"""Registra dónde se publican los resultados de CdD 2026 por IGED (páginas web oficiales de gob.pe).

Uso:    python ai/publicaciones.py
Salida: data/normas_md/Resultados_CdD_2026.md (indexado por el RAG) y una fila en data/normas/fuentes.csv.
Guarda los enlaces por región y los nombres de las IGED cuyo PDF de resultados está publicado; no descarga
los PDF. Según la founder (11/11/2026), una IGED del Anexo 1 sin PDF publicado es una IGED que no participa
en CdD 2026 por no cumplir una condición de la Norma Técnica.
"""
import csv
import html
import re
from datetime import date
from pathlib import Path

import time

import requests

RAIZ = Path(__file__).resolve().parents[1]
SALIDA = RAIZ / "data" / "normas_md" / "Resultados_CdD_2026.md"
FUENTES = RAIZ / "data" / "normas" / "fuentes.csv"
GOB = "https://www.gob.pe"
PAGINA = GOB + "/114689-ministerio-de-educacion-resultados-de-los-compromisos-de-desempeno-2026"
COLECCIONES = [  # enlaces verificados en la página "Resultados" el 11/11/2026
    ("Tramo 1", "Resultados preliminares", GOB + "/institucion/minedu/colecciones/96595-resultados-preliminares-tramo-1"),
    ("Tramo 1", "Resultados finales", GOB + "/institucion/minedu/colecciones/97304-resultados-finales-tramo-1"),
    ("Tramo 2", "Resultados preliminares", GOB + "/institucion/minedu/colecciones/98849-resultados-preliminares-tramo-2"),
]
PDF = re.compile(r'href="https://cdn\.www\.gob\.pe/uploads/document/file/\d+/\d+-([^".?]+)\.pdf')
ENLACE = re.compile(r'<a[^>]+href="(/institucion/minedu/informes-publicaciones/\d+-resultados-[^"]+)"[^>]*>(.*?)</a>', re.S)
# gob.pe responde 418 al agente por defecto de "requests"; nos identificamos con un nombre propio y descriptivo.
CABECERAS = {"User-Agent": "responde-cdd/0.1 (proyecto academico; lectura de publicaciones oficiales)"}


def obtener(url: str, **params) -> str:
    """GET con pausa entre consultas (para no saturar gob.pe) y reintentos."""
    for intento in range(4):
        try:
            time.sleep(2)
            r = requests.get(url, params=params or None, headers=CABECERAS, timeout=40)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            if intento == 3:
                raise
            print(f"  reintento en {15 * (intento + 1)}s ({type(e).__name__})")
            time.sleep(15 * (intento + 1))


def texto(fragmento: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragmento)).split())


def regiones(url: str) -> dict:
    """Publicaciones por región de una colección (recorre la paginación)."""
    encontradas, hoja = {}, 1
    while True:
        nuevas = {texto(t): GOB + h for h, t in ENLACE.findall(obtener(url, sheet=hoja))}
        nuevas = {t: h for t, h in nuevas.items() if t not in encontradas}
        if not nuevas:
            return encontradas
        encontradas.update(nuevas)
        hoja += 1



def igeds(url: str) -> list:
    """IGED con resultados publicados: nombres de los PDF que muestra la página de la región."""
    vistos = []
    for nombre in PDF.findall(obtener(url)):
        nombre = nombre.replace("-", " ").upper()
        if nombre not in vistos:
            vistos.append(nombre)
    return vistos


def main() -> None:
    hoy = date.today().strftime("%d/%m/%Y")
    lineas = [
        "# Resultados de los Compromisos de Desempeño 2026 por IGED: dónde consultarlos",
        "",
        f"Fuente: página oficial \"Resultados\" de CdD 2026 en gob.pe: {PAGINA} (enlaces verificados el {hoy}).",
        "Los resultados se publican por tramo y por región. En la página de cada región hay un archivo PDF por "
        "IGED que participa. Para conocer el resultado de una IGED, se ingresa al tramo, luego a la región "
        "y se abre el PDF con el nombre de la IGED.",
        "Si una IGED quiere observar su resultado, la consulta se deriva al especialista del indicador, "
        "quien valida el resultado de cada indicador.",
        "",
    ]
    for tramo, tipo, url in COLECCIONES:
        regs = regiones(url)
        lineas += [f"## {tipo} - {tramo}", "", f"Colección: {url}", "",
                   "| Región | Página de resultados | IGED con resultados publicados |", "|---|---|---|"]
        for nombre, enlace in sorted(regs.items()):
            region = re.sub(rf"^{tipo}\s+(región\s+)?|\s*-\s*{tramo}$", "", nombre, flags=re.I).strip()
            lineas.append(f"| {region} | {enlace} | {', '.join(igeds(enlace))} |")
        lineas.append("")
        print(f"{tipo} - {tramo}: {len(regs)} regiones")
    SALIDA.write_text("<!-- pagina: 1 -->\n" + "\n".join(lineas) + "\n", encoding="utf-8")

    with open(FUENTES, encoding="utf-8") as f:
        filas = [r for r in csv.DictReader(f) if r["archivo"] != SALIDA.name]
    filas.append({"archivo": SALIDA.name, "tipo": "publicacion", "estado": "vigente",
                  "titulo": "Resultados de los Compromisos de Desempeño 2026 (publicación web)",
                  "url": PAGINA, "fecha_descarga": date.today().isoformat()})
    with open(FUENTES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["archivo", "tipo", "estado", "titulo", "url", "fecha_descarga"])
        w.writeheader()
        w.writerows(filas)
    print(f"{SALIDA.name} escrito y registrado en fuentes.csv")


if __name__ == "__main__":
    main()
