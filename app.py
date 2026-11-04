"""KTVDI: Streamlit sebagai host Python; seluruh antarmuka dirender oleh HTML/CSS/JS."""
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components
from backend import initialize_firebase, handle_event, get_stats, get_all_broadcast_rows, get_recent_changes
try:
    from backend import get_latest_transmitter_update_timestamp
except ImportError:
    def get_latest_transmitter_update_timestamp():
        return None

st.set_page_config(page_title="KTVDI", page_icon="📡", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""
<style>
[data-testid="stSidebar"],[data-testid="stSidebarNav"],[data-testid="collapsedControl"],
[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stDecoration"],#MainMenu,footer{display:none!important;visibility:hidden!important;height:0!important}
[data-testid="stAppViewContainer"],[data-testid="stMain"]{background:#f4f7fb!important}
[data-testid="stMainBlockContainer"]{max-width:100%!important;padding:0!important;margin:0!important}
iframe{border:0!important;display:block!important}
</style>
""", unsafe_allow_html=True)

@st.cache_resource
def _component():
    return components.declare_component("ktvdi_frontend", path=str(Path(__file__).parent / "frontend"))

for key, default in (("ktvdi_session",{}),("ktvdi_result",None),("ktvdi_event_id",None)):
    if key not in st.session_state: st.session_state[key]=default

try:
    initialize_firebase(st.secrets)
    rows=get_all_broadcast_rows()
    provinces=st.secrets.get("PUBLIC_PROVINCES") if "PUBLIC_PROVINCES" in st.secrets else None
    if not provinces:
        try:
            from firebase_admin import db
            pdata=db.reference("provinsi").get() or {}
            provinces=sorted(pdata.values())
        except Exception: provinces=[]
    # Kirim hasil aksi ke komponen hanya sekali. Tanpa konsumsi satu-kali,
    # hasil lama (termasuk pesan "Aksi tidak dikenal") ikut terkirim lagi
    # setiap Streamlit melakukan rerun/navigasi.
    result_to_send = st.session_state.ktvdi_result
    event=_component()(result=result_to_send,
        auth=st.session_state.ktvdi_session.get("auth"), stats=get_stats(), rows=rows,
        changes=get_recent_changes(), provinces=provinces,
        map_last_updated=get_latest_transmitter_update_timestamp(),
        key="ktvdi_web_frontend", default=None)
    if result_to_send is not None:
        st.session_state.ktvdi_result = None

    if isinstance(event,dict) and event.get("event_id")!=st.session_state.ktvdi_event_id:
        st.session_state.ktvdi_event_id=event.get("event_id")
        st.session_state.ktvdi_result=handle_event(event,st.session_state.ktvdi_session,st.secrets)
        if isinstance(st.session_state.ktvdi_result, dict):
            st.session_state.ktvdi_result["action"]=event.get("action")
        st.rerun()
except Exception as exc:
    st.error("KTVDI belum dapat terhubung ke layanan backend. Periksa Streamlit Secrets dan log aplikasi.")
    st.caption(f"Jenis kesalahan: {type(exc).__name__}")
