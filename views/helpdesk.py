"""Helpdesk chat page. No sign-in: users pick Student or Teacher."""
from html import escape

import streamlit as st

from core import agent, auth, config, db, rag
from core.guardrails import redact_pii
from core.ui import LOGO_PATH, header, pill, steps_html

EXAMPLES = [
    "PC-12 is asking for a password and won't log in",
    "Ano po ang password ng PC-12?",
    "I waited 15 minutes and PC-12 is still locked",
    "Walang internet sa PC-07, ano po gagawin ko?",
    "I already restarted PC-03 twice and it still has no display",
    "May usok na lumalabas sa PC-20!",
    "What is the status of TKT-0001?",
    "Which server is PC-20 connected to?",
]
HOW_IT_WORKS = [
    ("Describe the problem", "Type what you see, in English or Taglish. Include the unit number."),
    ("Follow the steps", "LabAssist answers from the official lab procedures (SOPs)."),
    ("Request if needed", "Still not fixed? LabAssist files a ticket or an unlock request."),
    ("Track the status", "The Lab Administrator approves it. Ask for your ticket status anytime."),
]
RESOLUTION_LABEL = {
    "answered": "Answered", "action": "Action completed", "ticket": "Ticket filed",
    "escalated": "Escalated", "no_answer": "Not covered", "blocked": "Blocked by policy",
}
ASSISTANT_AVATAR = str(LOGO_PATH)
USER_AVATAR = ":material/person:"

retriever = rag.refresh_if_changed()  # picks up SOPs added/removed on the KB page


def new_conversation(user: dict):
    st.session_state.conversation_id = db.create_conversation(user["user_id"], user["role"])
    st.session_state.chat = []  # list of dicts rendered on screen


# Sidebar
with st.sidebar:
    st.markdown("<div class='side-title'>Select your role</div>", unsafe_allow_html=True)
    # no sign-in: role + random session id
    kind = st.segmented_control("User type", ["Student", "Teacher"], default="Student",
                                label_visibility="collapsed", width="stretch") or "Student"
    client_id = st.session_state.setdefault("client_id", auth.new_client_id())
    user, _ = auth.identify(kind.lower(), client_id)
    st.caption("No sign-in needed." + (" Stations are logged in by your teacher; students are "
               "never given a password." if kind == "Student" else
               " Unlock requests from teachers are marked high priority for the Lab Administrator."))

    # new conversation when the role changes
    if st.session_state.get("identity") != user["user_id"]:
        st.session_state.identity = user["user_id"]
        new_conversation(user)
    if st.button("New conversation", width="stretch"):
        new_conversation(user)
        st.rerun()

    st.divider()
    st.subheader("Service status")
    if not config.llm_enabled():
        ai_dot, ai_text = "dot-off", "Offline mode (no API key)"
    elif agent.LLM_STATUS.get("offline_reason"):
        ai_dot, ai_text = "dot-warn", "Offline mode (model unavailable)"
    else:
        ai_dot, ai_text = "dot-ok", f"Online ({agent.LLM_STATUS.get('last_model') or config.LLM_MODELS[0]})"
    idx_dot, idx_text = ("dot-ok", "Hybrid search") if retriever.vector_ok else ("dot-warn", "Keyword search only")
    st.markdown(
        f"<div class='status-line'><span class='status-dot {ai_dot}'></span>Assistant: {escape(ai_text)}</div>"
        f"<div class='status-line'><span class='status-dot {idx_dot}'></span>Knowledge base: {idx_text} "
        f"({len(retriever.chunks)} sections)</div>", unsafe_allow_html=True)

    st.divider()
    st.subheader("Lab information")
    st.markdown(
        "<div class='meta'><b>Hours:</b> Monday to Friday, 7:00 AM - 5:00 PM<br>"
        "<b>Maintenance:</b> every first Saturday of the month<br>"
        "<b>Station login:</b> your teacher logs the station in. Students are never given passwords.<br>"
        "<b>Emergency</b> (sparks, smoke, burning smell): step away and tell your teacher at once.</div>",
        unsafe_allow_html=True)


# Rendering helpers
def render_actions(actions: list):
    """Cards for tool results (never a password)."""
    for a in actions:
        d = a.get("data", {})
        with st.container(border=True):
            if a["tool"] == "request_station_unlock" and a["ok"]:
                title = "Existing unlock request" if a["status"] == "duplicate" else "Unlock request"
                st.markdown(f"**{title} {d['ticket_no']}** &nbsp; {pill(d['status'])} &nbsp; "
                            f"{pill(d['priority'])}", unsafe_allow_html=True)
                after = ("You can log the station in once it is unlocked." if user["role"] == "teacher"
                         else "Your teacher will log the station in once it is unlocked.")
                st.markdown(f"<div class='meta'>Unit {d['unit']} - waiting for approval by the Lab "
                            f"Administrator. {after}</div>", unsafe_allow_html=True)
            elif a["tool"] in ("create_ticket", "escalate_to_admin") and a["ok"]:
                title = "Escalated to Lab Administrator" if a["tool"] == "escalate_to_admin" else "Ticket filed"
                st.markdown(f"**{title}: {d['ticket_no']}** &nbsp; {pill(d['status'])} &nbsp; "
                            f"{pill(d['priority'])}", unsafe_allow_html=True)
                note = " The Lab Administrator has been notified." if d.get("admin_notified") else ""
                st.markdown(f"<div class='meta'>{escape(d['category'])} - unit {escape(d['unit'])}.{note}</div>",
                            unsafe_allow_html=True)
            elif a["tool"] == "unlock_station" and a["ok"]:
                st.markdown(f"**{d['unit']}** &nbsp; {pill('active')}", unsafe_allow_html=True)
            elif a["tool"] == "check_ticket_status" and a["ok"]:
                st.markdown(f"**{d['ticket_no']}** &nbsp; {pill(d['status'])} &nbsp; {pill(d['priority'])}",
                            unsafe_allow_html=True)
                st.markdown(f"<div class='meta'>{escape(d['category'])} - unit {escape(d.get('unit') or '-')} "
                            f"- last update {d['updated_at']}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div class='meta'>{escape(a['message'])}</div>", unsafe_allow_html=True)


def render_meta(m: dict):
    """Cards, PII notice, sources and details under a reply."""
    render_actions(m.get("actions", []))
    if m.get("pii"):
        st.warning("Personal information was masked before processing: " + ", ".join(m["pii"]) + ".")
    if m.get("sources") and m.get("relevant"):
        with st.expander("Sources (lab procedures used)"):
            for r in m["sources"]:
                st.markdown(f"**{r['sop_id']} - {r['section']}** &nbsp; hybrid `{r['score']:.3f}` "
                            f"&nbsp; vector `{r['vector']:.3f}` &nbsp; keyword (BM25) `{r['bm25']:.2f}`")
                st.caption(r["body"][:400] + ("..." if len(r["body"]) > 400 else ""))
    st.caption(f"{RESOLUTION_LABEL.get(m['resolution'], m['resolution'])} | {m['category']} | "
               f"{m['latency_ms'] / 1000:.1f} s | {m['model']}")


def requests_strip(u: dict):
    """This session's recent requests, shown above the chat."""
    title, tickets = "Your requests", db.tickets_for_requester(u["user_id"], 4)
    if not tickets:
        return
    chips = "".join(f"<span class='ticket-chip'><b>{t['ticket_no']}</b> {escape(t['unit'] or '-')} "
                    f"{pill(t['status'])}</span>" for t in tickets)
    st.markdown(f"<div class='requests-strip'><span class='panel-title'>{title}</span>{chips}</div>",
                unsafe_allow_html=True)


# Main page
header("CSIS ICT Laboratory Helpdesk", "LabAssist - First-level support for the ICT Laboratory")

chat_col = st.container()

with chat_col:
    st.markdown(f"<div class='meta'>Using LabAssist as a <b>{user['role']}</b> (change it in the "
                "panel on the left). Describe the problem in English, Filipino or Taglish and "
                "include the unit number (e.g. PC-12).</div>", unsafe_allow_html=True)
    requests_strip(user)
    if not st.session_state.get("chat"):
        st.markdown(steps_html(HOW_IT_WORKS, wide=True), unsafe_allow_html=True)
        st.markdown("<div class='panel-title' style='margin-top:10px'>Sample questions</div>",
                    unsafe_allow_html=True)
        cols = st.columns(2)
        for i, q in enumerate(EXAMPLES):
            if cols[i % 2].button(q, key=f"ex{i}", width="stretch"):
                st.session_state.pending = q
                st.rerun()

    # Re-draw the conversation so far
    for m in st.session_state.get("chat", []):
        with st.chat_message(m["role"], avatar=ASSISTANT_AVATAR if m["role"] == "assistant" else USER_AVATAR):
            st.markdown(m["content"])
            if m["role"] == "assistant":
                render_meta(m)

prompt = st.chat_input("Describe your lab IT problem...", max_chars=config.MAX_MESSAGE_CHARS)
prompt = prompt or st.session_state.pop("pending", None)

if prompt:
    with chat_col:
        with st.chat_message("user", avatar=USER_AVATAR):
            st.markdown(prompt)
        with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
            waiting = st.empty()
            waiting.caption("Checking the lab procedures...")
            stream = agent.stream_message(user, st.session_state.conversation_id, prompt)

            def live():
                """Show each piece as it arrives."""
                for i, piece in enumerate(stream):
                    if i == 0:
                        waiting.empty()
                    yield piece

            try:
                st.write_stream(live())
                res = stream.result
            except Exception as e:  # never crash the page
                waiting.empty()
                st.error(f"Something went wrong ({type(e).__name__}). Please try again.")
                st.stop()
            msg = {"role": "assistant", "content": res.reply, "sources": res.sources,
                   "actions": res.actions, "pii": res.pii_types, "latency_ms": res.latency_ms,
                   "model": res.model, "resolution": res.resolution, "category": res.category,
                   "relevant": res.relevant}
            render_meta(msg)
    # keep the masked text in the history
    st.session_state.chat.append({"role": "user", "content": redact_pii(prompt)[0]})
    st.session_state.chat.append(msg)
    if res.actions:  # refresh the "Your requests" panel
        st.rerun()
