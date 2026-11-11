"""Procesa las consultas de ejemplo con el flujo real (RAG + clasificador) y las registra en la hoja.

Uso: python data/sinteticos/procesar.py
"""
import csv
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "ai"))
sys.path.insert(0, str(RAIZ / "backend"))
import clasificador  # noqa: E402
import sheets  # noqa: E402

with open(Path(__file__).parent / "consultas_ejemplo.csv", encoding="utf-8") as f:
    filas = list(csv.DictReader(f))
aprendidas = sheets.aprendidas()
for n, fila in enumerate(filas, start=1):
    r = clasificador.responder(fila["consulta"], aprendidas=aprendidas)
    nro = sheets.registrar(r, fila["canal"])
    print(f"{n:2d}. N°{nro} | {r['estado'][:12]} | {r['destino']:<14} | {r['iged'] or '-':<22} | {r['respuesta'][:110]}")
    time.sleep(4)  # margen para el límite por minuto del plan gratuito
