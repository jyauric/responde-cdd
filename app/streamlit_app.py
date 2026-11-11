"""responde-cdd · App en Streamlit.

Correr en local:  streamlit run app/streamlit_app.py
"""
import os
import sys
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import pymupdf
import streamlit as st

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "ai"))
sys.path.insert(0, str(RAIZ / "backend"))

# En Streamlit Community Cloud la clave viene de st.secrets; en local, del archivo .env.
try:
    if "GEMINI_API_KEY" in st.secrets:
        os.environ.setdefault("GEMINI_API_KEY", st.secrets["GEMINI_API_KEY"])
except FileNotFoundError:
    pass

from catalogo import EQUIPOS, ESPECIALISTAS, INDICADORES  # noqa: E402
import clasificador  # noqa: E402
import sheets  # noqa: E402

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


@st.cache_data(ttl=60, show_spinner=False)
def respuestas_del_equipo() -> list:
    """Respuestas validadas por especialistas (hoja 'consultas'); vacío si Sheets no está configurado."""
    try:
        return sheets.aprendidas()
    except Exception:
        return []


# ---------------------------------------------------------------- Barra lateral: equipo de CdD
with st.sidebar:
    st.header("Equipo de CdD")
    st.write("Las consultas pendientes se registran en la hoja de Google Sheets del equipo. "
             "Cuando un especialista escribe su respuesta y marca **Respondido**, se incorpora a la base "
             "de conocimiento y la próxima consulta parecida se responde sola.")
    if st.button("Incorporar respuestas de especialistas", width="stretch"):
        try:
            nuevas = sheets.incorporar_respondidas()
            respuestas_del_equipo.clear()
            st.success(f"Incorporadas: {len(nuevas)}")
        except Exception as e:
            st.error(f"No se pudo leer la hoja: {e}")
    st.caption(f"Respuestas del equipo en la base: {len(respuestas_del_equipo())}")

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

tab_consulta, tab_panel = st.tabs(["Consultas", "Panel de la coordinadora"])

with tab_consulta:
  st.subheader("Nueva consulta")
  cols = st.columns(len(EJEMPLOS))
  for col, (titulo, texto) in zip(cols, EJEMPLOS.items()):
      if col.button(f"Ejemplo: {titulo}", width="stretch"):
          st.session_state.consulta = texto

  canal = st.radio("Canal", ["Correo", "WhatsApp"], horizontal=True)
  consulta = st.text_area("Pega aquí el texto de la consulta", key="consulta", height=110)

  if st.button("Procesar consulta", type="primary", disabled=not consulta.strip()):
      with st.spinner("Buscando en la norma y redactando la respuesta…"):
          try:
              r = clasificador.responder(consulta.strip(), aprendidas=respuestas_del_equipo())
          except Exception as e:  # p. ej. límite del plan gratuito de Gemini
              st.error(f"No se pudo procesar la consulta: {e}")
              st.stop()
      r["canal"], r["fecha"] = canal, datetime.now().strftime("%d/%m/%Y %H:%M")
      try:
          r["registro"] = sheets.registrar(r, canal)
      except Exception as e:
          r["registro"] = None
          st.caption(f"⚠️ No se registró en Google Sheets: {e}")
      st.session_state.historial.insert(0, r)

  if st.session_state.historial:
      r = st.session_state.historial[0]
      st.divider()
      auto = r["estado"] == "Respondida automáticamente"
      if auto:
          st.success(f"**{r['estado']}** · Tema: {nombre_destino(r['destino'])}")
      else:
          st.warning(f"**{r['estado']}** · Derivar a: {nombre_destino(r['destino'])}")

      if r.get("registro"):
          st.caption(f"Registrada en la hoja del equipo como consulta N° {r['registro']}.")
      if r.get("uso_respuesta_equipo"):
          st.info("🧠 Esta respuesta usa una respuesta ya validada por un especialista del equipo.")

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
              st.markdown(f"- {c['etiqueta']}" + (f" · [abrir fuente oficial]({enlace})" if enlace else ""))
              if es_pdf:
                  paginas = list(range(c["pagina"], c.get("pagina_fin", c["pagina"]) + 1))[:3]
                  with st.expander("Ver página citada" if len(paginas) == 1 else f"Ver las {len(paginas)} páginas citadas"):
                      for pag in paginas:
                          st.image(imagen_pagina(c["archivo"], pag), width="stretch")



# ---------------------------------------------------------------- Panel de la coordinadora
AZUL = "#2a78d6"  # una sola serie por gráfico: un solo color


@st.cache_data(ttl=60, show_spinner=False)
def datos_panel() -> pd.DataFrame:
    return pd.DataFrame(sheets.consultas())


def barras(df: pd.DataFrame, campo: str, titulo: str, eje: str):
    conteo = df[campo].replace("", "Sin dato").value_counts().reset_index()
    conteo.columns = [eje, "Consultas"]
    alto = max(120, 28 * len(conteo))
    grafico = (
        alt.Chart(conteo, title=titulo, height=alto)
        .mark_bar(color=AZUL, cornerRadiusEnd=4, size=16)
        .encode(
            x=alt.X("Consultas:Q", axis=alt.Axis(tickMinStep=1, grid=True, gridOpacity=0.25, title=None)),
            y=alt.Y(f"{eje}:N", sort="-x", axis=alt.Axis(title=None, labelLimit=320)),
            tooltip=[alt.Tooltip(f"{eje}:N"), alt.Tooltip("Consultas:Q")],
        )
    )
    etiquetas = grafico.mark_text(align="left", dx=4, color="#52514e").encode(text="Consultas:Q")
    st.altair_chart(grafico + etiquetas, width="stretch")


with tab_panel:
    st.subheader("Panel de la coordinadora")
    st.caption("Datos de la hoja del equipo (consultas de ejemplo). Sirve para ver la carga del equipo, de dónde "
               "consultan y qué temas de la norma generan más dudas, insumo para la norma del próximo año.")
    if st.button("Actualizar datos"):
        datos_panel.clear()
    try:
        df = datos_panel()
    except Exception as e:
        st.warning(f"No se pudo leer la hoja del equipo: {e}")
        st.stop()
    if df.empty:
        st.info("Todavía no hay consultas registradas.")
        st.stop()

    df["destino_nombre"] = df["destino"].map(lambda d: nombre_destino(d) if d else "")
    df["indicador_nombre"] = df["indicador"].astype(str).map(
        lambda i: f"{i} · {INDICADORES[i][:60]}…" if i in INDICADORES else "Sin indicador (tema transversal)")
    auto = (df["estado"] == "Respondida automáticamente").sum()
    pendientes = (df["estado"] == "Pendiente por validar").sum()
    respondidas = df[df["estado"] == "Respondido"].copy()
    en_base = (df["en_base"] == "Sí").sum()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Consultas", len(df))
    k2.metric("Resueltas al instante", f"{auto / len(df):.0%}", help=f"{auto} de {len(df)}")
    k3.metric("Pendientes por validar", int(pendientes))
    k4.metric("Respuestas del equipo en la base", int(en_base))

    if not respondidas.empty:
        horas = (pd.to_datetime(respondidas["fecha_respuesta"]) - pd.to_datetime(respondidas["fecha"])
                 ).dt.total_seconds() / 3600
        st.caption(f"Tiempo mediano de respuesta del equipo en consultas derivadas: {horas.median():.1f} horas "
                   f"({len(respondidas)} respondidas).")

    c1, c2 = st.columns(2)
    with c1:
        barras(df[df["estado"] == "Pendiente por validar"], "destino_nombre",
               "Carga pendiente por especialista o equipo", "Destino")
        barras(df, "region", "Consultas por región", "Región")
    with c2:
        barras(df, "indicador_nombre", "Indicadores que más consultas generan", "Indicador")
        barras(df, "canal", "Consultas por canal", "Canal")

    with st.expander("Ver tabla de consultas"):
        st.dataframe(df[["id", "fecha", "canal", "iged", "region", "tema", "destino", "indicador", "estado",
                         "en_base"]], width="stretch", hide_index=True)
