"""Entry point: page setup and navigation. Run with run.bat."""
import streamlit as st

from core.ui import LOGO_PATH, load_css, startup

st.set_page_config(page_title="CSIS ICT Laboratory Helpdesk", page_icon=str(LOGO_PATH),
                   layout="wide")
st.logo(str(LOGO_PATH), size="large")
load_css()
startup()  # create DB + load knowledge base (cached, runs once)

pages = [
    st.Page("views/helpdesk.py", title="Helpdesk", icon=":material/support_agent:", default=True),
    st.Page("views/admin_dashboard.py", title="Admin Dashboard", icon=":material/dashboard:"),
    st.Page("views/knowledge_base.py", title="Knowledge Base", icon=":material/menu_book:"),
]
st.navigation(pages).run()
