"""España: IPC vs. salarios (panel Streamlit)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from etl.build import build
from etl.config import (
    BASE_YEAR,
    CPI_MONTHLY_CSV,
    CPI_YEARLY_CSV,
    SALARIES_CSV,
    SALARY_CATALOG_JSON,
    IRPF_CSV,
    SERIES_META_CSV,
)
from etl.irpf import PAGE_URL as IRPF_PAGE_URL, personal_allowance
from etl.working_hours import NEW_WEEKLY_HOURS, OLD_WEEKLY_HOURS, REDUCTION_YEAR, apply_hours_penalty, hours_factor
from etl.metrics import compare, rebase_cpi, summarize
from etl.salaries import load_catalog

# Reference categorical palette (fixed order, colour follows the series, never its rank).
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'
MAX_SERIES = 8

CATEGORY_LABELS = {
    "academic": "Académico",
    "minimum_wage": "Salario mínimo",
    "politician": "Políticos",
    "low_wage": "Empleos de bajos salarios",
    "general": "General",
}
BASIS_LABELS = {"gross": "Bruto", "net": "Neto"}
UNIT_LABELS = {"eur_monthly": "EUR/mes", "eur_annual": "EUR/año"}

st.set_page_config(page_title="España: IPC vs. salarios", page_icon=None, layout="wide")


@st.cache_data(show_spinner="Cargando datos...")
def load_data(_stamp: float):
    return (
        pd.read_csv(CPI_YEARLY_CSV),
        pd.read_csv(SALARIES_CSV),
        pd.read_csv(SERIES_META_CSV).fillna(""),
    )


def data_stamp() -> float:
    files = [CPI_MONTHLY_CSV, CPI_YEARLY_CSV, SALARIES_CSV, SERIES_META_CSV, SALARY_CATALOG_JSON, IRPF_CSV]
    return max((p.stat().st_mtime for p in files if p.exists()), default=0.0)


def es(value: float, fmt: str) -> str:
    """Format a number Spanish-style (1.234,5) from an English format spec such as '+.1f' or ',.0f'."""
    return format(value, fmt).replace(",", "\0").replace(".", ",").replace("\0", ".")


if not all(p.exists() for p in [CPI_MONTHLY_CSV, CPI_YEARLY_CSV, SALARIES_CSV, SERIES_META_CSV]):
    with st.spinner("Primer arranque: descargando datos del IPC del INE..."):
        build()

cpi_y, salaries, meta = load_data(data_stamp())
if "provisional" not in cpi_y:
    cpi_y["provisional"] = False
prov_years = set(cpi_y.loc[cpi_y["provisional"], "year"].astype(int))
meta = meta.sort_values("order").set_index("series_id", drop=False)
label_of = {sid: r["label_es"] or r["label"] for sid, r in meta.iterrows()}
first_year, last_year = int(cpi_y["year"].min()), int(cpi_y["year"].max())
last_final_year = int(cpi_y.loc[~cpi_y["provisional"], "year"].max())
PROV_INFLATION = cpi_y.loc[cpi_y["provisional"], ["year", "inflation_dec_pct"]].set_index("year")["inflation_dec_pct"]


def ylabel(year) -> str:
    return f"{int(year)} (prov.)" if int(year) in prov_years else str(int(year))


def color_of(sid: str) -> tuple[str, str]:
    order = int(meta.loc[sid, "order"])
    return (SERIES_COLORS[order], "solid") if order < len(SERIES_COLORS) else (MUTED, "dash")


def style(fig: go.Figure, y_title: str, y_fmt: str = ",.0f", y0: int = first_year, y1: int = last_year):
    fig.update_layout(
        template="none",
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family=FONT, color=INK2, size=13),
        separators=",.",
        hovermode="x unified",
        height=460,
        margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", yanchor="top", y=-0.12, x=0),
        bargap=0.25,
    )
    fig.update_xaxes(
        showgrid=False,
        linecolor=AXIS,
        tickformat="d",
        dtick=1 if y1 - y0 <= 20 else 2,
        tickfont=dict(color=MUTED),
    )
    fig.update_yaxes(
        title=y_title,
        gridcolor=GRID,
        zeroline=False,
        tickformat=y_fmt,
        tickfont=dict(color=MUTED),
    )
    return fig


def add_line(fig, x, y, name, color, dash="solid", interpolated=None, width=2, fmt=",.1f", group=None):
    interpolated = interpolated if interpolated is not None else [False] * len(x)
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            name=name,
            legendgroup=group,
            mode="lines+markers",
            line=dict(color=color, width=width, dash=dash),
            marker=dict(
                size=8,
                color=[SURFACE if i else color for i in interpolated],
                line=dict(color=[color if i else SURFACE for i in interpolated], width=2),
            ),
            hovertemplate=f"%{{y:{fmt}}}",
            connectgaps=False,
        )
    )


def add_cpi_line(fig, x, y, name):
    fig.add_trace(
        go.Scatter(
            x=x, y=y, name=name, mode="lines", line=dict(color=INK, width=3.5), hovertemplate="%{y:,.1f}"
        )
    )
    x, y = pd.Series(list(x)), pd.Series(list(y))
    prov = x.isin(prov_years)
    if prov.any():
        fig.add_trace(
            go.Scatter(
                x=x[prov],
                y=y[prov],
                name="IPC provisional",
                mode="markers",
                marker=dict(symbol="diamond-open", size=11, color=INK, line=dict(width=2)),
                hovertemplate="%{y:,.1f} (provisional)",
            )
        )


def bar_pattern(years) -> dict:
    """Hatched fill for bars of provisional years."""
    return dict(shape=["/" if int(y) in prov_years else "" for y in years])


def wide_table(cmp: pd.DataFrame, col: str, ids: list[str], y0: int, y1: int) -> pd.DataFrame:
    sub = cmp[(cmp["year"] >= y0) & (cmp["year"] <= y1)]
    w = sub.pivot(index="year", columns="series_id", values=col)[ids].rename(columns=label_of)
    w.index = w.index.map(ylabel)
    w.index.name = "Año"
    return w


def show_table(df: pd.DataFrame, fmt: str, key: str):
    st.dataframe(df.style.format(fmt, na_rep="n/d", decimal=",", thousands="."), use_container_width=True)
    st.download_button(
        "Descargar CSV",
        df.to_csv().encode("utf-8"),
        file_name="ipc_vs_salarios.csv",
        mime="text/csv",
        key=f"dl-{key}",
    )


# ------------------------------------------------------------------ sidebar
st.sidebar.header("Controles")

net_years = sorted(salaries.loc[salaries["net_annual_eur"].notna(), "year"].unique())
allowance_txt = (
    f"{es(personal_allowance(2014), ',.0f')} EUR hasta 2014 y {es(personal_allowance(2015), ',.0f')} EUR desde 2015"
)
apply_irpf = st.sidebar.checkbox(
    "Aplicar IRPF (salario neto)",
    value=False,
    help=f"Descuenta el IRPF de la Comunidad Valenciana ({net_years[0]}-{net_years[-1]}): tipo total (estatal + autonómico) "
    f"progresivo por tramos, con un mínimo exento de {allowance_txt}. No incluye cotizaciones a la "
    "Seguridad Social.",
)
if apply_irpf:
    salaries = salaries.assign(annual_eur=salaries["net_annual_eur"])
    first_year, last_year = max(first_year, int(net_years[0])), min(last_year, int(net_years[-1]))

apply_hours = st.sidebar.checkbox(
    "Penalizar profesorado por la reducción de jornada (2026)",
    value=False,
    help=f"Esta medida se introdujo en {REDUCTION_YEAR}: el resto de puestos pasó de {es(OLD_WEEKLY_HOURS, ',.1f')} a "
    f"{es(NEW_WEEKLY_HOURS, ',.1f')} horas semanales con el mismo sueldo, mientras que el profesorado sigue en "
    f"{es(OLD_WEEKLY_HOURS, ',.1f')}. Desde {REDUCTION_YEAR} se multiplica el salario nominal del profesorado por "
    f"{es(NEW_WEEKLY_HOURS, ',.1f')}/{es(OLD_WEEKLY_HOURS, ',.1f')} = {es(hours_factor(), ',.4f')} "
    "(sueldo por hora trabajada relativo al del resto de puestos) y de ahí se derivan el índice y el poder adquisitivo "
    "frente al IPC.",
)
if apply_hours:
    salaries = apply_hours_penalty(salaries, meta)

y0, y1 = st.sidebar.slider("Rango de años", first_year, last_year, (first_year, last_year))
base_years = list(range(first_year, last_year + 1))
base_year = st.sidebar.selectbox(
    "Año base (= 100)",
    base_years,
    index=base_years.index(BASE_YEAR) if BASE_YEAR in base_years else 0,
    help="Los salarios y el IPC se reescalan para que este año valga 100. Por defecto: 2008 "
    "(con IRPF, el primer año con datos de IRPF).",
)

options = list(meta.index)
default_ids = [i for i in options if meta.loc[i, "category"] in ("academic",)][:1] + [
    i for i in options if meta.loc[i, "category"] == "minimum_wage"
][:1]


def option_label(sid: str) -> str:
    return f"{label_of[sid]}  [{CATEGORY_LABELS.get(meta.loc[sid, 'category'], meta.loc[sid, 'category'])}]"


chosen = st.sidebar.multiselect(
    "Salarios a comparar",
    options,
    default=default_ids,
    format_func=option_label,
    max_selections=MAX_SERIES,
    help="Todas las series tienen un histórico documentado desde 2008. Consulta la pestaña Fuentes y método.",
)
ids = [i for i in options if i in chosen]

amount_basis = st.sidebar.radio("Importes mostrados como", ["Anual (EUR/año)", "Media mensual (EUR/mes)"])
divisor = 12 if amount_basis.startswith("Media") else 1
unit_txt = ("EUR/mes" if divisor == 12 else "EUR/año") + (" netos" if apply_irpf else "")

interpolate = st.sidebar.checkbox(
    "Rellenar huecos por interpolación lineal",
    value=False,
    help="Estima los años sin dato entre dos valores conocidos. Los puntos rellenados se dibujan con marcadores huecos.",
)
show_adjusted = st.sidebar.checkbox(
    "Mostrar trayectoria ajustada al IPC (vista nominal)",
    value=False,
    help="Línea punteada: lo que valdría el salario del año base si hubiera seguido al IPC.",
)

# ------------------------------------------------------------------ header
st.title("España: precios de consumo vs. salarios")
st.caption(
    f"IPC: INE, diciembre de cada año, diciembre de {base_year} = 100. Salarios: "
    f"{'netos de IRPF (Comunidad Valenciana)' if apply_irpf else 'brutos'}, de las fuentes indicadas en la pestaña "
    f"Fuentes y método. Último año completo con datos de IPC: {last_final_year}."
)
if any(y0 <= y <= y1 for y in prov_years):
    st.warning(
        "**IPC provisional:** el IPC de diciembre de "
        + ", ".join(f"{y} se ha fijado provisionalmente en {es(p, '+.1f')}% (dic./dic.)" for y, p in PROV_INFLATION.items())
        + " hasta que el INE publique el dato real. Los valores de esos años aparecen marcados como «prov.» "
        "(marcador hueco en las líneas, barras rayadas) y las variaciones que los incluyen son provisionales."
    )
if apply_irpf:
    st.info(
        "Salario neto = bruto menos IRPF (tipo total estatal + autonómico de la Comunidad Valenciana, progresivo por "
        f"tramos, con un mínimo exento de {allowance_txt}). **No incluye las cotizaciones a la "
        f"Seguridad Social.** El SMI está exento de IRPF, por lo que su importe neto coincide con el bruto. "
        f"Disponible solo para {first_year}-{last_year}."
    )

if apply_hours:
    st.info(
        f"**Penalización por jornada:** la reducción de {es(OLD_WEEKLY_HOURS, ',.1f')} a {es(NEW_WEEKLY_HOURS, ',.1f')} "
        f"horas semanales se introdujo en {REDUCTION_YEAR} y no afecta al profesorado. Desde {REDUCTION_YEAR} su salario "
        f"nominal se multiplica por {es(hours_factor(), ',.4f')} ({es((hours_factor() - 1) * 100, '+.1f')}%). "
        "Es un ajuste hipotético sobre el importe mostrado (bruto o neto); el resto de series no cambia."
    )

if not ids:
    st.info("Selecciona al menos una serie salarial en la barra lateral.")
    st.stop()

cmp = compare(salaries, cpi_y, ids, base_year, interpolate)
cmp["amount"] = cmp["annual_eur"] / divisor
cmp["real_amount"] = cmp["real_annual_eur"] / divisor
cmp["inflation_pct"] = cmp["inflation_dec_pct"]
plot = cmp[(cmp["year"] >= y0) & (cmp["year"] <= y1)]
cpi_plot = plot.drop_duplicates("year").sort_values("year")

no_base = [label_of[s] for s in ids if cmp.loc[cmp["series_id"] == s, "salary_index"].isna().all()]
if no_base:
    st.warning(
        f"No hay valor para el año base {base_year} en: {', '.join(no_base)}. "
        "No se pueden calcular las vistas de índice ni de términos reales para estas series; elige otro año base."
    )

summary = summarize(cmp, cpi_y, y0, y1).set_index("series_id")

# ------------------------------------------------------------------ headline numbers
if not summary.empty:
    cols = st.columns(min(len(summary), 4) + 1)
    s0 = summary.iloc[0]
    cols[0].metric(f"IPC {int(s0.from_year)}-{int(s0.to_year)}", f"{es(s0.cpi_pct, '+.1f')}%")
    for col, (sid, r) in zip(cols[1:], list(summary.iterrows())[:4]):
        col.metric(
            label_of[sid],
            f"{es(r.nominal_pct, '+.1f')}% nominal",
            f"{es(r.real_pct, '+.1f')}% real ({int(r.from_year)}-{int(r.to_year)})",
            help="Variación nominal del salario y variación del poder adquisitivo tras descontar el IPC.",
        )

tab_evo, tab_real, tab_year, tab_cpi, tab_src = st.tabs(
    ["Evolución", "Poder adquisitivo", "Año a año", "IPC (INE)", "Fuentes y método"]
)

# ------------------------------------------------------------------ evolution
with tab_evo:
    view = st.radio(
        "Vista",
        ["Índice (año base = 100)", f"Nominal ({unit_txt})"],
        horizontal=True,
        label_visibility="collapsed",
    )
    is_index = view.startswith("Índice")
    fig = go.Figure()
    if is_index:
        add_cpi_line(fig, cpi_plot["year"], cpi_plot["cpi"], f"IPC (INE, dic. {base_year}=100)")
        for sid in ids:
            d = plot[plot["series_id"] == sid]
            c, dash = color_of(sid)
            add_line(fig, d["year"], d["salary_index"], label_of[sid], c, dash, d["interpolated"])
        style(fig, f"Índice ({base_year} = 100)", ",.0f", y0, y1)
    else:
        for sid in ids:
            d = plot[plot["series_id"] == sid]
            c, dash = color_of(sid)
            add_line(fig, d["year"], d["amount"], label_of[sid], c, dash, d["interpolated"], fmt=",.0f", group=sid)
            if show_adjusted:
                base_amount = cmp.loc[(cmp["series_id"] == sid) & (cmp["year"] == base_year), "amount"].iloc[0]
                fig.add_trace(
                    go.Scatter(
                        x=d["year"],
                        y=base_amount * d["cpi"] / 100,
                        name=f"{label_of[sid]} si hubiera seguido al IPC",
                        legendgroup=sid,
                        mode="lines",
                        line=dict(color=c, width=2, dash="dot"),
                        hovertemplate="%{y:,.0f}",
                    )
                )
        style(fig, unit_txt, ",.0f", y0, y1)
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Donde la línea de color queda por encima de la línea negra del IPC, el salario creció más que los precios "
        "desde el año base; por debajo, se perdió poder adquisitivo. Los marcadores huecos son valores interpolados."
    )
    with st.expander("Tabla de datos"):
        if is_index:
            t = wide_table(cmp, "salary_index", ids, y0, y1)
            t.insert(0, f"IPC (dic. {base_year}=100)", cpi_plot.set_index(cpi_plot["year"].map(ylabel))["cpi"])
            show_table(t, "{:,.1f}", "evo-index")
        else:
            show_table(wide_table(cmp, "amount", ids, y0, y1), "{:,.0f}", "evo-nominal")

# ------------------------------------------------------------------ purchasing power
with tab_real:
    st.markdown(
        f"Salarios deflactados por el IPC y expresados en **euros de {base_year}** ({unit_txt}). "
        "Una línea plana significa que el salario siguió el ritmo de los precios; una línea descendente, "
        "pérdida de poder adquisitivo."
    )
    fig = go.Figure()
    for sid in ids:
        d = plot[plot["series_id"] == sid]
        c, dash = color_of(sid)
        add_line(fig, d["year"], d["real_amount"], label_of[sid], c, dash, d["interpolated"], fmt=",.0f")
    style(fig, f"Euros de {base_year} ({unit_txt})", ",.0f", y0, y1)
    st.plotly_chart(fig, use_container_width=True)

    if not summary.empty:
        st.subheader(f"Variación en el periodo seleccionado ({y0}-{y1})")
        tbl = summary.assign(Serie=[label_of[s] for s in summary.index])
        tbl = tbl.set_index("Serie")[
            ["from_year", "to_year", "first_annual_eur", "last_annual_eur", "nominal_pct", "cpi_pct", "real_pct"]
        ]
        yr_txt = "EUR/año netos" if apply_irpf else "EUR/año"
        tbl.columns = [
            "Desde",
            "Hasta",
            f"Inicio ({yr_txt})",
            f"Fin ({yr_txt})",
            "Variación nominal %",
            "Variación IPC %",
            "Variación real %",
        ]
        st.dataframe(
            tbl.style.format(
                {
                    "Desde": "{:d}",
                    "Hasta": "{:d}",
                    f"Inicio ({yr_txt})": "{:,.0f}",
                    f"Fin ({yr_txt})": "{:,.0f}",
                    "Variación nominal %": "{:+.1f}",
                    "Variación IPC %": "{:+.1f}",
                    "Variación real %": "{:+.1f}",
                },
                decimal=",",
                thousands=".",
            ),
            use_container_width=True,
        )
        st.caption("Cada serie se mide entre su primer y su último año con datos dentro del rango seleccionado.")
    with st.expander("Tabla de datos"):
        show_table(wide_table(cmp, "real_amount", ids, y0, y1), "{:,.0f}", "real")

# ------------------------------------------------------------------ year by year
with tab_year:
    focus = st.selectbox("Serie", ids, format_func=lambda s: label_of[s])
    d = plot[plot["series_id"] == focus]
    c, _ = color_of(focus)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=d["year"],
            y=d["inflation_pct"],
            name="Inflación del IPC (dic./dic.)",
            marker=dict(color=INK2, line=dict(color=SURFACE, width=2), pattern=bar_pattern(d["year"])),
            hovertemplate="%{y:+.1f}%",
        )
    )
    fig.add_trace(
        go.Bar(
            x=d["year"],
            y=d["yoy_pct"],
            name=f"{label_of[focus]}: variación anual",
            marker=dict(color=c, line=dict(color=SURFACE, width=2), pattern=bar_pattern(d["year"])),
            hovertemplate="%{y:+.1f}%",
        )
    )
    fig.update_layout(barmode="group")
    style(fig, "Variación interanual (%)", ".1f", y0, y1)
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Los años sin barra del salario no tienen dato ese año o el año anterior.")

    metric_opts = {
        f"Importe nominal ({unit_txt})": ("amount", "{:,.0f}", None),
        "Variación anual (%)": ("yoy_pct", "{:+.1f}", ("inflation_pct", "Inflación del IPC (dic./dic., %)")),
        f"Índice ({base_year}=100)": ("salary_index", "{:,.1f}", ("cpi", f"IPC (dic. {base_year}=100)")),
        f"Importe real (euros de {base_year}, {unit_txt})": ("real_amount", "{:,.0f}", None),
        "Diferencia con el IPC (puntos de índice)": ("gap_pts", "{:+.1f}", None),
    }
    pick = st.selectbox("Tabla", list(metric_opts))
    col, fmt, cpi_col = metric_opts[pick]
    t = wide_table(cmp, col, ids, y0, y1)
    if cpi_col:
        t.insert(0, cpi_col[1], cpi_plot.set_index(cpi_plot["year"].map(ylabel))[cpi_col[0]])
    show_table(t, fmt, "year")

# ------------------------------------------------------------------ CPI
with tab_cpi:
    yy = rebase_cpi(cpi_y, base_year)
    yy = yy[(yy["year"] >= y0) & (yy["year"] <= y1)]
    st.subheader(f"IPC de diciembre, índice general nacional (dic. {base_year}=100)")
    fig = go.Figure()
    add_line(fig, yy["year"], yy["cpi"], "IPC (diciembre)", INK, interpolated=[int(y) in prov_years for y in yy["year"]])
    style(fig, f"Índice (dic. {base_year}=100)", ",.0f", y0, y1)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Inflación anual (diciembre sobre diciembre)")
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=yy["year"],
            y=yy["inflation_dec_pct"],
            name="Diciembre sobre diciembre",
            marker=dict(color=SERIES_COLORS[0], line=dict(color=SURFACE, width=2), pattern=bar_pattern(yy["year"])),
            hovertemplate="%{y:+.1f}%",
        )
    )
    style(fig, "%", ".1f", y0, y1)
    st.plotly_chart(fig, use_container_width=True)

    t = yy.rename(
        columns={
            "year": "Año",
            "cpi": f"IPC diciembre ({base_year}=100)",
            "inflation_dec_pct": "Inflación, dic./dic. (%)",
        }
    ).set_index("Año")
    t.index = t.index.map(ylabel)
    show_table(t, "{:,.2f}", "cpi")

# ------------------------------------------------------------------ sources
with tab_src:
    prov_txt = (
        "; ".join(
            f"para diciembre de {y} se supone una inflación dic./dic. de {es(p, '+.1f')}%"
            for y, p in PROV_INFLATION.items()
        )
        or "no hay años provisionales"
    )
    st.subheader("Método")
    st.markdown(
        f"""
- **IPC**: INE, índice general nacional (serie `IPC251852`, base 2021, retropolada por el INE hasta 2002),
  descargado de la API abierta del INE. Se usa el índice de **diciembre** de cada año, reescalado para que
  **diciembre del año base = 100**; así la variación acumulada coincide con la calculadora de inflación del INE
  (diciembre a diciembre). Solo se usan años completos, salvo el año provisional indicado a continuación.
- **IPC provisional**: {prov_txt}.
  Es un supuesto, no un dato del INE: se marca como «prov.» y se sustituye automáticamente por el dato real cuando el INE
  publique el IPC de diciembre (`PROVISIONAL_DEC_INFLATION_PCT` en `etl/ine_cpi.py`).
- **Vista de índice**: cada salario se divide por su propio valor en el año base, de modo que es directamente
  comparable con el IPC.
- **Poder adquisitivo**: salario / (IPC / 100), en euros del año base.
- **Importes anuales**: cifras mensuales multiplicadas por el número de pagas al año de cada serie (ver tabla inferior).
  El SMI se anualiza con 14 pagas. Para Titulares y Catedráticos de Universidad las pagas extra son inferiores a una
  mensualidad, así que se usan las pagas equivalentes que resultan de las tablas de la Universidad de Alicante
  («Total anual» / total mensual, 2025 y 2026, mismo cociente en ambos años) y se extrapolan a todos los años.
- **Salario neto (opción «Aplicar IRPF»)**: base = salario bruto anual − mínimo exento ({allowance_txt}; mínimo 0). Sobre esa base se aplica el IRPF de la Comunidad Valenciana de forma progresiva, con el **tipo total**
  (estatal + autonómico) de cada tramo y de cada año, publicado por datosmacro.com
  ([{net_years[0]}-{net_years[-1]}]({IRPF_PAGE_URL})). Neto = bruto − cuota. **No se descuentan las cotizaciones a la
  Seguridad Social** ni otras reducciones o deducciones personales, por lo que es una aproximación.
  El **SMI está exento de IRPF**: su importe neto es igual al bruto.
  Fuera de {net_years[0]}-{net_years[-1]} no hay tramos y el neto no está disponible. Los tramos de 2025 combinan la
  escala autonómica valenciana de 2025 (aportada por el proyecto) con la escala estatal, que no cambió respecto a 2024. Los de 2026 son la escala completa aportada por el proyecto
  (el IPC de 2026 aún no está disponible, por lo que ese año no se puede comparar).
- **Penalización por jornada (opción «Penalizar profesorado…»)**: en {REDUCTION_YEAR} el resto de puestos redujo la
  jornada semanal de {es(OLD_WEEKLY_HOURS, ',.1f')} a {es(NEW_WEEKLY_HOURS, ',.1f')} horas sin bajar el sueldo; el
  profesorado sigue en {es(OLD_WEEKLY_HOURS, ',.1f')}. La opción multiplica el salario nominal del profesorado desde
  {REDUCTION_YEAR} por {es(NEW_WEEKLY_HOURS, ',.1f')}/{es(OLD_WEEKLY_HOURS, ',.1f')} ({es(hours_factor(), ',.4f')}), es decir,
  su sueldo por hora trabajada respecto al del resto. Se aplica después del IRPF (sobre el importe neto si esa opción
  está activa) y a todos los cálculos derivados del IPC. El SMI y el resto de series no se modifican.
- Los años sin dato se dejan en blanco salvo que se active *Rellenar huecos*.
        """
    )
    st.subheader("Series salariales")
    src = meta[["label", "category", "basis", "unit", "payments_per_year", "source", "source_urls", "notes"]].copy()
    src["label"] = [label_of[s] for s in src.index]
    src["category"] = src["category"].map(lambda c: CATEGORY_LABELS.get(c, c))
    src["basis"] = src["basis"].map(lambda b: BASIS_LABELS.get(b, b))
    src["unit"] = src["unit"].map(lambda u: UNIT_LABELS.get(u, u))
    src.columns = ["Serie", "Categoría", "Base", "Unidad", "Pagas/año", "Fuente", "URL", "Notas"]
    st.dataframe(src.reset_index(drop=True), use_container_width=True, hide_index=True)

    rejected = load_catalog()[1]
    if rejected:
        st.subheader("Consideradas pero no incluidas")
        st.caption("Excluidas por no tener un histórico documentado desde 2008 hasta el último año.")
        st.dataframe(pd.DataFrame(rejected), use_container_width=True, hide_index=True)
