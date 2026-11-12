"""Convierte a Markdown los PDF vigentes de data/normas/ (según fuentes.csv).

Uso:    python ai/convertir_md.py
Salida: data/normas_md/<archivo>.md, con un marcador por página:
        <!-- pagina: N | impresa: M -->
        N = página del visor del PDF (uso interno: enlace e imagen de la página);
        M = número impreso en la hoja (el que se muestra en las citas), si existe.

Los PDF siguen siendo la fuente oficial; estos .md son derivados y no se editan a mano.
Limpieza aplicada:
  1. Quita el encabezado repetido de cada página ("Norma técnica | Código | Disposiciones...").
  2. Quita el sello de firma digital y los números de página impresos.
  3. Separa palabras que la conversión pegó (p. ej. "adecuadayoportunamente"),
     solo si cada parte (de 4+ letras, o unida por "y"/"de") aparece en ambas extracciones del PDF.
  4. Reconstruye las tablas de los Anexos 3, 4 y 5 con el catálogo de ai/catalogo.py:
     columna "Compromiso" separada de "N°" y nombres completos de compromisos e indicadores.
"""
import csv
import re
import sys
import unicodedata
from pathlib import Path

import pymupdf
import pymupdf4llm
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalogo import COMPROMISOS, INDICADORES, compromiso_de  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
ORIGEN = RAIZ / "data" / "normas"
DESTINO = RAIZ / "data" / "normas_md"

# ---------------------------------------------------------------- 1-2. Ruido
PALABRAS_ENCABEZADO = set(
    "norma técnica tecnica código codigo disposiciones para la implementación implementacion "
    "del mecanismo de financiamiento por desempeño denominado compromisos 2026".split()
)
FIRMA = [
    re.compile(r"Documento electr[óo]nico firmado digitalmente.*?clave:\s*\w+", re.S | re.I),
    re.compile(r"Esto es una copia aut[ée]ntica imprimible.*?clave:\s*\w+", re.S | re.I),
    # Bloque de imagen con los sellos de firma (nombres + "FAU 20131370998").
    re.compile(r"<!-- Start of picture text -->(?:(?!<!-- End).)*?FAU \d+.*?<!-- End of picture text -->", re.S),
]
FRASE_ENCABEZADO = re.compile(
    r"Norma\s+t[ée]cnica\s+C[óo]digo\s+Disposiciones\s+para\s+la\s+implementaci[óo]n\s+del\s+mecanismo\s+de\s+"
    r"financiamiento\s+por\s+desempe[ñn]o\s+denominado\s+“?Compromisos\s+de\s+Desempe[ñn]o\s+2026”?", re.I)
SELLO_FIRMA = re.compile(r"FAU \d{11}")  # línea de sello de firma digital (nombre, cargo, fecha)
NUMERO_PAGINA = re.compile(r"^\s*(?:<mark>)?\d{1,3}(?:</mark>)?\s*$")
SEPARADOR_TABLA = re.compile(r"^\s*\|(?:\s*:?-{3,}:?\s*\|)+\s*$")


def palabras(texto: str) -> set:
    texto = unicodedata.normalize("NFKC", texto).lower()
    return set(re.findall(r"[a-záéíóúñü0-9]+", texto))


def es_encabezado(linea: str) -> bool:
    """Línea (o fila de tabla) formada solo por palabras del encabezado de página."""
    if linea.lstrip().startswith("#"):
        return False
    p = palabras(linea.replace("<br>", " "))
    return len(p) >= 2 and p <= PALABRAS_ENCABEZADO


def numero_impreso(texto: str):
    """Número de página impreso en la hoja (pie de página), antes de limpiarlo."""
    for linea in reversed(texto.split("\n")):
        if NUMERO_PAGINA.match(linea):
            return int(re.sub(r"\D", "", linea))
    return None


def quitar_ruido(texto: str) -> str:
    for patron in FIRMA:
        texto = patron.sub("", texto)
    texto = FRASE_ENCABEZADO.sub("", texto)
    lineas = [l for l in texto.split("\n") if not es_encabezado(l) and not NUMERO_PAGINA.match(l) and not SELLO_FIRMA.search(l)]
    # Separadores de tabla que quedaron sueltos al quitar un encabezado.
    limpias = []
    for l in lineas:
        if SEPARADOR_TABLA.match(l):
            prev = limpias[-1] if limpias else ""
            if not prev.lstrip().startswith("|") or SEPARADOR_TABLA.match(prev):
                continue
        limpias.append(l)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(limpias)).strip()


# ---------------------------------------------------------------- 3. Palabras pegadas
CORTAS = {"y", "e", "o", "a", "u"}
UNIONES = CORTAS | {"de", "del", "la", "el"}


def separar_pegadas(texto: str, vocab_pdf: set, cambios: dict) -> str:
    def partir(palabra: str):
        w = palabra.lower()
        for i in range(2, len(w) - 1):
            a, b = w[:i], w[i:]
            if a in vocab_pdf and b in vocab_pdf and len(a) >= 4 and len(b) >= 4:
                return [palabra[:i], palabra[i:]]
            for j in range(i + 1, len(w) - 1):  # "adecuada" + "y" + "oportunamente"
                m, c = w[i:j], w[j:]
                if a in vocab_pdf and m in UNIONES and c in vocab_pdf and len(a) >= 3 and len(c) >= 3:
                    return [palabra[:i], palabra[i:j], palabra[j:]]
        return None

    def reemplazo(m):
        palabra = m.group(0)
        if len(palabra) < 8 or palabra.lower() in vocab_pdf:
            return palabra
        partes = partir(palabra)
        if not partes:
            return palabra
        nuevo = " ".join(partes)
        cambios[palabra] = nuevo
        return nuevo

    return re.sub(r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü]+", reemplazo, texto)


# ---------------------------------------------------------------- 4. Anexos 3, 4 y 5
INDICADOR = re.compile(r"^\d{1,2}\.\d$")
TRAMO = re.compile(r"Tramo\s+(\d)", re.I)
ENCABEZADOS = {
    3: ["N° Compromiso", "Compromiso", "N° Indicador", "Indicador", "Modalidad de Asignación"],
    4: ["N° Compromiso", "Compromiso", "N° Indicador", "Indicador", "Área responsable", "Área(s) de soporte"],
    5: ["N° Compromiso", "Compromiso", "Ponderador del compromiso", "N° Indicador", "Indicador",
        "Ponderador del indicador"],
}


def celda(texto: str) -> str:
    texto = re.sub(r"\*\*|<br>", " ", texto)
    texto = " ".join(texto.split())
    return re.sub(r"(\w)- (\w)", r"\1-\2", texto)  # "UGM- PRONIED" -> "UGM-PRONIED"


def filas_tabla(texto: str):
    for linea in texto.split("\n"):
        if linea.lstrip().startswith("|") and not SEPARADOR_TABLA.match(linea):
            yield [celda(c) for c in linea.strip()[1:-1].split("|")]


def leer_anexo(anexo: int, texto: str, pond_compromiso: dict) -> list:
    """Extrae las filas del anexo: ('tramo', n) o ('fila', [celdas])."""
    filas = []
    for celdas in filas_tabla(texto):
        n = next((c for c in celdas if INDICADOR.match(c)), None)
        tramo = next((TRAMO.search(c) for c in celdas if TRAMO.search(c)), None)
        if tramo and not n:
            filas.append(("tramo", tramo.group(1)))
            continue
        if not n:
            continue  # encabezados repetidos, nombre de la norma o restos de la conversión
        comp = compromiso_de(n)
        base = [str(comp), COMPROMISOS[comp]]
        if anexo == 3:
            filas.append(("fila", base + [n, INDICADORES[n], celdas[-1]]))
        elif anexo == 4:
            filas.append(("fila", base + [n, INDICADORES[n], celdas[-2], celdas[-1]]))
        else:
            if celdas[1]:
                pond_compromiso[comp] = celdas[1]
            filas.append(("fila", base + ["", n, INDICADORES[n], celdas[-1]]))
    return filas


def escribir_anexo(anexo: int, texto: str, filas: list, pond_compromiso: dict) -> str:
    cab = ENCABEZADOS[anexo]
    tabla = ["| " + " | ".join(cab) + " |", "|" + "---|" * len(cab)]
    for tipo, valor in filas:
        if tipo == "tramo":
            vacias = [""] * len(cab)
            vacias[3] = f"**Tramo {valor}**"
            tabla.append("| " + " | ".join(vacias) + " |")
        else:
            if anexo == 5:
                valor[2] = pond_compromiso.get(int(valor[0]), "")
            tabla.append("| " + " | ".join(valor) + " |")
    # Conserva el texto que no es tabla (p. ej., el título del anexo) y reemplaza las tablas.
    titulo = [l for l in texto.split("\n") if l.strip() and not l.lstrip().startswith("|")]
    return "\n".join(titulo + ([""] if titulo else []) + tabla)


# ---------------------------------------------------------------- Notas al pie
NOTA_PIE = re.compile(r"^> (\d+) (.+)$")


def mover_notas(texto: str, distancia: int = 40) -> str:
    """Coloca cada nota al pie ("> N texto") justo después del párrafo que la llama ("<sup>N</sup>").

    En el PDF la nota queda al pie de la página, a veces lejos de su llamada; si el RAG corta entre ambas,
    la IA recibe la regla sin su excepción (p. ej., la nota 1 del numeral 6.5 f.ii). Si no se encuentra la
    llamada en las líneas previas, la nota se deja donde está.
    """
    lineas = texto.split("\n")
    i = 0
    while i < len(lineas):
        m = NOTA_PIE.match(lineas[i])
        if m:
            marca = f"<sup>{m.group(1)}</sup>"
            for j in range(i - 1, max(i - distancia, 0) - 1, -1):
                if marca in lineas[j] and not lineas[j].lstrip().startswith("|"):
                    nota = f"> Nota al pie {m.group(1)}: {m.group(2)}"
                    del lineas[i]
                    lineas[j + 1:j + 1] = ["", nota]
                    i += 1  # la lista creció en una línea antes de i
                    break
        i += 1
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas))


# ---------------------------------------------------------------- Conversión
ANEXO = re.compile(r"Anexo N°\s*(\d+)\s*:", re.I)


def convertir(archivo: str) -> Path:
    ruta = ORIGEN / archivo
    vocab_pdf = set()
    for pagina in PdfReader(ruta).pages:
        vocab_pdf |= {w for w in palabras(pagina.extract_text() or "") if not w.isdigit()}

    paginas = pymupdf4llm.to_markdown(pymupdf.open(ruta), page_chunks=True, show_progress=False)
    # Solo palabras que aparecen en ambas extracciones (evita fragmentos como "anciar").
    vocab_pdf &= set().union(*(palabras(p["text"]) for p in paginas))
    impresas = [numero_impreso(p["text"]) for p in paginas]
    # Si el desfase visor-impresa es el mismo en todas las páginas detectadas, se completa
    # el número de las páginas cuyo pie no se pudo leer (solo después de la primera detectada).
    desfases = {i + 1 - n for i, n in enumerate(impresas) if n is not None}
    if len(desfases) == 1:
        desfase = desfases.pop()
        primera = next(i for i, n in enumerate(impresas) if n is not None)
        impresas = [n if n is not None or i < primera else i + 1 - desfase for i, n in enumerate(impresas)]
    textos = [quitar_ruido(p["text"]) for p in paginas]

    # Primera pasada: identificar páginas de los Anexos 3-5 y leer sus filas.
    anexo_de, filas_de, pond, actual = {}, {}, {}, None
    for i, texto in enumerate(textos):
        titulo = ANEXO.search(texto.split("\n", 1)[0]) if texto else None
        if titulo:
            actual = int(titulo.group(1))
        if actual in ENCABEZADOS and "|" in texto:
            anexo_de[i] = actual
            filas_de[i] = leer_anexo(actual, texto, pond)

    # Segunda pasada: escribir.
    cambios, partes = {}, []
    for i, texto in enumerate(textos):
        if i in anexo_de and filas_de[i]:
            texto = escribir_anexo(anexo_de[i], texto, filas_de[i], pond)
        else:
            texto = separar_pegadas(texto, vocab_pdf, cambios)
        marca = f"pagina: {i + 1}" + (f" | impresa: {impresas[i]}" if impresas[i] is not None else "")
        partes.append(f"<!-- {marca} -->\n{texto}")

    salida = DESTINO / (Path(archivo).stem + ".md")
    salida.write_text(mover_notas("\n\n".join(partes)) + "\n", encoding="utf-8")
    print(f"{archivo} -> {salida.name} ({len(paginas)} págs.)")
    if cambios:
        print("  palabras separadas:", "; ".join(f"{k} -> {v}" for k, v in sorted(cambios.items())))
    return salida


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    with open(ORIGEN / "fuentes.csv", encoding="utf-8") as f:
        vigentes = [fila["archivo"] for fila in csv.DictReader(f)
                    if fila["estado"] == "vigente" and fila["archivo"].endswith(".pdf")]
    for archivo in vigentes:
        convertir(archivo)


if __name__ == "__main__":
    main()
