import streamlit as st
import firebase_admin
import hashlib
import smtplib
import random
import time
import re
import pandas as pd
from email.mime.text import MIMEText
from firebase_admin import credentials, db
from pytz import timezone
from datetime import datetime

# Impor library Gemini
import google.generativeai as genai # <-- TAMBAHKAN INI

# --- KONFIGURASI DAN INISIALISASI ---

st.set_page_config(page_title="KTVDI", page_icon="🇮🇩")

def initialize_firebase():
    """Menginisialisasi koneksi ke Firebase Realtime Database."""
    if not firebase_admin._apps:
        try:
            cred_dict = dict(st.secrets["FIREBASE"])
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred, {
                "databaseURL": "https://website-ktvdi-default-rtdb.firebaseio.com/"
            })
        except Exception as e:
            st.error(f"Gagal terhubung ke Firebase: {e}")
            st.stop()

# Inisialisasi Gemini API (tempatkan setelah inisialisasi Firebase)
# Pastikan st.secrets["GOOGLE_API"]["API_KEY"] sudah ada di secrets.toml
GEMINI_MODEL = None
try:
    if "GOOGLE_API" in st.secrets and "API_KEY" in st.secrets["GOOGLE_API"]:
        genai.configure(api_key=st.secrets["GOOGLE_API"]["API_KEY"])
        # Pilih model yang sesuai, gemini-pro atau gemini-1.5-flash cocok untuk teks
        GEMINI_MODEL = genai.GenerativeModel('gemini-1.5-flash')
    else:
        st.warning("Google Gemini API Key tidak ditemukan di `secrets.toml`. Chatbot tidak akan berfungsi.")
except Exception as e:
    st.error(f"Gagal menginisialisasi Gemini API: {e}. Pastikan API Key valid.")
    GEMINI_MODEL = None


def initialize_session_state():
    """Menginisialisasi semua variabel session state yang dibutuhkan."""
    states = {
        "login": False,
        "username": "",
        "halaman": "beranda",
        "mode": "Login", # Untuk selectbox Login/Daftar
        "login_error": "",
        "login_attempted": False,
        "lupa_password": False,
        "otp_sent": False,
        "otp_code": "",
        "reset_username": "",
        "otp_sent_daftar": False,
        "otp_code_daftar": "",
        "edit_mode": False, # Menandakan apakah sedang dalam mode edit
        "edit_data": None, # Menyimpan data yang sedang diedit
        "selected_other_user": None, # Menyimpan username pengguna lain yang dipilih untuk dilihat
        "comment_success_message": "", # Tambahkan ini untuk pesan sukses komentar
        # Tambahkan state untuk chatbot
        "chat_history": [] # Menyimpan riwayat obrolan chatbot
    }
    for key, value in states.items():
        if key not in st.session_state:
            st.session_state[key] = value

# Inisialisasi awal
initialize_firebase()
initialize_session_state()
WIB = timezone("Asia/Jakarta")

def switch_page(page_name):
    """Fungsi untuk berpindah halaman."""
    st.session_state.halaman = page_name

def proses_logout():
    """Membersihkan session state saat logout."""
    st.session_state.login = False
    st.session_state.username = ""
    st.session_state.selected_other_user = None
    switch_page("beranda")

# --- FUNGSI HELPER ---
# ... (fungsi-fungsi helper seperti hash_password, generate_otp, send_otp_email, switch_page, proses_logout tetap sama) ...

def display_sidebar():
    """Menampilkan sidebar untuk pengguna yang sudah login."""
    if st.session_state.login:
        users = db.reference("users").get() or {}
        user_data = users.get(st.session_state.username, {})
        nama_pengguna = user_data.get("nama", st.session_state.username)
        user_points = user_data.get("points", 0)

        st.sidebar.title(f"Hai, {nama_pengguna}!")
        st.sidebar.markdown(f"**Poin Anda:** {user_points} ⭐")
        st.sidebar.markdown("---")

        if st.sidebar.button("👤 Profil Saya"):
            st.session_state.selected_other_user = None
            switch_page("profile")
            st.rerun()
        if st.sidebar.button("👥 Lihat Profil Pengguna Lain"):
            switch_page("other_users")
            st.rerun()
        if st.sidebar.button("🏆 Leaderboard"):
            switch_page("leaderboard")
            st.rerun()
        # TOMBOL CHATBOT BARU
        if st.sidebar.button("🤖 Chatbot KTVDI"): # <-- TAMBAHKAN INI
            switch_page("chatbot")
            st.rerun()
        st.sidebar.button("🚪 Logout", on_click=proses_logout)

# ... (fungsi-fungsi display_login_form, display_forgot_password_form, display_registration_form, display_add_data_form, handle_edit_delete_actions, display_edit_data_page, display_profile_page, display_other_users_page tetap sama) ...

# MODIFIKASI FUNGSI display_leaderboard_page untuk membaca timestamp
def display_leaderboard_page():
    """Menampilkan halaman leaderboard kontributor."""
    st.header("🏆 Leaderboard Kontributor")

    all_users = db.reference("users").get() or {}
    
    leaderboard_data = []
    for username, data in all_users.items():
        if data.get("points", 0) > 0:
            leaderboard_data.append({
                "nama": data.get("nama", username),
                "username": username,
                "points": data.get("points", 0)
            })
    
    leaderboard_data.sort(key=lambda x: x["points"], reverse=True)

    # --- Bagian yang dimodifikasi untuk membaca timestamp dari Firebase ---
    last_update_timestamp_str = db.reference("app_metadata/last_leaderboard_update_timestamp").get()
    
    display_update_time_str = "Belum ada update poin tercatat"
    if last_update_timestamp_str:
        try:
            dt_object = datetime.strptime(last_update_timestamp_str, "%Y-%m-%d %H:%M:%S")
            dt_object_wib = WIB.localize(dt_object) 
            display_update_time_str = dt_object_wib.strftime("%d-%m-%Y %H:%M:%S WIB")
        except ValueError:
            display_update_time_str = f"Waktu update tidak valid."
        except Exception as e:
            display_update_time_str = f"Error waktu: {e}"
    # --- Akhir bagian yang dimodifikasi ---

    if leaderboard_data:
        st.write("Berikut adalah daftar kontributor teratas berdasarkan poin:")
        
        leaderboard_df = pd.DataFrame(leaderboard_data)
        leaderboard_df.index = leaderboard_df.index + 1
        st.dataframe(leaderboard_df[["nama", "points"]].rename(columns={"nama": "Nama Kontributor", "points": "Poin"}), use_container_width=True)
        
        st.markdown(f"<p style='font-size: small; color: grey;'>Data diperbarui pada: {display_update_time_str}</p>", unsafe_allow_html=True)
    else:
        st.info("Belum ada kontributor dengan poin yang tercatat.")
        st.markdown(f"<p style='font-size: small; color: grey;'>Terakhir diperbarui: {display_update_time_str}</p>", unsafe_allow_html=True) 

    st.markdown("---")
    if st.button("⬅️ Kembali ke Beranda"):
        switch_page("beranda")
        st.rerun()

# --- FUNGSI BARU UNTUK CHATBOT ---
def display_chatbot_page():
    st.header("🤖 Chatbot KTVDI (FAQ TV Digital)")
    st.info("Tanyakan apa saja tentang TV Digital di Indonesia!")

    if not GEMINI_MODEL:
        st.error("Chatbot tidak dapat diinisialisasi. Periksa konfigurasi API Key Anda.")
        if st.button("⬅️ Kembali ke Beranda"):
            switch_page("beranda")
            st.rerun()
        return

    # Inisialisasi chat session jika belum ada
    if "chat_session" not in st.session_state:
        st.session_state.chat_session = GEMINI_MODEL.start_chat(history=[])

    # Tampilkan riwayat obrolan
    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Input pengguna
    if prompt := st.chat_input("Tanyakan sesuatu..."):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Mengetik..."):
                try:
                    # Context/System Instruction untuk chatbot agar fokus pada topik TV Digital
                    # Ini adalah bagian kunci agar AI tidak ngelantur
                    system_instruction = (
                        "Anda adalah asisten virtual yang ahli dalam hal TV Digital di Indonesia. "
                        "Jawablah pertanyaan pengguna dengan jelas, informatif, dan ringkas. "
                        "Fokus pada topik seperti siaran TV digital, perangkat (TV, STB, antena), "
                        "wilayah layanan, troubleshooting dasar, dan hal-hal terkait TV digital di Indonesia. "
                        "Jika pertanyaan di luar topik, mohon sampaikan bahwa Anda hanya dapat membantu terkait TV Digital."
                    )
                    
                    # Gabungkan riwayat chat dengan prompt baru untuk mengirim ke Gemini
                    # Gemini API menerima riwayat sebagai list of dicts { 'role': ..., 'parts': [ { 'text': ... } ] }
                    # Kita harus format ulang chat_history Streamlit ke format Gemini
                    gemini_history = []
                    for msg in st.session_state.chat_history[:-1]: # Kirim semua kecuali pesan terakhir (prompt user saat ini)
                        gemini_history.append({'role': msg['role'], 'parts': [{'text': msg['content']}]})
                    
                    # Untuk prompt saat ini, kirim sebagai 'user' role
                    gemini_history.append({'role': 'user', 'parts': [{'text': prompt}]})
                    
                    # Panggil generate_content dengan history dan system instruction
                    response = GEMINI_MODEL.generate_content(
                        contents=gemini_history,
                        system_instruction=system_instruction
                    )
                    
                    full_response = response.text
                    st.markdown(full_response)
                    st.session_state.chat_history.append({"role": "assistant", "content": full_response})
                except Exception as e:
                    st.error(f"Terjadi kesalahan saat menghubungi Chatbot: {e}. Coba lagi.")
                    st.session_state.chat_history.append({"role": "assistant", "content": "Maaf, terjadi kesalahan. Silakan coba lagi."})
        st.rerun() # Rerun untuk menampilkan respons baru

    st.markdown("---")
    if st.button("⬅️ Kembali ke Beranda"):
        switch_page("beranda")
        st.rerun()

# --- ROUTING HALAMAN UTAMA APLIKASI ---

# Panggil fungsi backfill poin secara otomatis di awal (jika masih ada)
# backfill_contributor_points_integrated_auto() # Hapus ini jika backfill sudah selesai

st.title("🇮🇩 KOMUNITAS TV DIGITAL INDONESIA 🇮🇩")
display_sidebar()


if st.session_state.halaman == "beranda":
    st.header("📺 Data Siaran TV Digital di Indonesia")
    # ... (logika halaman beranda tetap sama) ...
    provinsi_data = db.reference("provinsi").get()
    
    if provinsi_data:
        provinsi_list = sorted(provinsi_data.values())
        selected_provinsi = st.selectbox("Pilih Provinsi", provinsi_list, key="select_provinsi")
        
        siaran_data_prov = db.reference(f"siaran/{selected_provinsi}").get()
        if siaran_data_prov:
            wilayah_list = sorted(siaran_data_prov.keys())
            selected_wilayah = st.selectbox("Pilih Wilayah Layanan", wilayah_list, key="select_wilayah")
            
            mux_data = siaran_data_prov[selected_wilayah]
            mux_list = sorted(mux_data.keys())
            
            selected_mux_filter = st.selectbox("Pilih Penyelenggara MUX", ["Semua MUX"] + mux_list, key="select_mux_filter")

            if selected_mux_filter == "Semua MUX":
                for mux_key, mux_details in mux_data.items():
                    st.subheader(f"📡 {mux_key}")
                    if isinstance(mux_details, list):
                        siaran_list = mux_details
                    else:
                        siaran_list = mux_details.get("siaran", [])

                    for tv in siaran_list:
                        st.write(f"- {tv}")
                    
                    if st.session_state.login:
                        handle_edit_delete_actions(selected_provinsi, selected_wilayah, mux_key, mux_details, selected_mux_filter)
                    else:
                        if isinstance(mux_details, dict):
                            last_updated_by_name = mux_details.get("last_updated_by_name", "N/A")
                            last_updated_date = mux_details.get("last_updated_date", "N/A")
                            last_updated_time = mux_details.get("last_updated_time", "N/A")
                            st.markdown(f"<p style='font-size: small; color: grey;'>Diperbarui oleh: <b>{last_updated_by_name}</b> pada {last_updated_date} pukul {last_updated_time}</p>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<p style='font-size: small; color: grey;'>Diperbarui oleh: <b>Belum Diperbarui</b> pada N/A pukul N/A</p>", unsafe_allow_html=True)
                    display_comments_section(selected_provinsi, selected_wilayah, mux_key)
                    st.markdown("---")

            else: # Specific MUX selected
                mux_details = mux_data.get(selected_mux_filter, {})
                if isinstance(mux_details, list):
                    siaran_list = mux_details
                else:
                    siaran_list = mux_details.get("siaran", [])

                if siaran_list:
                    st.subheader(f"📡 {selected_mux_filter}")
                    for tv in siaran_list:
                        st.write(f"- {tv}")
                    
                    if st.session_state.login:
                        handle_edit_delete_actions(selected_provinsi, selected_wilayah, selected_mux_filter, mux_details, selected_mux_filter)
                    else:
                        if isinstance(mux_details, dict):
                            last_updated_by_name = mux_details.get("last_updated_by_name", "N/A")
                            last_updated_date = mux_details.get("last_updated_date", "N/A")
                            last_updated_time = mux_details.get("last_updated_time", "N/A")
                            st.markdown(f"<p style='font-size: small; color: grey;'>Diperbarui oleh: <b>{last_updated_by_name}</b> pada {last_updated_date} pukul {last_updated_time}</p>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<p style='font-size: small; color: grey;'>Diperbarui oleh: <b>Belum Diperbarui</b> pada N/A pukul N/A</p>", unsafe_allow_html=True)
                    display_comments_section(selected_provinsi, selected_wilayah, selected_mux_filter)
                    st.markdown("---")
                else:
                    st.info("Tidak ada data siaran untuk MUX ini.")

        else:
            st.info("Belum ada data siaran untuk provinsi ini.")
    else:
        st.warning("Gagal memuat data provinsi.")

    if st.session_state.login:
        display_add_data_form()
    else:
        st.info("Untuk menambahkan, memperbarui, atau menghapus data, silakan login terlebih dahulu.")
        if st.button("🔐 Login / Daftar Akun"):
            switch_page("login")
            st.rerun()

elif st.session_state.halaman == "login":
    users_ref = db.reference("users")
    users = users_ref.get() or {}

    if st.session_state.mode == "Daftar Akun":
        st.session_state.lupa_password = False
    
    if not st.session_state.lupa_password:
        st.session_state.mode = st.selectbox(
            "Pilih Aksi", ["Login", "Daftar Akun"], key="login_reg_select"
        )

    if st.session_state.lupa_password:
        display_forgot_password_form(users)
    elif st.session_state.mode == "Login":
        display_login_form(users)
    else: # Daftar Akun
        display_registration_form(users)

    if st.button("⬅️ Kembali ke Beranda"):
        switch_page("beranda")
        st.rerun()

elif st.session_state.halaman == "edit_data":
    if not st.session_state.login:
        st.warning("Anda harus login untuk mengakses halaman ini.")
        switch_page("login")
    else:
        display_edit_data_page()

elif st.session_state.halaman == "profile":
    display_profile_page()

elif st.session_state.halaman == "other_users":
    display_other_users_page()

elif st.session_state.halaman == "leaderboard":
    display_leaderboard_page()

elif st.session_state.halaman == "chatbot": # <-- TAMBAHKAN ROUTING INI
    display_chatbot_page()
