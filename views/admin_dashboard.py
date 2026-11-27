"""Admin Dashboard (admin PIN): requests, stations, analytics, tickets, audit log."""
import json
from html import escape

import pandas as pd
import streamlit as st

from core import auth, db, metrics, workflow
from core.ui import (ACCENT, ALERT, PRIMARY, SECONDARY, bar_chart, checkbox_filter, header,
                     kpi_cards, line_chart, pill, require_admin_pin, section)

header("Admin Dashboard", "LabAssist - CSIS ICT Laboratory Helpdesk")
if not require_admin_pin():
    st.stop()

ADMIN = dict(auth.ADMIN_USER)  # the dashboard acts as the Lab Administrator
ACTIVE_STATUSES = ["pending_approval", "open", "escalated", "in_progress"]
PRIORITIES = ["critical", "high", "medium", "low"]
RESOLUTION_LABELS = {"answered": "Answered", "action": "Action done", "ticket": "Ticket filed",
                     "escalated": "Escalated", "no_answer": "Not covered", "blocked": "Blocked"}


def run_action(ticket: dict, action: str) -> None:
    result = workflow.apply_action(ticket["ticket_no"], action, ADMIN)
    if result["secret"].get("station_password"):
        # kept in this session only, shown once
        st.session_state.new_password = {"unit": ticket["unit"],
                                         "password": result["secret"]["station_password"]}
    st.session_state.flash = (result["ok"], result["message"])


# One-time messages from the last button click
if st.session_state.get("new_password"):
    info = st.session_state.new_password
    with st.container(border=True):
        st.markdown(f"**New station password for {info['unit']}**")
        st.code(info["password"], language=None)
        st.caption("Shown only once, only on this dashboard. Give it to the teachers directly. "
                   "It is stored only as a secure hash and is not written to any log.")
        if st.button("Dismiss"):
            del st.session_state.new_password
            st.rerun()
if st.session_state.get("flash"):
    ok, text = st.session_state.pop("flash")
    (st.success if ok else st.error)(text)

# KPI tiles
k = metrics.kpis()
kpi_cards([
    ("Pending approvals", k["pending_approvals"], "accent", "Waiting for your decision"),
    ("Open tickets", k["open_tickets"], "alert", "Not yet resolved or rejected"),
    ("Requests", k["requests"], "primary", "Messages received"),
    ("Deflection rate", f"{k['deflection_rate']:.0f}%", "secondary", "Solved without a ticket"),
    ("Average response", f"{k['avg_latency_ms'] / 1000:.1f} s", "primary", "Time to a full answer"),
    ("Blocked requests", k["blocked"], "alert", "Stopped by the guardrails"),
])

# 1. Pending Requests
pending = db.list_tickets(ACTIVE_STATUSES)
section(f"Pending Requests ({len(pending)})")
if not pending:
    st.markdown("<div class='empty-note'>No pending requests. New unlock requests and tickets "
                "appear here.</div>", unsafe_allow_html=True)
for t in pending:
    with st.container(border=True):
        info_col, btn_col = st.columns([3, 2], gap="medium")
        with info_col:
            st.markdown(f"<span class='ticket-no'>{t['ticket_no']}</span> &nbsp; {pill(t['status'])} "
                        f"&nbsp; {pill(t['priority'])} &nbsp; <span class='meta'>{escape(t['category'])}</span>",
                        unsafe_allow_html=True)
            requester = t["requester"] + (f" ({t['requester_section']})" if t["requester_section"] else "")
            st.markdown(f"<div class='meta'>Requester: {escape(requester)} &nbsp;|&nbsp; "
                        f"Unit: <b>{escape(t['unit'] or '-')}</b> &nbsp;|&nbsp; Filed: {t['created_at']}</div>",
                        unsafe_allow_html=True)
            st.markdown(escape(t["description"]))
        with btn_col:
            station_ok = workflow.is_station(t["unit"])
            key = t["ticket_no"]
            b1, b2 = st.columns(2)
            b3, b4 = st.columns(2)
            clicked = None
            if b1.button("Unlock station", key=f"u{key}", width="stretch", disabled=not station_ok):
                clicked = "unlock"
            if b2.button("Reset password", key=f"p{key}", width="stretch", disabled=not station_ok,
                         help="Reset station password (shown once, here only)"):
                clicked = "reset"
            if b3.button("Mark resolved", key=f"r{key}", width="stretch", type="primary"):
                clicked = "resolve"
            if b4.button("Reject", key=f"x{key}", width="stretch"):
                clicked = "reject"
            if clicked:
                run_action(t, clicked)
                st.rerun()

# 2. Stations
stations = db.list_stations()
counts = {s: sum(1 for x in stations if x["status"] == s) for s in db.STATION_STATUSES}
section("Stations")
st.markdown("<div class='legend'>" + "".join(
    f"<span class='legend-item'><span class='swatch {s}'></span>{db.STATUS_LABELS[s]} "
    f"<b>{counts[s]}</b></span>" for s in db.STATION_STATUSES) + "</div>", unsafe_allow_html=True)
server_cols = st.columns(3, gap="medium")
for col, server in zip(server_cols, ["MPS-1", "MPS-2", "MPS-3"]):
    units = [s for s in stations if s["server"] == server]
    with col.container(border=True):
        st.markdown(f"<div class='server-title'>{server} <span class='meta'>{units[0]['unit']} to "
                    f"{units[-1]['unit']}</span></div>", unsafe_allow_html=True)
        st.markdown("<div class='station-grid'>" + "".join(
            f"<div class='station {s['status']}' title='{s['unit']}: {db.STATUS_LABELS[s['status']]}'>"
            f"{s['unit'][3:]}</div>" for s in units)
            + "</div>", unsafe_allow_html=True)

with st.expander("Change a station's status manually"):
    with st.form("station_status"):
        c1, c2, c3 = st.columns([2, 2, 1], vertical_alignment="bottom")
        unit = c1.selectbox("Station", [s["unit"] for s in stations])
        new_status = c2.selectbox("Status", db.STATION_STATUSES, format_func=lambda s: db.STATUS_LABELS[s])
        if c3.form_submit_button("Save", width="stretch"):
            db.set_station_status(unit, new_status)
            db.log_action(ADMIN["user_id"], "admin_set_station_status",
                          {"unit": unit, "status": new_status}, {"status": "success"}, True)
            st.session_state.flash = (True, f"{unit} set to {db.STATUS_LABELS[new_status]}.")
            st.rerun()

# 3. Analytics
section("Analytics")


def chart_card(title: str, draw) -> None:
    """Card with a title, or 'No data yet.'"""
    with st.container(border=True):
        st.markdown(f"<div class='chart-title'>{title}</div>", unsafe_allow_html=True)
        if not draw():
            st.caption("No data yet.")


def _bars(rows, x, y, color, labels=None):
    def draw():
        df = pd.DataFrame(rows)
        if df.empty:
            return False
        bar_chart(df, x, y, color, label_map=labels)
        return True
    return draw


left, mid, right = st.columns(3, gap="medium")
with left:
    chart_card("Requests by category", _bars(db.query(
        "SELECT category, COUNT(*) AS requests FROM messages WHERE role='assistant' "
        "GROUP BY category ORDER BY requests DESC"), "category", "requests", PRIMARY))
with mid:
    chart_card("Resolution breakdown", _bars(db.query(
        "SELECT resolution, COUNT(*) AS count FROM messages WHERE role='assistant' "
        "GROUP BY resolution ORDER BY count DESC"), "resolution", "count", SECONDARY, RESOLUTION_LABELS))
with right:
    chart_card("Requests by intent", _bars(metrics.by_intent(), "intent", "requests", ACCENT, {}))

trends = pd.DataFrame(metrics.daily_trends())


def _lines(series):
    def draw():
        if trends.empty:
            return False
        line_chart(trends, "day", series)
        return True
    return draw


t1, t2, t3 = st.columns(3, gap="medium")
with t1:
    chart_card("Requests per day", _lines({"requests": ("Requests", PRIMARY)}))
with t2:
    chart_card("Response time per day (ms)", _lines({"avg_latency_ms": ("Average", PRIMARY),
                                                     "max_latency_ms": ("Slowest", ALERT)}))
with t3:
    chart_card("Deflection rate per day (%)", _lines({"deflection_rate": ("Deflection", SECONDARY)}))

# 4. LLM observability
section("LLM observability")
kpi_cards([
    ("p95 response", f"{k['p95_latency_ms'] / 1000:.1f} s", "primary", "95% of answers are faster"),
    ("LLM answers", k["llm_answers"], "secondary", "Written by the language model"),
    ("Offline fallbacks", k["offline_fallbacks"], "accent", "Answered by the offline rules"),
    ("Tokens used", f"{k['prompt_tokens'] + k['completion_tokens']:,}", "primary", "Prompt + completion"),
    ("Mean time to resolution", f"{k['mttr_minutes']:.0f} min", "secondary", "Filing to resolved"),
])
models = pd.DataFrame(metrics.by_model())
if not models.empty:
    st.dataframe(models, width="stretch", hide_index=True, column_config={
        "model": "Model", "requests": "Requests", "avg_latency_ms": "Average latency (ms)",
        "tokens": "Tokens"})

# 5. All tickets
section("All tickets")
tickets = db.list_tickets()
if tickets:
    tdf = pd.DataFrame(tickets).drop(columns=["id"])
    categories = sorted(tdf["category"].unique())
    f1, f2, f3 = st.columns(3, gap="small")
    with f1:
        statuses = checkbox_filter("Status", db.TICKET_STATUSES, "flt_status",
                                   format_func=lambda s: db.STATUS_LABELS[s])
    with f2:
        priorities = checkbox_filter("Priority", PRIORITIES, "flt_priority", format_func=str.capitalize)
    with f3:
        cats = checkbox_filter("Category", categories, "flt_category")
    view = tdf[tdf["status"].isin(statuses) & tdf["priority"].isin(priorities)
               & tdf["category"].isin(cats)].copy()
    view["status"] = view["status"].map(db.STATUS_LABELS)
    view["priority"] = view["priority"].str.capitalize()
    st.caption(f"Showing {len(view)} of {len(tdf)} tickets")
    st.dataframe(view, width="stretch", hide_index=True, column_config={
        "ticket_no": "Ticket", "requester": "Requester", "requester_section": "Section",
        "category": "Category", "unit": "Unit", "description": st.column_config.TextColumn(
            "Description", width="large"), "priority": "Priority", "status": "Status",
        "external_ref": "Jira", "created_at": "Filed", "updated_at": "Updated"})
    with st.form("update_ticket"):
        c1, c2, c3 = st.columns([2, 2, 1], vertical_alignment="bottom")
        ticket_no = c1.selectbox("Ticket", [t["ticket_no"] for t in tickets])
        new_status = c2.selectbox("New status", db.TICKET_STATUSES, format_func=lambda s: db.STATUS_LABELS[s])
        if c3.form_submit_button("Update", width="stretch"):
            workflow.set_ticket_status(db.get_ticket(ticket_no), new_status, ADMIN, "admin_update_ticket")
            st.session_state.flash = (True, f"{ticket_no} set to {db.STATUS_LABELS[new_status]}.")
            st.rerun()
else:
    st.markdown("<div class='empty-note'>No tickets yet.</div>", unsafe_allow_html=True)

# 6. Audit log
section("Audit log")
logs = db.list_action_logs()
if logs:
    ldf = pd.DataFrame(logs)
    ldf["success"] = ldf["success"].map({1: "Yes", 0: "No"})
    ldf["result"] = ldf["result"].map(lambda r: json.loads(r).get("message", json.loads(r).get("status", "")))
    st.dataframe(ldf[["created_at", "user_id", "tool", "arguments", "success", "result"]],
                 width="stretch", hide_index=True, height=320, column_config={
                     "created_at": "Time", "user_id": "User", "tool": "Action", "arguments": "Details",
                     "success": "Success", "result": "Result"})
else:
    st.markdown("<div class='empty-note'>No actions logged yet.</div>", unsafe_allow_html=True)

with st.expander("Recent messages (stored after PII redaction)"):
    msgs = db.query("SELECT m.created_at, c.user_id, m.role, m.content, m.category, m.resolution, "
                    "m.latency_ms, m.model FROM messages m JOIN conversations c "
                    "ON c.id = m.conversation_id ORDER BY m.id DESC LIMIT 100")
    if msgs:
        st.dataframe(pd.DataFrame(msgs), width="stretch", hide_index=True)
