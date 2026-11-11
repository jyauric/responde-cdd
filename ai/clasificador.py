"""Clasifica una consulta y redacta la respuesta con citas (salida estructurada de Gemini).

Uso de prueba:  python ai/clasificador.py "¿Hasta cuándo se envía el PUR consolidado?"

Regla de respuesta (D8), aplicada en código y no por el modelo:
  responde directo solo si (a) la respuesta está totalmente cubierta por los documentos,
  (b) cita al menos un fragmento y (c) la confianza es >= UMBRAL. Si no -> "Pendiente por validar".
"""
import json
import sys
import time
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field
from google.genai import types

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalogo import COMPROMISOS, EQUIPOS, ESPECIALISTAS, INDICADORES, TRAMOS, especialista_de  # noqa: E402
import participacion  # noqa: E402
import rag  # noqa: E402

UMBRAL = 0.8
MODELOS = ["gemini-3.5-flash", "gemini-3.5-flash-lite"]  # el segundo solo si el primero falla por demanda

Destino = Literal["A", "B", "C", "D", "E", "F", "G", "H",
                  "IMPLEMENTACION", "DATOS", "PRESUPUESTO", "COMUNICACIONES"]


class Clasificacion(BaseModel):
    destino: Destino = Field(description="Especialista (A-H) del indicador o equipo transversal que atiende la consulta.")
    indicador: Optional[str] = Field(None, description="Número del indicador si la consulta trata de uno (p. ej. '3.1').")
    iged: Optional[str] = Field(None, description="DRE/GRE o UGEL que consulta, si se menciona.")
    tema: str = Field(description="Tema de la consulta en pocas palabras.")
    cubierto_totalmente: bool = Field(description="True solo si TODA la respuesta está en los fragmentos.")
    confianza: float = Field(ge=0, le=1, description="Qué tan seguro estás de que la respuesta es correcta y completa.")
    respuesta: str = Field(description="Respuesta clara y breve, basada solo en los fragmentos.")
    fragmentos_citados: List[int] = Field(description="IDs de los fragmentos que sustentan la respuesta.")
    falta: Optional[str] = Field(None, description="Qué parte de la consulta no está en los documentos.")


def instrucciones() -> str:
    especialistas = "\n".join(
        f"- {e}: " + "; ".join(f"{i} {INDICADORES[i]}" for i in inds) for e, inds in ESPECIALISTAS.items())
    equipos = "\n".join(f"- {k}: {v}" for k, v in EQUIPOS.items())
    compromisos = "\n".join(f"- {n}. {t}" for n, t in COMPROMISOS.items())
    tramos = "\n".join(f"- {i}: Tramo " + " y ".join(map(str, t)) for i, t in TRAMOS.items())
    return f"""Eres el asistente del equipo de Compromisos de Desempeño (CdD) 2026. Respondes consultas de DRE/GRE y UGEL.

REGLAS
1. Responde SOLO con la información de los FRAGMENTOS. No uses conocimiento externo ni supongas.
2. Si algo no está en los fragmentos, márcalo como no cubierto (cubierto_totalmente = false) y explica en "falta".
3. Si la norma (RM 057-2026-MINEDU) y "Canales de consulta" no coinciden, prevalece la norma.
4. No escribas nombres, correos ni celulares de funcionarios; indica el área responsable o el canal institucional.
5. Resultados de una IGED: los fragmentos NO contienen los resultados en sí, pero sí DÓNDE se publican
   (por tramo, tipo -preliminar o final- y región). Si preguntan dónde verlos, indica el enlace exacto de su región
   y tramo tal como aparece en los fragmentos (la región se deduce del Anexo 1 o del nombre de la IGED);
   eso sí está cubierto. Si piden el valor de su resultado o quieren observarlo, no está cubierto: deriva al
   especialista del indicador (valida el resultado) o a DATOS (consolida y publica los resultados).
   No afirmes que existe el PDF de una IGED concreta: indica que busque el PDF de su IGED en esa página.
   Verifica el tramo del indicador con la lista TRAMOS; si la consulta menciona un tramo equivocado, acláralo.
   La lista "IGED con resultados publicados" de cada región es la válida. Si la IGED que consulta NO figura en
   esa lista de su región, responde que no participa en los Compromisos de Desempeño 2026 porque no cumplió el
   requisito del numeral 6.10 literal b de la Norma Técnica (designar a su representante mediante Resolución de
   su Titular dentro de los 15 días hábiles posteriores a la publicación de la norma); eso sí está cubierto.
6. Ampliaciones o prórrogas de plazo: la norma solo contempla el caso excepcional del numeral 6.5 literal h
   (interrupción de la plataforma o sistema el último día de cumplimiento). Explica eso si aparece en los fragmentos,
   pero marca la consulta como no cubierta: cada caso lo evalúa el especialista del indicador.
7. Cita solo los IDs de fragmentos que realmente usaste. Escribe en español, claro y breve.

DERIVACIÓN
Especialistas por indicador:
{especialistas}
Equipos transversales:
{equipos}
Si la consulta es sobre un indicador específico, va a su especialista; si es transversal, al equipo.

COMPROMISOS
{compromisos}

TRAMOS (Anexo N° 3: en qué tramo se evalúa cada indicador)
{tramos}"""


def generar(consulta: str, fragmentos: list, c) -> Clasificacion:
    contexto = "\n\n".join(f"[ID {f['id']}] {rag.etiqueta(f)}\n{f['texto']}" for f in fragmentos)
    contenido = f"FRAGMENTOS:\n{contexto}\n\nCONSULTA:\n{consulta}"
    config = types.GenerateContentConfig(
        system_instruction=instrucciones(), temperature=0.2,
        response_mime_type="application/json", response_schema=Clasificacion,
    )
    ultimo_error = None
    for modelo in MODELOS:
        for intento in range(3):
            try:
                r = c.models.generate_content(model=modelo, contents=contenido, config=config)
                resultado = r.parsed or Clasificacion.model_validate_json(r.text)
                resultado._modelo = modelo
                return resultado
            except Exception as e:  # 429 / 503: esperar y reintentar; luego probar el modelo alternativo
                ultimo_error = e
                if not any(x in str(e) for x in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE")):
                    raise
                time.sleep(5 * (intento + 1))
    raise RuntimeError(f"Gemini no respondió: {ultimo_error}")


def responder(consulta: str, k: int = 8) -> dict:
    c = rag.cliente()
    fragmentos = rag.buscar(consulta, k=k, c=c)
    r = generar(consulta, fragmentos, c)
    por_id = {f["id"]: f for f in fragmentos}
    citas = [por_id[i] for i in r.fragmentos_citados if i in por_id]  # descarta IDs inventados
    # El destino de un indicador se corrige con el catálogo si el modelo eligió otro especialista.
    destino = r.destino
    if r.indicador and especialista_de(r.indicador) and destino in ESPECIALISTAS:
        destino = especialista_de(r.indicador)
    automatica = r.cubierto_totalmente and len(citas) > 0 and r.confianza >= UMBRAL
    respuesta, falta, cubierto, confianza = r.respuesta, r.falta, r.cubierto_totalmente, r.confianza

    # D26: si la IGED está en el Anexo N° 1 pero no tiene resultados publicados, no participa.
    # Se decide en código (no por el modelo) y se cita el numeral 6.10 b y la página de resultados.
    if participacion.participa(r.iged) is False:
        todos, _ = rag.cargar_indice()
        req = next(f for f in todos if "requisito para su participación" in f["texto"])
        res = next((f for f in todos if f["archivo"].startswith("Resultados")), None)
        citas = [req] + ([res] if res else [])
        respuesta = (f"La {r.iged} no participa en los Compromisos de Desempeño 2026: no figura entre las IGED con "
                     "resultados publicados porque no cumplió el requisito del numeral 6.10, literal b, de la Norma "
                     "Técnica, que establece que la designación del representante de la IGED (mediante Resolución "
                     "de su Titular, remitida a la UFD dentro de los quince días hábiles posteriores a la publicación "
                     "de la norma) es requisito para su participación en el mecanismo.")
        falta, cubierto, confianza, automatica, destino = None, True, 1.0, True, "DATOS"

    return {
        "consulta": consulta,
        "estado": "Respondida automáticamente" if automatica else "Pendiente por validar",
        "destino": destino, "indicador": r.indicador, "iged": r.iged, "tema": r.tema,
        "cubierto_totalmente": cubierto, "confianza": confianza,
        "respuesta": respuesta, "falta": falta,
        "citas": [{"etiqueta": rag.etiqueta(f), "archivo": f["archivo"], "url": f["url"],
                   "pagina": f["pagina"], "pagina_fin": f.get("pagina_fin") or f["pagina"],
                   "impresa": f["impresa"]} for f in citas],
        "modelo": getattr(r, "_modelo", None),
    }


if __name__ == "__main__":
    print(json.dumps(responder(" ".join(sys.argv[1:])), ensure_ascii=False, indent=2))
