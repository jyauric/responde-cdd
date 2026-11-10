"""Descarga los documentos públicos de Compromisos de Desempeño (CdD) 2026 desde gob.pe.

Fuente: https://www.gob.pe/110943-ministerio-de-educacion-compromisos-de-desempeno-2026
Uso:    python ai/ingesta.py
Salida: PDFs en data/normas/ y data/normas/fuentes.csv (trazabilidad de cada documento).
"""
import csv
from datetime import date
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parents[1]
CARPETA = RAIZ / "data" / "normas"
CDN = "https://cdn.www.gob.pe/uploads/document/file/"

# tipo:   "norma" = norma técnica CdD 2026 y sus modificatorias;
#         "publicacion" = publicación web aparte de la normativa.
# estado: "vigente" entra al RAG; cualquier otro valor se conserva solo como trazabilidad.
DOCUMENTOS = [
    {"archivo": "RM_057-2026-MINEDU.pdf", "tipo": "norma", "estado": "vigente",
     "titulo": "Resolución Ministerial N.° 057-2026-MINEDU",
     "url": CDN + "9392265/7696771-resolucion-ministerial-057-2026-minedu.pdf"},
    {"archivo": "RM_253-2026-MINEDU.pdf", "tipo": "norma", "estado": "sin efecto por RM 310-2026-MINEDU",
     "titulo": "Resolución Ministerial N.° 253-2026-MINEDU",
     "url": CDN + "9904008/7696771-resolucion-ministerial-n-253-2026-minedu.pdf"},
    {"archivo": "RM_00310-2026-MINEDU.pdf", "tipo": "norma", "estado": "vigente",
     "titulo": "Resolución Ministerial N.° 00310-2026-MINEDU",
     "url": CDN + "10056033/7696771-resolucion-ministerial-n-00310-2026-minedu.pdf"},
    {"archivo": "Canales_de_consulta_CdD_2026.pdf", "tipo": "publicacion", "estado": "vigente",
     "titulo": "Canales de consulta de los indicadores de los Compromisos de Desempeño 2026",
     "url": CDN + "9461621/7747829-canales-de-consulta-de-los-indicadores-de-los-compromisos-de-desempeno-2026-f.pdf"},
]


def descargar(doc: dict) -> Path:
    destino = CARPETA / doc["archivo"]
    if destino.exists():
        print(f"ya existe   {destino.name}")
        return destino
    r = requests.get(doc["url"], timeout=60)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise ValueError(f"{doc['url']} no devolvió un PDF")
    destino.write_bytes(r.content)
    print(f"descargado  {destino.name} ({len(r.content) / 1e6:.1f} MB)")
    return destino


def main() -> None:
    CARPETA.mkdir(parents=True, exist_ok=True)
    filas = []
    for doc in DOCUMENTOS:
        descargar(doc)
        filas.append({**doc, "fecha_descarga": date.today().isoformat()})
    with open(CARPETA / "fuentes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["archivo", "tipo", "estado", "titulo", "url", "fecha_descarga"])
        w.writeheader()
        w.writerows(filas)
    print(f"fuentes.csv con {len(filas)} documentos")


if __name__ == "__main__":
    main()
