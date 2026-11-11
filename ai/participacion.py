"""¿Participa una IGED en CdD 2026? Verificación determinística (sin IA).

Regla (D26): la lista válida es la de IGED con resultados publicados en gob.pe (Resultados_CdD_2026.md).
Una IGED que está en el Anexo N° 1 pero no tiene resultados publicados no participa, por no cumplir
el numeral 6.10 literal b de la Norma Técnica (designación del representante dentro del plazo).
"""
import difflib
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
NORMA = RAIZ / "data" / "normas_md" / "RM_057-2026-MINEDU.md"
RESULTADOS = RAIZ / "data" / "normas_md" / "Resultados_CdD_2026.md"


def clave(nombre: str) -> str:
    """Normaliza un nombre de IGED para compararlo: sin tildes, guiones ni espacios, en mayúsculas."""
    nombre = re.sub(r"<[^>]+>", " ", nombre)  # etiquetas como <br> o <sup>
    nombre = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().upper()
    nombre = re.sub(r"\bIB\b", "INTERCULTURAL BILINGUE", nombre)  # "UGEL IB RIO SANTIAGO"
    nombre = re.sub(r"[^A-Z0-9]", "", nombre)
    return re.sub(r"^GRE", "DRE", nombre)  # algunas regiones usan GRE en lugar de DRE


@lru_cache(maxsize=1)
def anexo1() -> dict:
    """{clave: nombre} de las IGED del Anexo N° 1."""
    texto = NORMA.read_text(encoding="utf-8")
    inicio = texto.index("Anexo N° 1: Listado de IGED que participan")
    tramo = texto[inicio:texto.index("Ficha técnica", inicio) if "Ficha técnica" in texto[inicio:] else None]
    igeds = {}
    for linea in tramo.split("\n"):
        celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
        if len(celdas) == 4 and celdas[3].startswith(("DRE", "GRE", "UGEL")) and celdas[2] not in ("NOMBRE DE ENTIDAD",):
            igeds[clave(celdas[2])] = re.sub(r"<[^>]+>", " ", celdas[2]).strip()
            REGIONES.add(clave(celdas[0]))
            REGION_DE[clave(celdas[2])] = celdas[0].title()
    return igeds


REGIONES = set()
REGION_DE = {}


def region_de(iged: str) -> str:
    """Región de una IGED según el Anexo N° 1 ('' si no se reconoce)."""
    if not iged:
        return ""
    anexo1()
    k = clave(iged)
    if k not in REGION_DE:
        # Nombres que existen en más de una región ("UGEL La Unión": Arequipa y Piura) quedan sin región.
        empiezan = [x for x in REGION_DE if x.startswith(k)]
        if len(empiezan) > 1:
            return ""
        cercano = empiezan or difflib.get_close_matches(k, REGION_DE.keys(), n=1, cutoff=0.9)
        k = cercano[0] if cercano else k
    return REGION_DE.get(k, "")


def emparejar(k: str, region: str = ""):
    """Lleva el nombre de un PDF publicado a su IGED del Anexo N° 1.
    Algunos PDF llevan la región como prefijo ("amazonas-ugel-bagua") o tienen erratas ("trujilllo")."""
    a = anexo1()
    if k in a:
        return k
    for r in sorted(REGIONES, key=len, reverse=True):
        resto = re.sub(r"^GRE", "DRE", k[len(r):])
        if k.startswith(r) and resto in a:
            return resto
    k = re.sub(r"\d$", "", k)  # sufijo de archivo duplicado ("ugel-la-union-2")
    if k + clave(region) in a:  # nombres repetidos en dos regiones ("UGEL LA UNION - PIURA")
        return k + clave(region)
    cercano = difflib.get_close_matches(k, a.keys(), n=1, cutoff=0.85)
    return cercano[0] if cercano else None


@lru_cache(maxsize=1)
def publicadas() -> set:
    """Claves de las IGED con resultados publicados en algún tramo."""
    claves = set()
    for linea in RESULTADOS.read_text(encoding="utf-8").split("\n"):
        celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
        if len(celdas) == 3 and celdas[1].startswith("http"):
            for n in celdas[2].split(","):
                if n.strip():
                    claves.add(emparejar(clave(n), celdas[0]) or f"SIN_EMPAREJAR:{n.strip()}")
    return claves


def participa(iged: str):
    """True / False si la IGED está en el Anexo N° 1; None si no se reconoce el nombre."""
    if not iged:
        return None
    k = clave(iged)
    if k not in anexo1():
        return None
    return k in publicadas()


if __name__ == "__main__":
    print(f"Anexo N° 1: {len(anexo1())} IGED · con resultados publicados: {len(publicadas() & set(anexo1()))}")
    print("Nombres publicados sin emparejar:", sorted(k for k in publicadas() if k.startswith("SIN_EMPAREJAR")))
    for nombre in ["DRE Cusco", "UGEL Cusco", "UGEL Espinar", "UGEL Bagua", "GRE La Libertad", "UGEL Inventada"]:
        print(f"{nombre}: {participa(nombre)}")
