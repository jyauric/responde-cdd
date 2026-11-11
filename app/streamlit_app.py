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
st.markdown("""
<style>
  .block-container {padding-top: 2.2rem; max-width: 1200px;}
  h1 {color: #387870; letter-spacing: -0.5px;}
  [data-testid="stMetric"] {background: #ffffff;}
  [data-testid="stMetricValue"] {color: #2b5f59;}
</style>
""", unsafe_allow_html=True)
st.title("responde-cdd")
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
      c1.metric("IGED", r["iged"] or "No indicada", border=True)
      c2.metric("Indicador", r["indicador"] or "—", border=True)
      c3.metric("Confianza del modelo", f"{r['confianza']:.0%}", border=True)

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
VERDE = "#387870"  # color de la marca; una sola serie por gráfico: un solo color
TINTA = "#4a5755"  # etiquetas de valores en color de texto, no de la serie
CORTO = {"IMPLEMENTACION": "Implementación", "DATOS": "Datos", "PRESUPUESTO": "Presupuesto",
         "COMUNICACIONES": "Comunicaciones"}


@st.cache_data(ttl=60, show_spinner=False)
def datos_panel() -> pd.DataFrame:
    return pd.DataFrame(sheets.consultas())


def barras(df: pd.DataFrame, campo: str, detalle: str, titulo: str):
    """Barras horizontales de una sola serie: etiqueta corta en el eje y nombre completo en el tooltip."""
    if df.empty:
        st.caption(f"{titulo}: sin datos con los filtros elegidos.")
        return
    conteo = (df.assign(_c=df[campo].replace("", "Sin dato"), _d=df[detalle].replace("", "Sin dato"))
              .groupby(["_c", "_d"]).size().reset_index(name="Consultas"))
    maximo = int(conteo["Consultas"].max())
    base = alt.Chart(conteo, height=40 + 48 * len(conteo)).encode(
        y=alt.Y("_c:N", sort="-x", title=None, scale=alt.Scale(paddingInner=0.45, paddingOuter=0.3),
                axis=alt.Axis(labelLimit=200, ticks=False, domain=False, labelFontSize=13, labelColor=TINTA)),
        x=alt.X("Consultas:Q", title=None, scale=alt.Scale(domain=[0, maximo * 1.25 + 0.5]),
                axis=None),  # sin números en el eje: cada barra ya muestra su valor
        tooltip=[alt.Tooltip("_d:N", title="Detalle"), alt.Tooltip("Consultas:Q")],
    )
    barra = base.mark_bar(color=VERDE, cornerRadiusEnd=4)
    valor = base.mark_text(align="left", dx=6, color=TINTA, fontSize=13, fontWeight="bold").encode(text="Consultas:Q")
    with st.container(border=True):
        st.markdown(f"**{titulo}**")
        st.altair_chart((barra + valor).configure_view(strokeWidth=0), width="stretch")


def _marcar(clave: str, opciones: list, valor: bool) -> None:
    for o in opciones:
        st.session_state[f"{clave}::{o}"] = valor


def _borrar_filtros() -> None:
    for k in list(st.session_state):
        if k.startswith("f_"):
            if "::" in k:
                st.session_state[k] = False
            else:
                del st.session_state[k]


def filtro(columna, etiqueta: str, opciones: list, clave: str) -> list:
    """Filtro desplegable con lista vertical de casillas, 'Todos' y 'Limpiar'. Sin selección = todas."""
    opciones = [o for o in opciones if o]
    elegidas = [o for o in opciones if st.session_state.get(f"{clave}::{o}")]
    titulo = f"{etiqueta} ({len(elegidas)})" if elegidas else etiqueta
    with columna.popover(titulo, width="stretch"):
        # Dos botones pequeños con símbolo (texto completo al pasar el mouse): "todos" a la izquierda y "limpiar"
        # a la derecha, pegados a la lista de casillas.
        b1, _, b2 = st.columns([1, 3, 1], gap="small", vertical_alignment="center")
        b1.button("", key=f"{clave}_todos", icon=":material/done_all:", help="Seleccionar todos",
                  on_click=_marcar, args=(clave, opciones, True))
        b2.button("", key=f"{clave}_limpiar", icon=":material/close:", help="Limpiar",
                  on_click=_marcar, args=(clave, opciones, False))
        for o in opciones:
            st.checkbox(str(o), key=f"{clave}::{o}")
    return [o for o in opciones if st.session_state.get(f"{clave}::{o}")]


with tab_panel:
    st.subheader("Panel de la coordinadora")
    st.caption("Datos de la hoja del equipo (consultas de ejemplo). Muestra la carga del equipo, de dónde consultan "
               "y qué indicadores generan más dudas, insumo para la norma del próximo año. "
               "Sin selección en un filtro se muestran todos.")
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

    df["fecha_dt"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["destino_corto"] = df["destino"].map(lambda d: CORTO.get(d, d))
    df["destino_nombre"] = df["destino"].map(lambda d: nombre_destino(d) if d else "")
    df["indicador"] = df["indicador"].astype(str).replace("nan", "")
    df["indicador_nombre"] = df["indicador"].map(lambda i: f"{i} · {INDICADORES[i]}" if i in INDICADORES else "")
    df["indicador_corto"] = df["indicador"].where(df["indicador"].isin(INDICADORES.keys()), "Transversal")

    # ---- Filtros (desplegables en una fila)
    dias = df["fecha_dt"].dropna().dt.date
    desde, hasta = dias.min(), dias.max()
    cols = st.columns([1, 1.4, 1, 1, 1, 1, 1.1])
    with cols[0].popover("Fechas", width="stretch"):
        rango = st.date_input("Rango de fechas", value=(desde, hasta), min_value=desde, max_value=hasta,
                              format="DD/MM/YYYY", key="f_fechas")
    cols[6].button("Borrar filtros", on_click=_borrar_filtros, width="stretch", type="secondary")
    orden_destino = list(ESPECIALISTAS) + list(CORTO.values())
    sel_dest = filtro(cols[1], "Especialista / equipo",
                      [d for d in orden_destino if d in set(df["destino_corto"])], "f_dest")
    ind_presentes = sorted((i for i in set(df["indicador"]) if i in INDICADORES),
                           key=lambda x: [int(n) for n in x.split(".")])
    sel_ind = filtro(cols[2], "Indicador", ind_presentes, "f_ind")
    sel_reg = filtro(cols[3], "Región", sorted(set(df["region"])), "f_reg")
    igeds = df[df["region"].isin(sel_reg)] if sel_reg else df
    sel_iged = filtro(cols[4], "IGED", sorted(set(igeds["iged"])), "f_iged")
    sel_canal = filtro(cols[5], "Canal", sorted(set(df["canal"])), "f_canal")

    solo_pendientes = st.checkbox("Ver solo consultas pendientes por validar", key="f_solo_pendientes")

    f = df.copy()
    if solo_pendientes:
        f = f[f["estado"] == "Pendiente por validar"]
    if isinstance(rango, tuple) and len(rango) == 2:
        f = f[(f["fecha_dt"].dt.date >= rango[0]) & (f["fecha_dt"].dt.date <= rango[1])]
    for col, sel in [("destino_corto", sel_dest), ("indicador", sel_ind), ("region", sel_reg),
                     ("iged", sel_iged), ("canal", sel_canal)]:
        if sel:
            f = f[f[col].isin(sel)]

    # ---- Indicadores principales
    total = len(f)
    auto = int((f["estado"] == "Respondida automáticamente").sum())
    pendientes = int((f["estado"] == "Pendiente por validar").sum())
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Consultas", total, border=True)
    k2.metric("Resueltas al instante", f"{auto / total:.0%}" if total else "—", help=f"{auto} de {total}",
              border=True)
    k3.metric("Pendientes por validar", pendientes, border=True)
    k4.metric("Respuestas del equipo en la base", int((f["en_base"] == "Sí").sum()), border=True)
    respondidas = f[f["estado"] == "Respondido"]
    if not respondidas.empty:
        horas = (pd.to_datetime(respondidas["fecha_respuesta"], errors="coerce") - respondidas["fecha_dt"]
                 ).dt.total_seconds() / 3600
        st.caption(f"Tiempo mediano de respuesta del equipo en consultas derivadas: {horas.median():.1f} horas "
                   f"({len(respondidas)} respondidas).")

    c1, c2 = st.columns(2)
    with c1:
        barras(f[f["estado"] == "Pendiente por validar"], "destino_corto", "destino_nombre",
               "Carga pendiente por especialista o equipo")
        barras(f, "region", "region", "Consultas por región")
    with c2:
        barras(f, "indicador_corto", "indicador_nombre", "Indicadores que más consultas generan")
        barras(f, "canal", "canal", "Consultas por canal")

    with st.expander("Ver tabla de consultas"):
        st.dataframe(f[["id", "fecha", "canal", "iged", "region", "tema", "destino_corto", "indicador", "estado",
                        "en_base"]], width="stretch", hide_index=True)
