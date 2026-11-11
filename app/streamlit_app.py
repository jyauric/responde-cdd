"""responde-cdd · App en Streamlit.

Correr en local:  streamlit run app/streamlit_app.py
"""
import os
import sys
from datetime import datetime
from pathlib import Path

import pymupdf
import streamlit as st

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "ai"))

# En Streamlit Community Cloud la clave viene de st.secrets; en local, del archivo .env.
try:
    if "GEMINI_API_KEY" in st.secrets:
        os.environ.setdefault("GEMINI_API_KEY", st.secrets["GEMINI_API_KEY"])
except FileNotFoundError:
    pass

from catalogo import EQUIPOS, ESPECIALISTAS  # noqa: E402
import clasificador  # noqa: E402

st.set_page_config(page_title="responde-cdd", page_icon="📘", layout="wide")

EJEMPLOS = {
    "PUR consolidado": "Buenos días, les escribimos de la UGEL Bagua. ¿Hasta qué fecha la DRE debe enviar el PUR "
                       "consolidado y por qué medio?",
    "Ampliación de plazo": "Buenas tardes, desde la UGEL Espinar: ¿pueden ampliarnos el plazo para registrar las "
                           "plazas del indicador 1.1 porque tuvimos problemas con el sistema?",
    "Resultado de una IGED": "Desde la DRE Cusco queremos saber dónde vemos nuestro resultado preliminar del "
                             "indicador 3.2 en el Tramo 2.",
}


def nombre_destino(codigo: str) -> str:
    if codigo in ESPECIALISTAS:
        return f"Especialista {codigo} (indicadores {', '.join(ESPECIALISTAS[codigo])})"
    return "Equipo de " + EQUIPOS[codigo].split(":")[0]


@st.cache_data(show_spinner=False)
def imagen_pagina(archivo: str, pagina: int) -> bytes:
    with pymupdf.open(RAIZ / "data" / "normas" / archivo) as doc:
        return doc[pagina - 1].get_pixmap(dpi=110).tobytes("png")


# ---------------------------------------------------------------- Interfaz
st.title("📘 responde-cdd")
st.markdown(
    "Respondemos al instante las consultas de las UGEL y DRE/GRE sobre **Compromisos de Desempeño**, "
    "mediante IA que busca en la norma y en las publicaciones web de la herramienta, cita la fuente "
    "y deriva al especialista solo lo que no está cubierto."
)
st.caption("Proyecto personal (Diplomatura Q-Lab PUCP). No es un producto oficial de ninguna institución. "
           "Usa solo documentos públicos; las consultas son de ejemplo y los remitentes, ilustrativos.")

if "historial" not in st.session_state:
    st.session_state.historial = []

st.subheader("Nueva consulta")
cols = st.columns(len(EJEMPLOS))
for col, (titulo, texto) in zip(cols, EJEMPLOS.items()):
    if col.button(f"Ejemplo: {titulo}", use_container_width=True):
        st.session_state.consulta = texto

canal = st.radio("Canal", ["Correo", "WhatsApp"], horizontal=True)
consulta = st.text_area("Pega aquí el texto de la consulta", key="consulta", height=110)

if st.button("Procesar consulta", type="primary", disabled=not consulta.strip()):
    with st.spinner("Buscando en la norma y redactando la respuesta…"):
        try:
            r = clasificador.responder(consulta.strip())
        except Exception as e:  # p. ej. límite del plan gratuito de Gemini
            st.error(f"No se pudo procesar la consulta: {e}")
            st.stop()
    r["canal"], r["fecha"] = canal, datetime.now().strftime("%d/%m/%Y %H:%M")
    st.session_state.historial.insert(0, r)

if st.session_state.historial:
    r = st.session_state.historial[0]
    st.divider()
    auto = r["estado"] == "Respondida automáticamente"
    (st.success if auto else st.warning)(f"**{r['estado']}** · Derivar a: {nombre_destino(r['destino'])}")

    c1, c2, c3 = st.columns(3)
    c1.metric("IGED", r["iged"] or "No indicada")
    c2.metric("Indicador", r["indicador"] or "—")
    c3.metric("Confianza del modelo", f"{r['confianza']:.0%}")

    st.markdown("**Respuesta**" if auto else "**Borrador para el especialista**")
    st.write(r["respuesta"])
    if r["falta"]:
        st.info(f"**Lo que no está en los documentos:** {r['falta']}")

    if r["citas"]:
        st.markdown("**Fuentes citadas**")
        for i, c in enumerate(r["citas"]):
            es_pdf = c["archivo"].endswith(".pdf")
            enlace = f"{c['url']}#page={c['pagina']}" if es_pdf else c["url"]
            st.markdown(f"- {c['etiqueta']} · [abrir fuente oficial]({enlace})")
            if es_pdf:
                paginas = list(range(c["pagina"], c.get("pagina_fin", c["pagina"]) + 1))[:3]
                with st.expander("Ver página citada" if len(paginas) == 1 else f"Ver las {len(paginas)} páginas citadas"):
                    for pag in paginas:
                        st.image(imagen_pagina(c["archivo"], pag), use_container_width=True)

