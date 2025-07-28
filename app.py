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
import google.generativeai as genai

# --- DEFINISI FUNGSI SWITCH_PAGE SENDIRI ---
def switch_page(page_name):
    """Mengubah halaman aplikasi Streamlit."""
    st.session_state.halaman = page_name
    st.rerun()
# --- AKHIR DEFINISI FUNGSI SWITCH_PAGE SENDIRI ---

# --- KONFIGURASI DAN INISIALISASI ---

st.set_page_config(page_title="KTVDI", page_icon="🇮🇩")

def initialize_firebase():
    """Menginisialisasi koneksi ke Firebase Realtime Database."""
    if not firebase_admin._apps:
        try:
            cred_dict = dict(st.secrets["FIREBASE"])
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred, {
                "databaseURL": "https://website-ktvdi-default-rtdb.firebaseio.com/" # PASTIKAN INI URL DATABASE ANDA
            })
        except Exception as e:
            st.error(f"Gagal terhubung ke Firebase: {e}")
            st.stop()

# Inisialisasi Gemini API (tempatkan setelah inisialisasi Firebase)
GEMINI_MODEL = None
try:
    if "GOOGLE_API" in st.secrets and "API_KEY" in st.secrets["GOOGLE_API"]:
        genai.configure(api_key=st.secrets["GOOGLE_API"]["API_KEY"])
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
        "chat_history": [] # Menyimpan riwayat obrolan chatbot
    }
    for key, value in states.items():
        if key not in st.session_state:
            st.session_state[key] = value

# Inisialisasi awal
initialize_firebase()
initialize_session_state()
WIB = timezone("Asia/Jakarta")

# --- FUNGSI HELPER ---

def hash_password(password):
    """Menghash password menggunakan SHA256."""
    return hashlib.sha256(password.encode()).hexdigest()

def generate_otp():
    """Menghasilkan OTP 6 digit."""
    return str(random.randint(100000, 999999))

def send_otp_email(to_email, otp_code, purpose="daftar"):
    """Mengirim OTP ke email pengguna."""
    sender_email = st.secrets["EMAIL_SETTINGS"]["SENDER_EMAIL"]
    sender_password = st.secrets["EMAIL_SETTINGS"]["SENDER_PASSWORD"]
    smtp_server = st.secrets["EMAIL_SETTINGS"]["SMTP_SERVER"]
    smtp_port = st.secrets["EMAIL_SETTINGS"]["SMTP_PORT"]

    subject = f"Kode OTP untuk {purpose.capitalize()} Akun KTVDI Anda"
    body = f"""
    Halo,

    Kode OTP Anda untuk {purpose} akun KTVDI adalah:
    {otp_code}

    Kode ini berlaku untuk waktu yang terbatas. Jangan berikan kode ini kepada siapapun.

    Terima kasih,
    Tim KTVDI
    """

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = to_email

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        return True
    except Exception as e:
        st.error(f"Gagal mengirim email: {e}")
        return False

def proses_logout():
    """Meriset session state untuk logout."""
    st.session_state.login = False
    st.session_state.username = ""
    st.session_state.halaman = "beranda" # Kembali ke beranda setelah logout
    st.session_state.login_error = "" # Bersihkan pesan error
    st.session_state.login_attempted = False
    st.session_state.lupa_password = False
    st.session_state.otp_sent = False
    st.session_state.otp_code = ""
    st.session_state.reset_username = ""
    st.session_state.otp_sent_daftar = False
    st.session_state.otp_code_daftar = ""
    st.session_state.edit_mode = False
    st.session_state.edit_data = None
    st.session_state.selected_other_user = None
    st.session_state.comment_success_message = ""
    st.session_state.chat_history = [] # Bersihkan riwayat chat
    if "chat_session" in st.session_state:
        del st.session_state.chat_session # Hapus sesi chat
    st.rerun()

# --- FUNGSI TAMPILAN HALAMAN ---

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
        if st.sidebar.button("🤖 Chatbot KTVDI"):
            switch_page("chatbot")
            st.rerun()
        st.sidebar.button("🚪 Logout", on_click=proses_logout)

def display_login_form(users):
    """Menampilkan form login."""
    st.header("Login Akun")
    username = st.text_input("Username", key="login_user")
    password = st.text_input("Password", type="password", key="login_pass")

    if st.button("Login"):
        st.session_state.login_attempted = True
        if username in users and users[username]["password"] == hash_password(password):
            st.session_state.login = True
            st.session_state.username = username
            st.session_state.halaman = "beranda"
            st.session_state.login_error = ""
            st.success("Login berhasil!")
            time.sleep(1)
            st.rerun()
        else:
            st.session_state.login_error = "Username atau password salah."
            st.error(st.session_state.login_error)
    
    st.markdown("---")
    if st.button("Lupa Password?", key="forgot_password_btn"):
        st.session_state.lupa_password = True
        st.rerun()

def display_forgot_password_form(users):
    """Menampilkan form untuk proses lupa password."""
    st.header("🔑 Reset Password")

    if not st.session_state.otp_sent:
        reset_email = st.text_input("Email Terdaftar", key="reset_email")

        if st.button("Kirim OTP ke Email"):
            if not reset_email:
                st.toast("Email tidak boleh kosong.")
                return

            found_username = None
            user_data = None
            for user_key, data in users.items():
                if data.get("email", "").strip().lower() == reset_email.strip().lower():
                    found_username = user_key
                    user_data = data
                    break

            if not found_username:
                st.toast("❌ Email tidak ditemukan atau tidak terdaftar.")
            else:
                otp = generate_otp()
                if send_otp_email(user_data["email"], otp, purpose="reset"):
                    st.session_state.otp_code = otp
                    st.session_state.reset_username = found_username
                    st.session_state.otp_sent = True
                    st.success(f"OTP berhasil dikirim ke {user_data['email']}.")
                    st.info(f"Username Anda adalah: **{found_username}**") # Tampilkan username
                    time.sleep(2)
                    st.rerun()

    else:
        st.info(f"Kode OTP dikirim ke email Anda. Username Anda adalah: **{st.session_state.reset_username}**")
        
        input_otp = st.text_input("Masukkan Kode OTP", key="reset_otp")
        new_pw = st.text_input("Password Baru", type="password", key="reset_new_pw")

        if st.button("Reset Password"):
            if input_otp != st.session_state.otp_code:
                st.toast("❌ Kode OTP salah.")
            elif len(new_pw) < 6:
                st.toast("Password minimal 6 karakter.")
            else:
                username = st.session_state.reset_username
                hashed_new_pw = hash_password(new_pw)
                db.reference("users").child(username).update({"password": hashed_new_pw})
                st.success("Password berhasil direset. Silakan login kembali.")
                
                st.session_state.lupa_password = False
                st.session_state.otp_sent = False
                st.session_state.reset_username = ""
                st.session_state.otp_code = ""
                time.sleep(2)
                st.rerun()

    if st.button("❌ Batalkan"):
        st.session_state.lupa_password = False
        st.session_state.otp_sent = False
        st.session_state.reset_username = ""
        st.session_state.otp_code = ""
        st.rerun()

def display_registration_form(users):
    """Menampilkan form pendaftaran akun baru."""
    st.header("Daftar Akun Baru")
    new_username = st.text_input("Username", key="reg_user")
    new_password = st.text_input("Password", type="password", key="reg_pass")
    confirm_password = st.text_input("Konfirmasi Password", type="password", key="reg_confirm_pass")
    nama_lengkap = st.text_input("Nama Lengkap", key="reg_nama")
    email_reg = st.text_input("Email", key="reg_email")

    if not st.session_state.otp_sent_daftar:
        if st.button("Daftar"):
            if not new_username or not new_password or not confirm_password or not nama_lengkap or not email_reg:
                st.warning("Semua kolom harus diisi.")
            elif new_username in users:
                st.error("Username sudah terdaftar. Gunakan username lain.")
            elif new_password != confirm_password:
                st.error("Password dan konfirmasi password tidak cocok.")
            elif len(new_password) < 6:
                st.warning("Password minimal 6 karakter.")
            elif not re.match(r"[^@]+@[^@]+\.[^@]+", email_reg):
                st.error("Format email tidak valid.")
            elif any(data.get("email", "").strip().lower() == email_reg.strip().lower() for data in users.values()):
                st.error("Email sudah terdaftar dengan akun lain.")
            else:
                otp = generate_otp()
                if send_otp_email(email_reg, otp, purpose="verifikasi"):
                    st.session_state.otp_code_daftar = otp
                    st.session_state.new_user_data = {
                        "username": new_username,
                        "password": hash_password(new_password),
                        "nama": nama_lengkap,
                        "email": email_reg,
                        "points": 0
                    }
                    st.session_state.otp_sent_daftar = True
                    st.success("Kode OTP telah dikirim ke email Anda.")
                    time.sleep(2)
                    st.rerun()
    else:
        input_otp_daftar = st.text_input("Masukkan Kode OTP Verifikasi", key="reg_otp_input")
        if st.button("Verifikasi & Daftar"):
            if input_otp_daftar == st.session_state.otp_code_daftar:
                new_user_data = st.session_state.new_user_data
                users_ref = db.reference("users")
                users_ref.child(new_user_data["username"]).set(new_user_data)
                st.success("Akun berhasil didaftarkan! Silakan login.")
                st.session_state.otp_sent_daftar = False
                st.session_state.otp_code_daftar = ""
                st.session_state.new_user_data = {}
                st.session_state.mode = "Login" # Kembali ke form login
                time.sleep(2)
                st.rerun()
            else:
                st.error("Kode OTP salah. Silakan coba lagi.")
        if st.button("Batalkan Pendaftaran"):
            st.session_state.otp_sent_daftar = False
            st.session_state.otp_code_daftar = ""
            st.session_state.new_user_data = {}
            st.rerun()

def display_add_data_form():
    """Menampilkan form untuk menambahkan data MUX baru."""
    st.subheader("➕ Tambah Data MUX Baru")
    
    with st.form(key="add_data_form", clear_on_submit=True):
        new_provinsi = st.text_input("Nama Provinsi (misal: Jawa Barat)", key="add_provinsi").strip()
        new_wilayah = st.text_input("Nama Wilayah Layanan (misal: Jawa Barat-1)", key="add_wilayah").strip()
        new_mux_key = st.text_input("Nama Penyelenggara MUX (misal: TVRI)", key="add_mux_key").strip()
        new_siaran_list_raw = st.text_area("Daftar Siaran (pisahkan dengan koma atau baris baru)", key="add_siaran_list")

        submit_add = st.form_submit_button("Tambah Data")

        if submit_add:
            if not new_provinsi or not new_wilayah or not new_mux_key or not new_siaran_list_raw:
                st.warning("Semua kolom harus diisi.")
                return

            # Sanitasi input
            new_provinsi_clean = new_provinsi.title() # Capitalize first letter of each word
            new_wilayah_clean = new_wilayah.title()
            new_mux_key_clean = new_mux_key.upper() # MUX names typically uppercase

            siaran_list = [s.strip() for s in re.split(r'[,;\n]', new_siaran_list_raw) if s.strip()]

            siaran_ref = db.reference(f"siaran/{new_provinsi_clean}/{new_wilayah_clean}/{new_mux_key_clean}")
            existing_data = siaran_ref.get()

            now_wib = datetime.now(WIB)
            current_date = now_wib.strftime("%Y-%m-%d")
            current_time = now_wib.strftime("%H:%M:%S WIB")

            user_data = db.reference(f"users/{st.session_state.username}").get()
            updater_name = user_data.get("nama", st.session_state.username)

            if existing_data:
                st.warning("Data MUX ini sudah ada. Jika ingin mengubahnya, silakan gunakan fitur edit.")
            else:
                data_to_save = {
                    "siaran": siaran_list,
                    "last_updated_by_username": st.session_state.username,
                    "last_updated_by_name": updater_name,
                    "last_updated_date": current_date,
                    "last_updated_time": current_time
                }
                siaran_ref.set(data_to_save)
                
                # Tambah poin kontributor
                users_ref = db.reference(f"users/{st.session_state.username}")
                current_points = users_ref.child("points").get() or 0
                users_ref.update({"points": current_points + 10})
                
                # Update timestamp leaderboard
                db.reference("app_metadata/last_leaderboard_update_timestamp").set(now_wib.strftime("%Y-%m-%d %H:%M:%S"))

                # Perbarui daftar provinsi jika ada yang baru
                provinsi_ref = db.reference("provinsi")
                existing_provinsi = provinsi_ref.get() or []
                if new_provinsi_clean not in existing_provinsi:
                    existing_provinsi.append(new_provinsi_clean)
                    provinsi_ref.set(sorted(existing_provinsi))

                st.success("Data MUX berhasil ditambahkan!")
                time.sleep(1)
                st.rerun()

def handle_edit_delete_actions(provinsi, wilayah, mux_key, mux_details, selected_mux_filter):
    """Menangani tombol edit dan delete untuk setiap MUX."""
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button(f"✏️ Edit", key=f"edit_btn_{provinsi}_{wilayah}_{mux_key}"):
            st.session_state.edit_mode = True
            st.session_state.edit_data = {
                "provinsi": provinsi,
                "wilayah": wilayah,
                "mux_key": mux_key,
                "siaran": mux_details.get("siaran", []) if isinstance(mux_details, dict) else mux_details, # Handle old list format
                "last_updated_by_username": mux_details.get("last_updated_by_username", "N/A"),
                "last_updated_by_name": mux_details.get("last_updated_by_name", "N/A"),
                "last_updated_date": mux_details.get("last_updated_date", "N/A"),
                "last_updated_time": mux_details.get("last_updated_time", "N/A"),
            }
            switch_page("edit_data")
            st.rerun()
    with col2:
        if st.button(f"🗑️ Hapus", key=f"delete_btn_{provinsi}_{wilayah}_{mux_key}"):
            if st.session_state.login:
                if st.session_state.username == mux_details.get("last_updated_by_username") or st.session_state.username == "admin":
                    if st.warning(f"Anda yakin ingin menghapus MUX {mux_key} di {wilayah}, {provinsi}?"):
                        siaran_ref = db.reference(f"siaran/{provinsi}/{wilayah}/{mux_key}")
                        siaran_ref.set(None) # Menghapus MUX
                        
                        # Kurangi poin (opsional, jika ingin mengimplementasikan pengurangan poin)
                        # users_ref = db.reference(f"users/{st.session_state.username}")
                        # current_points = users_ref.child("points").get() or 0
                        # users_ref.update({"points": max(0, current_points - 10)})

                        st.success("Data MUX berhasil dihapus.")
                        st.rerun()
                else:
                    st.warning("Anda hanya bisa menghapus data yang Anda tambahkan sendiri atau sebagai admin.")
            else:
                st.warning("Silakan login untuk menghapus data.")

    # Tampilkan informasi updater
    if isinstance(mux_details, dict):
        last_updated_by_name = mux_details.get("last_updated_by_name", "N/A")
        last_updated_date = mux_details.get("last_updated_date", "N/A")
        last_updated_time = mux_details.get("last_updated_time", "N/A")
        st.markdown(f"<p style='font-size: small; color: grey;'>Diperbarui oleh: <b>{last_updated_by_name}</b> pada {last_updated_date} pukul {last_updated_time}</p>", unsafe_allow_html=True)
    else:
        st.markdown(f"<p style='font-size: small; color: grey;'>Diperbarui oleh: <b>Belum Diperbarui</b> pada N/A pukul N/A</p>", unsafe_allow_html=True)


def display_edit_data_page():
    """Menampilkan form untuk mengedit data MUX."""
    st.header("✏️ Edit Data MUX")
    
    if st.session_state.edit_data:
        data = st.session_state.edit_data
        st.write(f"Mengedit data untuk: **{data['mux_key']}** di **{data['wilayah']}**, **{data['provinsi']}**")

        with st.form(key="edit_data_form", clear_on_submit=False):
            # Tampilkan provinsi, wilayah, mux_key sebagai readonly
            st.text_input("Provinsi", value=data["provinsi"], disabled=True)
            st.text_input("Wilayah Layanan", value=data["wilayah"], disabled=True)
            st.text_input("Penyelenggara MUX", value=data["mux_key"], disabled=True)
            
            # Form untuk mengedit daftar siaran
            current_siaran_str = "\n".join(data["siaran"])
            edited_siaran_list_raw = st.text_area("Daftar Siaran (pisahkan dengan baris baru)", value=current_siaran_str, key="edit_siaran_list")

            col1, col2 = st.columns(2)
            with col1:
                submit_edit = st.form_submit_button("Simpan Perubahan")
            with col2:
                cancel_edit = st.form_submit_button("Batalkan")

            if submit_edit:
                edited_siaran_list = [s.strip() for s in re.split(r'[\n]', edited_siaran_list_raw) if s.strip()]
                
                now_wib = datetime.now(WIB)
                current_date = now_wib.strftime("%Y-%m-%d")
                current_time = now_wib.strftime("%H:%M:%S WIB")

                user_data = db.reference(f"users/{st.session_state.username}").get()
                updater_name = user_data.get("nama", st.session_state.username)

                updates = {
                    "siaran": edited_siaran_list,
                    "last_updated_by_username": st.session_state.username,
                    "last_updated_by_name": updater_name,
                    "last_updated_date": current_date,
                    "last_updated_time": current_time
                }
                
                siaran_ref = db.reference(f"siaran/{data['provinsi']}/{data['wilayah']}/{data['mux_key']}")
                siaran_ref.update(updates)
                
                # Tambah poin kontributor untuk edit
                users_ref = db.reference(f"users/{st.session_state.username}")
                current_points = users_ref.child("points").get() or 0
                users_ref.update({"points": current_points + 5})

                # Update timestamp leaderboard
                db.reference("app_metadata/last_leaderboard_update_timestamp").set(now_wib.strftime("%Y-%m-%d %H:%M:%S"))
                
                st.success("Perubahan berhasil disimpan!")
                st.session_state.edit_mode = False
                st.session_state.edit_data = None
                time.sleep(1)
                switch_page("beranda")
                st.rerun()

            if cancel_edit:
                st.session_state.edit_mode = False
                st.session_state.edit_data = None
                switch_page("beranda")
                st.rerun()
    else:
        st.warning("Tidak ada data yang dipilih untuk diedit.")
        if st.button("⬅️ Kembali ke Beranda"):
            switch_page("beranda")
            st.rerun()

def display_profile_page():
    """Menampilkan halaman profil pengguna yang sedang login."""
    st.header(f"👤 Profil Saya")
    
    users_ref = db.reference("users")
    user_data = users_ref.child(st.session_state.username).get()

    if user_data:
        st.write(f"**Username:** {st.session_state.username}")
        st.write(f"**Nama Lengkap:** {user_data.get('nama', 'N/A')}")
        st.write(f"**Email:** {user_data.get('email', 'N/A')}")
        st.write(f"**Total Poin Kontribusi:** {user_data.get('points', 0)} ⭐")
    else:
        st.error("Data profil tidak ditemukan.")

    st.markdown("---")
    st.subheader("Riwayat Kontribusi Saya")
    
    siaran_ref = db.reference("siaran")
    all_siaran_data = siaran_ref.get() or {}
    
    user_contributions = []
    for provinsi_key, provinsi_data in all_siaran_data.items():
        if isinstance(provinsi_data, dict):
            for wilayah_key, wilayah_data in provinsi_data.items():
                if isinstance(wilayah_data, dict):
                    for mux_key, mux_details in wilayah_data.items():
                        if isinstance(mux_details, dict):
                            if mux_details.get("last_updated_by_username") == st.session_state.username:
                                user_contributions.append({
                                    "Provinsi": provinsi_key,
                                    "Wilayah": wilayah_key,
                                    "MUX": mux_key,
                                    "Terakhir Diperbarui": f"{mux_details.get('last_updated_date', 'N/A')} {mux_details.get('last_updated_time', 'N/A')}"
                                })

    if user_contributions:
        df_contributions = pd.DataFrame(user_contributions)
        st.dataframe(df_contributions, use_container_width=True)
    else:
        st.info("Anda belum berkontribusi data siaran.")

    st.markdown("---")
    if st.button("⬅️ Kembali ke Beranda"):
        switch_page("beranda")
        st.rerun()

def display_other_users_page():
    """Menampilkan daftar pengguna lain dan profil mereka."""
    st.header("👥 Profil Pengguna Lain")

    users_ref = db.reference("users")
    all_users_data = users_ref.get() or {}

    other_users_list = []
    for username, data in all_users_data.items():
        if username != st.session_state.username: # Jangan tampilkan diri sendiri
            other_users_list.append({
                "username": username,
                "nama": data.get("nama", username),
                "points": data.get("points", 0)
            })
    
    if other_users_list:
        selected_user_name = st.selectbox(
            "Pilih Pengguna untuk Dilihat Profilnya:",
            ["Pilih Pengguna"] + sorted([u["nama"] for u in other_users_list]),
            key="select_other_user_profile"
        )

        if selected_user_name != "Pilih Pengguna":
            selected_user_data = next((u for u in other_users_list if u["nama"] == selected_user_name), None)
            if selected_user_data:
                st.session_state.selected_other_user = selected_user_data["username"]
                st.subheader(f"Profil {selected_user_data['nama']}")
                st.write(f"**Username:** {selected_user_data['username']}")
                st.write(f"**Nama Lengkap:** {selected_user_data['nama']}")
                st.write(f"**Total Poin Kontribusi:** {selected_user_data['points']} ⭐")
                
                st.markdown("---")
                st.subheader("Riwayat Kontribusi Pengguna Ini")
                
                siaran_ref = db.reference("siaran")
                all_siaran_data = siaran_ref.get() or {}
                
                user_contributions = []
                for provinsi_key, provinsi_data in all_siaran_data.items():
                    if isinstance(provinsi_data, dict):
                        for wilayah_key, wilayah_data in provinsi_data.items():
                            if isinstance(wilayah_data, dict):
                                for mux_key, mux_details in wilayah_data.items():
                                    if isinstance(mux_details, dict):
                                        if mux_details.get("last_updated_by_username") == selected_user_data["username"]:
                                            user_contributions.append({
                                                "Provinsi": provinsi_key,
                                                "Wilayah": wilayah_key,
                                                "MUX": mux_key,
                                                "Terakhir Diperbarui": f"{mux_details.get('last_updated_date', 'N/A')} {mux_details.get('last_updated_time', 'N/A')}"
                                            })
                
                if user_contributions:
                    df_contributions = pd.DataFrame(user_contributions)
                    st.dataframe(df_contributions, use_container_width=True)
                else:
                    st.info("Pengguna ini belum berkontribusi data siaran.")
            else:
                st.info("Pilih pengguna dari daftar di atas.")
    else:
        st.info("Belum ada pengguna lain yang terdaftar selain Anda.")

    st.markdown("---")
    if st.button("⬅️ Kembali ke Beranda"):
        st.session_state.selected_other_user = None
        switch_page("beranda")
        st.rerun()

# --- FUNGSI ANALISIS SENTIMEN (AI) ---
def get_comment_sentiment(comment_text):
    """Menggunakan Gemini API untuk menganalisis sentimen komentar."""
    if not GEMINI_MODEL:
        return "N/A (AI tidak aktif)" 

    try:
        prompt = f"Analisasi sentimen dari teks berikut: '{comment_text}'. Balas hanya dengan 'Positif', 'Negatif', atau 'Netral'. Jika tidak jelas, balas 'Tidak Tentu'."
        response = GEMINI_MODEL.generate_content(prompt)
        sentiment = response.text.strip()
        
        if sentiment in ["Positif", "Negatif", "Netral", "Tidak Tentu"]:
            return sentiment
        else:
            return "N/A (Respon AI tidak valid)" 
    except Exception as e:
        # st.error(f"Error saat memanggil Gemini API untuk sentimen: {e}") # Debugging
        return "Error AI"

def display_comments_section(provinsi, wilayah, mux_key):
    """
    Menampilkan bagian komentar untuk MUX tertentu dan memungkinkan pengguna menambah komentar.
    """
    st.markdown("---")
    st.subheader("💬 Komentar Pengguna")

    comments_ref = db.reference(f"siaran/{provinsi}/{wilayah}/{mux_key}/comments")
    comments_data = comments_ref.get() or {}

    comments_list = []
    for comment_id, comment_details in comments_data.items():
        comments_list.append({
            "id": comment_id,
            "username": comment_details.get("username", "Anonim"),
            "nama_pengguna": comment_details.get("nama_pengguna", "Anonim"),
            "timestamp": comment_details.get("timestamp", "N/A"),
            "text": comment_details.get("text", "")
        })
    
    comments_list.sort(key=lambda x: x["timestamp"], reverse=True)

    if st.session_state.comment_success_message:
        st.success(st.session_state.comment_success_message)
        st.session_state.comment_success_message = ""

    if st.session_state.login:
        with st.form(key=f"comment_form_{provinsi}_{wilayah}_{mux_key}", clear_on_submit=True):
            new_comment_text = st.text_area("Tulis komentar Anda:", key=f"comment_text_{provinsi}_{wilayah}_{mux_key}")
            submit_comment = st.form_submit_button("Kirim Komentar")

            if submit_comment:
                if new_comment_text.strip():
                    try:
                        current_username = st.session_state.username
                        user_data = db.reference(f"users/{current_username}").get()
                        current_user_name = user_data.get("nama", current_username)
                        
                        now_wib = datetime.now(WIB)
                        comment_timestamp = now_wib.strftime("%Y-%m-%d %H:%M:%S WIB")

                        comment_data = {
                            "username": current_username,
                            "nama_pengguna": current_user_name,
                            "timestamp": comment_timestamp,
                            "text": new_comment_text.strip()
                        }
                        
                        comments_ref.push().set(comment_data)
                        
                        user_ref = db.reference(f"users/{current_username}")
                        current_points = user_ref.child("points").get() or 0
                        user_ref.update({"points": current_points + 1})
                        
                        # Update timestamp leaderboard
                        db.reference("app_metadata/last_leaderboard_update_timestamp").set(now_wib.strftime("%Y-%m-%d %H:%M:%S"))

                        st.session_state.comment_success_message = "Komentar berhasil dikirim dan Anda mendapatkan 1 poin!"
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal mengirim komentar: {e}")
                else:
                    st.warning("Komentar tidak boleh kosong.")
    else: # Jika belum login
        if not comments_list: # Jika belum login DAN belum ada komentar
            st.info("Login untuk dapat menulis komentar. Belum ada komentar untuk MUX ini.")
        else: # Jika belum login TAPI sudah ada komentar
            st.info("Login untuk dapat menulis komentar.")

    st.markdown("---")
    if comments_list:
        st.write("### Komentar Sebelumnya:")
        for comment in comments_list:
            sentiment = get_comment_sentiment(comment['text']) 
            st.markdown(f"**{comment['nama_pengguna']}** ({comment['timestamp']}) - Sentimen: **{sentiment}**:")
            st.write(comment['text'])
            st.markdown("---")

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

# --- FUNGSI BACKFILL OTOMATIS (TANPA TOMBOL ADMIN) ---
# Hapus fungsi ini setelah Anda yakin proses backfill sudah selesai
def backfill_contributor_points_integrated_auto():
    """
    Fungsi ini akan menghitung ulang dan memperbarui poin kontributor
    berdasarkan data siaran yang sudah ada. Akan berjalan secara otomatis
    jika flag di database belum diatur.
    """
    backfill_flag_ref = db.reference("app_settings/backfill_points_completed")
    backfill_completed = backfill_flag_ref.get()

    if backfill_completed:
        return

    st.warning("Mendeteksi backfill poin kontributor belum selesai. Memulai proses otomatis...")
    st.info("Proses ini hanya akan berjalan sekali untuk menginisialisasi poin kontributor lama.")

    siaran_ref = db.reference("siaran")
    all_siaran_data = siaran_ref.get()

    if not all_siaran_data:
        st.info("Tidak ada data siaran ditemukan di database untuk backfill. Menandai backfill selesai.")
        backfill_flag_ref.set(True) 
        st.rerun()
        return

    users_ref = db.reference("users")
    all_users_data = users_ref.get() or {}

    with st.spinner("Mereset poin semua pengguna..."):
        for username, user_data in all_users_data.items():
            if user_data.get("points") != 0:
                users_ref.child(username).update({"points": 0})
        st.success("Semua poin pengguna telah direset menjadi 0 sebelum perhitungan ulang.")
        time.sleep(1)

    calculated_points = {username: 0 for username in all_users_data.keys()}
    processed_mux_entries = {}

    POINTS_FOR_NEW_DATA = 10 

    total_entries_processed = 0
    st.info("Menghitung poin berdasarkan kontribusi data siaran...")

    with st.spinner("Menganalisis data siaran..."):
        for provinsi_key, provinsi_data in all_siaran_data.items():
            if not isinstance(provinsi_data, dict):
                continue

            for wilayah_key, wilayah_data in provinsi_data.items():
                if not isinstance(wilayah_data, dict):
                    continue

                for mux_key, mux_details in wilayah_data.items():
                    total_entries_processed += 1
                    if isinstance(mux_details, dict):
                        updater_username = mux_details.get("last_updated_by_username")
                        
                        if updater_username and updater_username in all_users_data:
                            if updater_username not in processed_mux_entries:
                                processed_mux_entries[updater_username] = set()
                            
                            current_entry_identifier = (provinsi_key, wilayah_key, mux_key)

                            if current_entry_identifier not in processed_mux_entries[updater_username]:
                                calculated_points[updater_username] += POINTS_FOR_NEW_DATA
                                processed_mux_entries[updater_username].add(current_entry_identifier)
        
    st.info(f"Total {total_entries_processed} entri siaran diproses.")
    st.info("Memperbarui poin pengguna di database Firebase...")

    with st.spinner("Mengupdate poin di database..."):
        for username, points in calculated_points.items():
            if points > 0:
                users_ref.child(username).update({"points": points})
                st.write(f"✅ {username}: Total **{points}** poin diperbarui.")
            else:
                st.write(f"➖ {username}: Tidak ada poin kontribusi data siaran (atau sudah 0).")

    st.success("Proses backfill poin selesai! Poin Anda akan segera diperbarui.")
    
    backfill_flag_ref.set(True)
    # Update timestamp leaderboard setelah backfill
    db.reference("app_metadata/last_leaderboard_update_timestamp").set(datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S"))
    
    time.sleep(2)
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

    if "chat_session" not in st.session_state:
        st.session_state.chat_session = GEMINI_MODEL.start_chat(history=[])

    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("Tanyakan sesuatu..."):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Mengetik..."):
                try:
                    system_instruction = (
                        "Anda adalah asisten virtual yang ahli dalam hal TV Digital di Indonesia. "
                        "Jawablah pertanyaan pengguna dengan jelas, informatif, dan ringkas. "
                        "Fokus pada topik seperti siaran TV digital, perangkat (TV, STB, antena), "
                        "wilayah layanan, troubleshooting dasar, dan hal-hal terkait TV digital di Indonesia. "
                        "Jika pertanyaan di luar topik, mohon sampaikan bahwa Anda hanya dapat membantu terkait TV Digital."
                    )
                    
                    gemini_history = []
                    for msg in st.session_state.chat_history[:-1]:
                        gemini_history.append({'role': msg['role'], 'parts': [{'text': msg['content']}]})
                    
                    gemini_history.append({'role': 'user', 'parts': [{'text': prompt}]})
                    
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
        st.rerun()

    st.markdown("---")
    if st.button("⬅️ Kembali ke Beranda"):
        switch_page("beranda")
        st.rerun()

# --- ROUTING HALAMAN UTAMA APLIKASI ---

# Panggil fungsi backfill poin secara otomatis di awal
backfill_contributor_points_integrated_auto() # Hapus baris ini jika Anda sudah selesai dengan backfill!

st.title("🇮🇩 KOMUNITAS TV DIGITAL INDONESIA 🇮🇩")
display_sidebar()

if st.session_state.halaman == "beranda":
    st.header("📺 Data Siaran TV Digital di Indonesia")
    
    provinsi_data = db.reference("provinsi").get()
    
    if provinsi_data:
        provinsi_list = sorted(provinsi_data.values())
        selected_provinsi = st.selectbox("Pilih Provinsi", provinsi_list, key="select_provinsi")
        
        siaran_data_prov = db.reference(f"siaran/{selected_provinsi}").get()
        if siaran_data_prov:
            # Filter out non-dictionary items if any old data format exists at this level
            filtered_wilayah_data = {k: v for k, v in siaran_data_prov.items() if isinstance(v, dict)}
            wilayah_list = sorted(filtered_wilayah_data.keys())
            
            if wilayah_list:
                selected_wilayah = st.selectbox("Pilih Wilayah Layanan", wilayah_list, key="select_wilayah")
                
                mux_data = filtered_wilayah_data[selected_wilayah]
                mux_list = sorted(mux_data.keys())
                
                selected_mux_filter = st.selectbox("Pilih Penyelenggara MUX", ["Semua MUX"] + mux_list, key="select_mux_filter")

                if selected_mux_filter == "Semua MUX":
                    for mux_key, mux_details in mux_data.items():
                        st.subheader(f"📡 {mux_key}")
                        if isinstance(mux_details, dict):
                            siaran_list = mux_details.get("siaran", [])
                        else: # Handle old list format
                            siaran_list = mux_details

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
                    if isinstance(mux_details, dict):
                        siaran_list = mux_details.get("siaran", [])
                    else:
                        siaran_list = mux_details

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
                st.info("Belum ada data wilayah layanan untuk provinsi ini.")
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

elif st.session_state.halaman == "chatbot":
    display_chatbot_page()