"""Registro de consultas en Google Sheets y base de conocimiento que aprende de los especialistas.

Hoja "consultas": una fila por consulta. El especialista escribe su respuesta en "respuesta_especialista"
y cambia "estado" a "Respondido". La app la incorpora a la base de conocimiento y marca "en_base" = "Sí".
Hoja "equipos": a quién se deriva cada tema (especialistas ficticios para el demo).

Credenciales (cuenta de servicio de Google):
  - local: GOOGLE_SERVICE_ACCOUNT_FILE (ruta al JSON) y GOOGLE_SHEET_ID en .env
  - Streamlit Cloud: [gcp_service_account] y GOOGLE_SHEET_ID en los secrets
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import gspread
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "ai"))
from catalogo import EQUIPOS, ESPECIALISTAS  # noqa: E402

COLUMNAS = ["id", "fecha", "canal", "iged", "consulta", "tema", "destino", "indicador", "estado",
            "confianza", "respuesta_ia", "citas", "respuesta_especialista", "fecha_respuesta", "en_base"]
ESTADOS = ["Respondida automáticamente", "Pendiente por validar", "Respondido"]


def _credenciales():
    load_dotenv(RAIZ / ".env")
    try:  # Streamlit Cloud
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            return dict(st.secrets["gcp_service_account"]), st.secrets.get("GOOGLE_SHEET_ID")
    except Exception:
        pass
    archivo = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    if not archivo:
        raise RuntimeError("Falta GOOGLE_SERVICE_ACCOUNT_FILE en .env (o gcp_service_account en los secrets).")
    ruta = Path(archivo) if Path(archivo).is_absolute() else RAIZ / archivo
    return json.loads(ruta.read_text(encoding="utf-8")), os.getenv("GOOGLE_SHEET_ID")


def libro() -> gspread.Spreadsheet:
    info, hoja_id = _credenciales()
    if not hoja_id:
        raise RuntimeError("Falta GOOGLE_SHEET_ID.")
    return gspread.service_account_from_dict(info).open_by_key(hoja_id)


def preparar() -> None:
    """Crea (si no existen) las pestañas 'consultas' y 'equipos' con sus encabezados."""
    lb = libro()
    nombres = [w.title for w in lb.worksheets()]
    if "consultas" not in nombres:
        ws = lb.add_worksheet("consultas", rows=500, cols=len(COLUMNAS))
        ws.append_row(COLUMNAS)
        ws.freeze(rows=1)
    if "equipos" not in nombres:
        ws = lb.add_worksheet("equipos", rows=30, cols=3)
        filas = [["destino", "nombre (ficticio)", "atiende"]]
        filas += [[e, f"Especialista {e}", "Indicadores " + ", ".join(i)] for e, i in ESPECIALISTAS.items()]
        filas += [[k, f"Equipo de {v.split(':')[0]}", v.split(":", 1)[1].strip()] for k, v in EQUIPOS.items()]
        ws.append_rows(filas)
        ws.freeze(rows=1)
    if "Hoja 1" in nombres or "Sheet1" in nombres:  # pestaña vacía que crea Google por defecto
        lb.del_worksheet(lb.worksheet("Hoja 1" if "Hoja 1" in nombres else "Sheet1"))


def registrar(r: dict, canal: str) -> int:
    """Agrega la consulta procesada como una fila nueva. Devuelve su id."""
    ws = libro().worksheet("consultas")
    nuevo_id = len(ws.col_values(1))  # la fila 1 es el encabezado
    citas = " | ".join(c["etiqueta"] for c in r["citas"])
    ws.append_row([nuevo_id, datetime.now().strftime("%Y-%m-%d %H:%M"), canal, r["iged"] or "", r["consulta"],
                   r["tema"], r["destino"], r["indicador"] or "", r["estado"], round(r["confianza"], 2),
                   r["respuesta"], citas, "", "", ""], value_input_option="USER_ENTERED")
    return nuevo_id


def consultas() -> list:
    """Todas las filas como diccionarios (para el panel)."""
    return libro().worksheet("consultas").get_all_records(expected_headers=COLUMNAS)


def incorporar_respondidas() -> list:
    """Devuelve las respuestas de especialistas aún no incorporadas y las marca como incorporadas."""
    ws = libro().worksheet("consultas")
    filas = ws.get_all_records(expected_headers=COLUMNAS)
    nuevas = []
    col_base = COLUMNAS.index("en_base") + 1
    col_fecha = COLUMNAS.index("fecha_respuesta") + 1
    for n, f in enumerate(filas, start=2):
        if f["estado"] == "Respondido" and str(f["respuesta_especialista"]).strip() and f["en_base"] != "Sí":
            nuevas.append(f)
            if not str(f["fecha_respuesta"]).strip():
                ws.update_cell(n, col_fecha, datetime.now().strftime("%Y-%m-%d %H:%M"))
            ws.update_cell(n, col_base, "Sí")
    return nuevas


def aprendidas() -> list:
    """Preguntas y respuestas validadas por el equipo que ya forman parte de la base."""
    return [f for f in consultas() if f["en_base"] == "Sí" and str(f["respuesta_especialista"]).strip()]


if __name__ == "__main__":
    preparar()
    print("Hoja lista:", [w.title for w in libro().worksheets()])
