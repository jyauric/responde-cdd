"""RAG sobre la normativa CdD 2026: fragmentos por sección, embeddings con Gemini y búsqueda.

Construir el índice (una sola vez, o cuando cambien las normas):
    python ai/rag.py construir
Probar una búsqueda:
    python ai/rag.py buscar "¿hasta cuándo se presenta el PUR?"

Salida: data/indice/fragmentos.json (texto + metadatos) y data/indice/vectores.npy.
"""
import collections
import csv
import json
import math
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types

RAIZ = Path(__file__).resolve().parents[1]
NORMAS_MD = RAIZ / "data" / "normas_md"
FUENTES = RAIZ / "data" / "normas" / "fuentes.csv"
INDICE = RAIZ / "data" / "indice"

MODELO_EMBEDDING = "gemini-embedding-001"
DIMENSION = 768          # vectores más livianos; se normalizan para usar similitud coseno
MAX_CARACTERES = 2500    # tamaño máximo de un fragmento
LOTE = 20                # textos por llamada de embeddings

# ---------------------------------------------------------------- Secciones
MARCADOR = re.compile(r"<!-- pagina: (\d+)(?: \| impresa: (\d+))? -->")
ROMANA = re.compile(r"^#+\s*\**\s*(I|II|III|IV|V|VI|VII|VIII)\.\s+(.+?)\**\s*$")
NUMERAL = re.compile(r"^(?:#+|-)\s*\**\s*([67]\.\d{1,2})\.\s+(.+?)\**\s*$")
ANEXO = re.compile(r"^#+\s*\**\s*Anexo N°\s*(\d+)\s*:\s*(.+?)\**\s*$", re.I)
FICHA_COMPROMISO = re.compile(r"^#+\s*\**\s*Compromiso\s+(\d+)\s*:", re.I)
FICHA_INDICADOR = re.compile(r"^#+.*INDICADOR\s+(\d{1,2}\.\d)\b")
INICIO_NORMA = re.compile(r"^#\s+Norma Técnica\s*$")
SEPARADOR_TABLA = re.compile(r"^\s*\|(?:\s*:?-{3,}:?\s*\|)+\s*$")

# Canales de consulta: se excluye la columna con nombre, correo y celular de funcionarios (D16).
CORREO_O_FONO = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|Celular:\s*[\d\s-]+|Tel[ée]fono:[^|]*", re.I)


def limpiar_md(texto: str) -> str:
    texto = re.sub(r"</?(?:mark|u|sup)>", "", texto)
    texto = texto.replace("<br>", " ")
    return re.sub(r"[ \t]+", " ", texto)


def sin_datos_personales(linea: str, columnas: list) -> str:
    """Quita la columna 'Canal de consulta' de las tablas de Canales y cualquier correo o teléfono."""
    if linea.lstrip().startswith("|") and "Canal de consulta" in columnas:
        celdas = linea.strip()[1:-1].split("|")
        idx = columnas.index("Canal de consulta")
        if len(celdas) == len(columnas):
            celdas.pop(idx)
            linea = "|" + "|".join(celdas) + "|"
        # Solo en tablas: el párrafo inicial tiene los canales institucionales generales, que se conservan.
        linea = CORREO_O_FONO.sub("[ver documento oficial]", linea)
    return linea


def leer_fuentes() -> dict:
    with open(FUENTES, encoding="utf-8") as f:
        return {Path(r["archivo"]).stem: r for r in csv.DictReader(f) if r["estado"] == "vigente"}


def fragmentar(stem: str, fuente: dict) -> list:
    """Recorre el Markdown línea a línea y corta cada vez que cambia la sección."""
    texto = (NORMAS_MD / f"{stem}.md").read_text(encoding="utf-8")
    es_norma = stem.startswith("RM_057")
    es_canales = stem.startswith("Canales")
    seccion = "Resolución Ministerial" if es_norma else fuente["titulo"]
    indicador, pagina, impresa = None, 1, None
    actual, fragmentos, cabecera_tabla, columnas = [], [], None, []

    def cerrar():
        cuerpo = "\n".join(actual).strip()
        if len(re.sub(r"\W", "", cuerpo)) >= 40:
            fragmentos.append({
                "archivo": fuente["archivo"], "documento": fuente["titulo"], "url": fuente["url"],
                "seccion": seccion, "indicador": indicador,
                "pagina": inicio[0], "impresa": inicio[1],
                "pagina_fin": pagina, "impresa_fin": impresa, "texto": cuerpo,
            })
        actual.clear()

    inicio = (pagina, impresa)
    for linea in texto.split("\n"):
        m = MARCADOR.match(linea.strip())
        if m:
            pagina, impresa = int(m.group(1)), int(m.group(2)) if m.group(2) else None
            if not actual:
                inicio = (pagina, impresa)
            continue

        nueva = None
        if es_norma and INICIO_NORMA.match(linea):
            nueva = ("Norma Técnica (portada e índice)", None)
        elif (r := ROMANA.match(linea)):
            nueva = (f"Sección {r.group(1)}. {r.group(2)}", None)
        elif (n := NUMERAL.match(linea)):
            nueva = (f"Numeral {n.group(1)}. {n.group(2)}", None)
        elif (a := ANEXO.match(linea)):
            nueva = (f"Anexo N° {a.group(1)}: {a.group(2)}", None)
        elif (c := FICHA_COMPROMISO.match(linea)):
            nueva = (f"Anexo N° 2: Ficha técnica del Compromiso {c.group(1)}", None)
        elif (i := FICHA_INDICADOR.match(linea)) and i.group(1) != indicador:
            num = i.group(1)
            nueva = (f"Anexo N° 2: Ficha técnica del indicador {num}", num)

        if nueva:
            cerrar()
            seccion, indicador = nueva
            inicio = (pagina, impresa)
            cabecera_tabla = None

        # Cabecera de tabla: se repite al inicio de cada fragmento que continúa la tabla.
        if linea.lstrip().startswith("|"):
            if cabecera_tabla is None or SEPARADOR_TABLA.match(linea):
                if cabecera_tabla is None:
                    columnas = [re.sub(r"\W+", " ", c).strip() for c in limpiar_md(linea).strip()[1:-1].split("|")]
                    columnas = ["Canal de consulta" if "Canal de consulta" in c else c for c in columnas]
                cabecera_tabla = (cabecera_tabla or []) + [linea]
        else:
            cabecera_tabla = None if linea.strip() else cabecera_tabla

        if es_canales:
            linea = sin_datos_personales(linea, columnas)
        actual.append(limpiar_md(linea))

        if sum(len(l) for l in actual) > MAX_CARACTERES and not linea.strip().startswith("|---"):
            cerrar()
            inicio = (pagina, impresa)
            if cabecera_tabla:
                actual.extend(limpiar_md(sin_datos_personales(l, columnas) if es_canales else l)
                              for l in cabecera_tabla[:2])
    cerrar()
    return fragmentos


def etiqueta(f: dict) -> str:
    """Cómo se cita un fragmento (D21): documento, sección y página impresa si existe."""
    cita = f"{f['documento']} · {f['seccion']}"
    if not f.get("impresa"):
        return cita
    fin = f.get("impresa_fin")
    return cita + (f" · pp. {f['impresa']}-{fin}" if fin and fin != f["impresa"] else f" · p. {f['impresa']}")


# ---------------------------------------------------------------- Embeddings
def cliente() -> genai.Client:
    load_dotenv(RAIZ / ".env")
    clave = os.getenv("GEMINI_API_KEY")
    if not clave:
        raise RuntimeError("Falta GEMINI_API_KEY en .env (local) o en los secrets de Streamlit.")
    return genai.Client(api_key=clave)


def embeddings(textos: list, tarea: str, c: genai.Client) -> np.ndarray:
    vectores = []
    for i in range(0, len(textos), LOTE):
        lote = textos[i:i + LOTE]
        for intento in range(6):
            try:
                r = c.models.embed_content(
                    model=MODELO_EMBEDDING, contents=lote,
                    config=types.EmbedContentConfig(task_type=tarea, output_dimensionality=DIMENSION),
                )
                vectores.extend(e.values for e in r.embeddings)
                break
            except Exception as e:  # límite por minuto (429) o alta demanda (503): esperar y reintentar
                if intento == 5 or not any(code in str(e) for code in ("429", "503", "RESOURCE_EXHAUSTED")):
                    raise
                espera = 20 * (intento + 1)
                print(f"  límite alcanzado, espero {espera}s… ({str(e)[:80]})")
                time.sleep(espera)
        if len(textos) > LOTE:
            print(f"  {min(i + LOTE, len(textos))}/{len(textos)} fragmentos")
            time.sleep(1)
    v = np.array(vectores, dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def construir() -> None:
    fragmentos = []
    for stem, fuente in leer_fuentes().items():
        partes = fragmentar(stem, fuente)
        print(f"{fuente['archivo']}: {len(partes)} fragmentos")
        fragmentos.extend(partes)
    for i, f in enumerate(fragmentos):
        f["id"] = i
    textos = [f"{etiqueta(f)}\n\n{f['texto']}" for f in fragmentos]
    # Reutiliza los vectores ya calculados si el texto del fragmento no cambió (ahorra cuota).
    previos = {}
    if (INDICE / "fragmentos.json").exists():
        viejos = json.loads((INDICE / "fragmentos.json").read_text(encoding="utf-8"))
        vv = np.load(INDICE / "vectores.npy")
        previos = {f["texto"]: vv[i] for i, f in enumerate(viejos)}
    nuevos = [i for i, f in enumerate(fragmentos) if f["texto"] not in previos]
    print(f"Reutilizados: {len(fragmentos) - len(nuevos)} · nuevos a calcular: {len(nuevos)}")
    calculados = embeddings([textos[i] for i in nuevos], "RETRIEVAL_DOCUMENT", cliente()) if nuevos else []
    mapa = dict(zip(nuevos, calculados))
    vectores = np.array([mapa[i] if i in mapa else previos[f["texto"]] for i, f in enumerate(fragmentos)],
                        dtype=np.float32)
    INDICE.mkdir(parents=True, exist_ok=True)
    (INDICE / "fragmentos.json").write_text(json.dumps(fragmentos, ensure_ascii=False, indent=1), encoding="utf-8")
    np.save(INDICE / "vectores.npy", vectores)
    print(f"Índice guardado: {len(fragmentos)} fragmentos, vectores {vectores.shape}")


# ---------------------------------------------------------------- Búsqueda
_cache = {}


def cargar_indice():
    if "fragmentos" not in _cache:
        _cache["fragmentos"] = json.loads((INDICE / "fragmentos.json").read_text(encoding="utf-8"))
        _cache["vectores"] = np.load(INDICE / "vectores.npy")
    return _cache["fragmentos"], _cache["vectores"]


PESO_LEXICO = 0.2         # búsqueda híbrida: 80 % significado (embeddings) + 20 % palabras en común
MAX_POR_SECCION = 2       # diversidad: evita que una sola sección ocupe todos los resultados
VACIAS = set("de la el en y a los las del que por para con se su al o un una es no lo como sus le ya este esta "
             "son ser han ha nos".split())


def _palabras(texto: str) -> list:
    return [w for w in re.findall(r"[a-záéíóúñü]{3,}", texto.lower()) if w not in VACIAS]


def _lexico(consulta: str, fragmentos: list) -> np.ndarray:
    """Puntaje TF-IDF simple: palabras de la consulta presentes en el fragmento, ponderadas por rareza."""
    if "df" not in _cache:
        _cache["tf"] = [collections.Counter(_palabras(f["texto"])) for f in fragmentos]
        _cache["df"] = collections.Counter(w for tf in _cache["tf"] for w in tf)
    n, df = len(fragmentos), _cache["df"]
    q = set(_palabras(consulta))
    s = np.array([sum((1 + math.log(tf[w])) * math.log(n / df[w]) for w in q if tf[w]) for tf in _cache["tf"]])
    return s / s.max() if s.max() > 0 else s


def buscar(consulta: str, k: int = 8, c: genai.Client = None) -> list:
    """Devuelve los k fragmentos más relevantes (búsqueda híbrida con diversidad), con su puntaje."""
    fragmentos, vectores = cargar_indice()
    q = embeddings([consulta], "RETRIEVAL_QUERY", c or cliente())[0]
    puntajes = (1 - PESO_LEXICO) * (vectores @ q) + PESO_LEXICO * _lexico(consulta, fragmentos)
    # Si la consulta menciona un indicador (p. ej. "3.1"), se favorece su ficha técnica.
    mencionados = set(re.findall(r"\b(\d{1,2}\.\d)\b", consulta))
    for i, f in enumerate(fragmentos):
        if f.get("indicador") in mencionados:
            puntajes[i] += 0.05
    elegidos, por_seccion = [], collections.Counter()
    for i in np.argsort(-puntajes):
        clave = (fragmentos[i]["archivo"], fragmentos[i]["seccion"])
        if por_seccion[clave] >= MAX_POR_SECCION:
            continue
        por_seccion[clave] += 1
        elegidos.append(i)
        if len(elegidos) == k:
            break
    return [{**fragmentos[i], "puntaje": float(puntajes[i])} for i in elegidos]


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "construir":
        construir()
    elif len(sys.argv) >= 3 and sys.argv[1] == "buscar":
        for r in buscar(" ".join(sys.argv[2:])):
            print(f"{r['puntaje']:.3f} | {etiqueta(r)} | {r['texto'][:120]!r}")
    else:
        print(__doc__)
