"""Shared Streamlit helpers: header, pills, KPI tiles, charts, filters, admin PIN."""
import base64
from functools import lru_cache
from html import escape

import streamlit as st

from core import config, db

LOGO_PATH = config.BASE_DIR / "assets" / "csis-logo.png"
CSS_PATH = config.BASE_DIR / "assets" / "style.css"
# brand colors (also in config.toml)
PRIMARY, SECONDARY, ACCENT, ALERT = "#310098", "#036403", "#C9A800", "#B3261E"


@st.cache_resource(show_spinner="Starting LabAssist (database and knowledge base)...")
def startup():
    """Runs once per server start: create tables/seed data and load the KB index."""
    db.init_db()
    from core.rag import get_retriever
    return get_retriever()


def load_css() -> None:
    st.markdown(f"<style>{CSS_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


@lru_cache(maxsize=1)
def _logo_b64() -> str:
    return base64.b64encode(LOGO_PATH.read_bytes()).decode()


def header(title: str, subtitle: str, motto: str = "We Engage. We Explore. We Excel.") -> None:
    """Official page header: logo, title, subtitle and the school motto."""
    st.markdown(
        f"<div class='csis-header'><img src='data:image/png;base64,{_logo_b64()}' "
        f"alt='CSIS logo'/><div><h1>{escape(title)}</h1>"
        f"<div class='subtitle'>{escape(subtitle)}</div>"
        f"<div class='motto'>{escape(motto)}</div></div></div>",
        unsafe_allow_html=True)


def section(title: str) -> None:
    st.markdown(f"<div class='csis-section'>{escape(title)}</div>", unsafe_allow_html=True)


def pill(value: str) -> str:
    """HTML for a status / priority pill, e.g. pill('pending_approval')."""
    css = {"pending_approval": "pending", "in_progress": "progress"}.get(value, value)
    label = db.STATUS_LABELS.get(value, str(value).capitalize())
    return f"<span class='pill pill-{escape(css)}'>{escape(label)}</span>"


def client_key() -> str:
    """Id of this browser session (PIN lockout is per session)."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return "session:" + get_script_run_ctx().session_id
    except Exception:  # noqa: BLE001 - outside Streamlit (tests)
        return "local"


def require_admin_pin() -> bool:
    """Admin PIN form. Returns True once unlocked."""
    from core import auth  # avoids a circular import
    if st.session_state.get("admin_ok"):
        with st.sidebar:
            if st.button("Lock admin pages", width="stretch"):
                st.session_state.admin_ok = False
                st.rerun()
        return True
    st.info("This page is for the Lab Administrator. Enter the admin PIN to continue.")
    with st.form("pin_form"):
        pin = st.text_input("Admin PIN", type="password")
        if st.form_submit_button("Unlock", type="primary"):
            ok, reason = auth.verify_admin_pin(pin, client_key())
            if ok:
                st.session_state.admin_ok = True
                st.rerun()
            else:
                st.error(reason)
    return False


def kpi_cards(items: list[tuple]) -> None:
    """KPI tiles. items = [(label, value, tone, note)]."""
    st.markdown("<div class='kpi-grid'>" + "".join(
        f"<div class='kpi kpi-{tone}'><div class='kpi-label'>{escape(label)}</div>"
        f"<div class='kpi-value'>{escape(str(value))}</div>"
        f"<div class='kpi-note'>{escape(note)}</div></div>"
        for label, value, tone, note in items) + "</div>", unsafe_allow_html=True)


# Charts (Altair)
def _axis(title=None, **kw):
    import altair as alt
    # horizontal labels, long ones wrapped
    kw.setdefault("labelExpr", "split(datum.label, ' ')")
    return alt.Axis(title=title, labelAngle=0, labelFontSize=12, titleFontSize=12,
                    labelColor="#4F4C63", **kw)


def bar_chart(df, x: str, y: str, color: str, height: int = 260, label_map: dict | None = None) -> None:
    """Vertical bars with horizontal, wrapped x-axis labels."""
    import altair as alt
    data = df.copy()
    if label_map is not None:  # {} = just tidy the values
        data[x] = data[x].map(lambda v: label_map.get(v, str(v).replace("_", " ").capitalize()))
    chart = (alt.Chart(data).mark_bar(color=color, cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
             .encode(x=alt.X(f"{x}:N", sort="-y", axis=_axis(labelLimit=120)),
                     y=alt.Y(f"{y}:Q", axis=alt.Axis(title=None, tickMinStep=1, labelColor="#4F4C63")),
                     tooltip=[alt.Tooltip(f"{x}:N", title=x.capitalize()), alt.Tooltip(f"{y}:Q", title=y.capitalize())])
             .properties(height=height))
    st.altair_chart(chart, width="stretch")


def line_chart(df, x: str, series: dict, height: int = 240) -> None:
    """Lines over days. series = {column: (label, color)}."""
    import altair as alt
    data = df.melt(id_vars=[x], value_vars=list(series), var_name="series", value_name="value")
    data["series"] = data["series"].map(lambda c: series[c][0])
    chart = (alt.Chart(data).mark_line(point=True, strokeWidth=2.5)
             .encode(x=alt.X(f"{x}:T", axis=_axis(format="%b %d", labelExpr="datum.label")),
                     y=alt.Y("value:Q", axis=alt.Axis(title=None, labelColor="#4F4C63", format="~g",
                                                      tickMinStep=1)),
                     color=alt.Color("series:N", legend=alt.Legend(orient="bottom", title=None),
                                     scale=alt.Scale(domain=[v[0] for v in series.values()],
                                                     range=[v[1] for v in series.values()])),
                     tooltip=[alt.Tooltip(f"{x}:T", title="Day"), "series:N", "value:Q"])
             .properties(height=height))
    st.altair_chart(chart, width="stretch")


# Checkbox dropdown filter
def checkbox_filter(label: str, options: list, key: str, format_func=str) -> list:
    """Dropdown with an 'All' checkbox plus one per option. Returns the selection."""
    all_key, keys = f"{key}_all", {o: f"{key}_{o}" for o in options}
    for k in [all_key, *keys.values()]:
        st.session_state.setdefault(k, True)

    def toggle_all():  # "All" checks or clears every option
        for k in keys.values():
            st.session_state[k] = st.session_state[all_key]

    def toggle_one():  # "All" stays checked only while every option is checked
        st.session_state[all_key] = all(st.session_state[k] for k in keys.values())

    chosen = [o for o in options if st.session_state[keys[o]]]
    summary = ("All" if len(chosen) == len(options) else "None" if not chosen
               else format_func(chosen[0]) if len(chosen) == 1 else f"{len(chosen)} selected")
    with st.popover(f"{label}: {summary}", width="stretch"):
        st.checkbox("All", key=all_key, on_change=toggle_all)
        st.markdown("<hr class='filter-sep'>", unsafe_allow_html=True)
        for o in options:
            st.checkbox(format_func(o), key=keys[o], on_change=toggle_one)
    return chosen


def steps_html(steps: list[tuple[str, str]], wide: bool = False) -> str:
    """Numbered 'how it works' tiles (2 per row, or 4 per row when wide=True)."""
    return f"<div class='steps{' wide' if wide else ''}'>" + "".join(
        f"<div class='step'><span class='num'>{i}</span><div class='title'>{escape(t)}</div>"
        f"<div class='desc'>{escape(d)}</div></div>" for i, (t, d) in enumerate(steps, 1)) + "</div>"
