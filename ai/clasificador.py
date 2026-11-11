"""Clasifica una consulta y redacta la respuesta con citas (salida estructurada de Gemini).

Uso de prueba:  python ai/clasificador.py "¿Hasta cuándo se envía el PUR consolidado?"

Regla de respuesta (D8), aplicada en código y no por el modelo:
  responde directo solo si (a) la respuesta está totalmente cubierta por los documentos,
  (b) cita al menos un fragmento y (c) la confianza es >= UMBRAL. Si no -> "Pendiente por validar".
"""
import json
import re
import sys
import time
from datetime import date
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
    hoy = date.today().strftime("%d/%m/%Y")
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
7. FECHAS: hoy es {hoy}. Si un plazo o fecha ya pasó, redacta en pasado ("el plazo venció el…", "debía remitirse
   hasta el…"); si aún no llega, en futuro.
8. ASISTENCIAS TÉCNICAS: la respuesta validada por el equipo sobre asistencias técnicas aplica a TODOS los
   indicadores (la evaluación de CdD 2026 ya culminó); úsala y cítala aunque mencione otro indicador.
9. FICHAS TÉCNICAS: al explicar condiciones de una ficha, usa su misma redacción; no agregues matices que la
   ficha no dice.
10. DESTINO: ponderadores, metas, MMA, cálculo de la transferencia, Anexos 1, 5, 6, 7 y 8 → DATOS.
11. Los fragmentos "Respuesta validada por el equipo de CdD" son respuestas que un especialista ya dio a una
   consulta igual o parecida: úsalos y cítalos como fuente válida. Si contradicen la norma, prevalece la norma.
12. Cita solo los IDs de fragmentos que realmente usaste. Escribe en español, claro y breve.

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


def generar(consulta: str, fragmentos: list, c, dato_verificado: str = "") -> Clasificacion:
    contexto = "\n\n".join(f"[ID {f['id']}] {rag.etiqueta(f)}\n{f['texto']}" for f in fragmentos)
    contenido = f"FRAGMENTOS:\n{contexto}\n\n{dato_verificado}CONSULTA:\n{consulta}"
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
                u = r.usage_metadata  # tokens usados (para el costo por consulta del modelo de negocio)
                resultado._tokens = {"entrada": u.prompt_token_count or 0, "salida": u.candidates_token_count or 0,
                                     "razonamiento": getattr(u, "thoughts_token_count", 0) or 0}
                return resultado
            except Exception as e:  # 429 / 503: esperar y reintentar; luego probar el modelo alternativo
                ultimo_error = e
                if not any(x in str(e) for x in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE")):
                    raise
                time.sleep(5 * (intento + 1))
    raise RuntimeError(f"Gemini no respondió: {ultimo_error}")


def responder(consulta: str, k: int = 8, aprendidas: list = None) -> dict:
    """aprendidas: filas de la hoja 'consultas' ya validadas por especialistas (sheets.aprendidas())."""
    c = rag.cliente()
    fragmentos = rag.buscar(consulta, k=k, c=c, aprendidas=rag.fragmentos_aprendidos(aprendidas or [], c))

    # D26/D29: participación verificada en código (Anexo 1 vs resultados publicados), antes de llamar al modelo.
    iged = participacion.detectar_iged(consulta)
    no_participa = iged is not None and participacion.participa(iged) is False
    region = participacion.region_de(iged) if iged else ""
    ugel_region = participacion.ugel_participantes(region) if no_participa and iged.startswith(("DRE", "GRE")) else []
    dato = ""
    if ugel_region:
        dato = (f"DATO VERIFICADO: la {iged} no participa en CdD 2026, pero en su región ({region}) participan "
                f"{len(ugel_region)} UGEL: {', '.join(ugel_region)}. Como la DRE/GRE supervisa a sus UGEL, responde "
                "la consulta con información general útil para su región (sin repetir lo de la no participación).\n\n")

    r = generar(consulta, fragmentos, c, dato)
    por_id = {f["id"]: f for f in fragmentos}
    citas = [por_id[i] for i in r.fragmentos_citados if i in por_id]  # descarta IDs inventados
    # El destino de un indicador se corrige con el catálogo si el modelo eligió otro especialista.
    destino = r.destino
    if r.indicador and especialista_de(r.indicador) and destino in ESPECIALISTAS:
        destino = especialista_de(r.indicador)
    if not r.indicador and any(re.match(r"Anexo N° [15678]\b", f["seccion"]) for f in citas):
        destino = "DATOS"  # D19: Anexos 1, 5, 6, 7 y 8 los ve el equipo de Datos
    # D30: asistencia técnica → especialista del indicador si lo menciona; si no, Comunicaciones.
    if re.search(r"asistencia[s]? t[ée]cnica|capacitaci[óo]n", consulta, re.I):
        destino = especialista_de(r.indicador) if r.indicador and especialista_de(r.indicador) else "COMUNICACIONES"
    automatica = r.cubierto_totalmente and len(citas) > 0 and r.confianza >= UMBRAL
    respuesta, falta, cubierto, confianza = r.respuesta, r.falta, r.cubierto_totalmente, r.confianza

    if no_participa:
        todos, _ = rag.cargar_indice()
        req = next(f for f in todos if "requisito para su participación" in f["texto"])
        aviso = (f"La {iged} no participa en los Compromisos de Desempeño 2026: no figura entre las IGED con "
                 "resultados publicados porque no cumplió el requisito del numeral 6.10, literal b, de la Norma "
                 "Técnica (designar a su representante mediante Resolución de su Titular, remitida a la UFD dentro "
                 "de los quince días hábiles posteriores a la publicación de la norma).")
        # D29: destino = especialista del indicador mencionado; si no hay indicador, equipo de Implementación.
        destino = especialista_de(r.indicador) if r.indicador and especialista_de(r.indicador) else "IMPLEMENTACION"
        if ugel_region:  # DRE/GRE: aviso + respuesta general para su región
            respuesta = aviso + f"\n\nPara su región ({region}), donde participan {len(ugel_region)} UGEL: " + r.respuesta
            citas = [req] + [f for f in citas if f is not req]
        else:  # UGEL que no participa: solo el aviso
            respuesta, falta, cubierto, confianza, automatica = aviso, None, True, 1.0, True
            res = next((f for f in todos if f["archivo"].startswith("Resultados")), None)
            citas = [req] + ([res] if res else [])

    return {
        "consulta": consulta,
        "estado": "Respondida automáticamente" if automatica else "Pendiente por validar",
        "destino": destino, "indicador": r.indicador, "iged": iged or r.iged, "tema": r.tema,
        "cubierto_totalmente": cubierto, "confianza": confianza,
        "respuesta": respuesta, "falta": falta,
        "citas": [{"etiqueta": rag.etiqueta(f), "archivo": f["archivo"], "url": f["url"],
                   "pagina": f["pagina"], "pagina_fin": f.get("pagina_fin") or f["pagina"],
                   "impresa": f["impresa"]} for f in citas],
        "modelo": getattr(r, "_modelo", None),
        "tokens": getattr(r, "_tokens", None),
        "uso_respuesta_equipo": any(f["archivo"] == "base_equipo" for f in citas),
    }


if __name__ == "__main__":
    print(json.dumps(responder(" ".join(sys.argv[1:])), ensure_ascii=False, indent=2))
