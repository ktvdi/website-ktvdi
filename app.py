import streamlit as st
import firebase_admin
import hashlib
import smtplib
import random
import time
import re
import pandas as pd
import google.generativeai as genai
from email.mime.text import MIMEText
from firebase_admin import credentials, db
from pytz import timezone
from datetime import datetime

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

def initialize_gemini():
    """Menginisialisasi koneksi ke Gemini API."""
    try:
        genai.configure(api_key=st.secrets["GEMINI"]["api_key"])
    except KeyError:
        st.error("Kunci API Gemini tidak ditemukan di Streamlit Secrets. Pastikan Anda telah menambahkannya.")
        st.stop()
    except Exception as e:
        st.error(f"Gagal menginisialisasi Gemini API: {e}")
        st.stop()

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
        "messages": [], # Untuk menyimpan riwayat chat chatbot
    }
    for key, value in states.items():
        if key not in st.session_state:
            st.session_state[key] = value

# Inisialisasi awal
initialize_firebase()
initialize_session_state()
initialize_gemini()
WIB = timezone("Asia/Jakarta")

# --- FUNGSI HELPER UMUM (DEFINED SEBELUM DIGUNAKAN) ---

def hash_password(password):
    """Menghash password menggunakan SHA256."""
    return hashlib.sha256(password.encode()).hexdigest()

def send_otp_email(email, otp_code):
    """Mengirim kode OTP ke email."""
    try:
        sender_email = st.secrets["EMAIL"]["address"]
        sender_password = st.secrets["EMAIL"]["password"] # App password, bukan password akun Google
        smtp_server = "smtp.gmail.com"
        smtp_port = 587

        msg = MIMEText(f"Kode OTP Anda adalah: {otp_code}\nKode ini berlaku selama 5 menit. Jangan bagikan kode ini kepada siapapun.")
        msg["Subject"] = "Kode OTP Reset Password KTVDI Anda"
        msg["From"] = sender_email
        msg["To"] = email

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, email, msg.as_string())
        st.success("Kode OTP telah dikirim ke email Anda.")
        return True
    except Exception as e:
        st.error(f"Gagal mengirim OTP. Pastikan email dan password pengirim benar, dan akses aplikasi pihak ketiga di akun Google Anda diizinkan: {e}")
        return False

def switch_page(page_name): # PENTING: Fungsi ini didefinisikan di sini
    """Mengganti halaman aplikasi."""
    st.session_state.halaman = page_name

def proses_logout():
    """Mengatur ulang session state untuk logout."""
    st.session_state.login = False
    st.session_state.username = ""
    st.session_state.halaman = "beranda"
    st.session_state.edit_mode = False
    st.session_state.edit_data = None
    st.session_state.selected_other_user = None
    st.session_state.comment_success_message = ""
    st.session_state.messages = [] # Reset riwayat chat saat logout
    st.rerun()

def get_provinsi_data():
    """Mengambil data provinsi dari Firebase."""
    try:
        return db.reference("provinsi").get()
    except Exception as e:
        st.error(f"Gagal mengambil data provinsi: {e}")
        return None

def get_wilayah_data(provinsi):
    """Mengambil data wilayah berdasarkan provinsi."""
    try:
        wilayah_ref = db.reference(f"wilayah/{provinsi}")
        return wilayah_ref.get()
    except Exception as e:
        st.error(f"Gagal mengambil data wilayah: {e}")
        return None

def get_mux_data(provinsi, wilayah):
    """Mengambil data MUX berdasarkan provinsi dan wilayah."""
    try:
        mux_ref = db.reference(f"mux/{provinsi}/{wilayah}")
        return mux_ref.get()
    except Exception as e:
        st.error(f"Gagal mengambil data MUX: {e}")
        return None

def get_comment_data(provinsi, wilayah, mux_key):
    """Mengambil data komentar untuk MUX tertentu."""
    try:
        comments_ref = db.reference(f"comments/{provinsi}/{wilayah}/{mux_key}").order_by_child("timestamp").get()
        if comments_ref:
            comments_list = []
            users_data = db.reference("users").get() or {}
            for comment_key, comment_data in comments_ref.items():
                if isinstance(comment_data, dict):
                    username = comment_data.get("username", "Anonim")
                    nama_pengguna = users_data.get(username, {}).get("nama", username)
                    comment_data["display_name"] = nama_pengguna
                    comments_list.append(comment_data)
            return comments_list
        return []
    except Exception as e:
        st.error(f"Gagal mengambil data komentar: {e}")
        return []

def add_user_points(username, points_to_add):
    """Menambahkan poin ke pengguna."""
    try:
        user_ref = db.reference(f"users/{username}")
        current_points = user_ref.child("points").get() or 0
        user_ref.child("points").set(current_points + points_to_add)
        if username == st.session_state.username:
            users_data = db.reference(f"users/{st.session_state.username}").get()
            if users_data:
                st.session_state.user_points = users_data.get("points", 0)
    except Exception as e:
        st.warning(f"Gagal menambahkan poin untuk {username}: {e}")

# --- FUNGSI TAMPILAN HALAMAN (DEFINED SEBELUM DIGUNAKAN DI ROUTING UTAMA) ---

def display_login_form(users):
    """Menampilkan form login."""
    st.subheader("Login ke Akun Anda")
    username_login = st.text_input("Username", key="username_login")
    password_login = st.text_input("Password", type="password", key="password_login")

    if st.button("Login", key="btn_login"):
        if username_login and password_login:
            st.session_state.login_attempted = True
            if username_login in users and users[username_login]["password"] == hash_password(password_login):
                st.session_state.login = True
                st.session_state.username = username_login
                st.session_state.halaman = "beranda"
                st.success("Login berhasil!")
                st.session_state.login_error = ""
                st.rerun()
            else:
                st.session_state.login_error = "Username atau password salah."
                st.error(st.session_state.login_error)
        else:
            st.session_state.login_error = "Harap isi username dan password."
            st.warning(st.session_state.login_error)
    
    if st.button("Lupa Password?", key="btn_lupa_password"):
        st.session_state.lupa_password = True
        st.rerun()

    if st.session_state.login_error and st.session_state.login_attempted:
        st.error(st.session_state.login_error)

def display_registration_form(users):
    """Menampilkan form pendaftaran akun."""
    st.subheader("Daftar Akun Baru")
    new_username = st.text_input("Username (unik)", key="new_username")
    new_email = st.text_input("Email", key="new_email")
    new_password = st.text_input("Password", type="password", key="new_password")
    confirm_password = st.text_input("Konfirmasi Password", type="password", key="confirm_password")
    nama_lengkap = st.text_input("Nama Lengkap", key="nama_lengkap_reg")
    provinsi_domisili = st.selectbox("Provinsi Domisili", ["Pilih Provinsi"] + list(get_provinsi_data().keys()), key="provinsi_reg")
    wilayah_domisili = st.text_input("Wilayah Domisili (contoh: Kota Surabaya, Kab. Bandung)", key="wilayah_domisili_reg")
    merk_tv_digital = st.text_input("Merk TV Digital/STB yang Digunakan (contoh: Polytron, Matrix Apple)", key="merk_tv_digital_reg")
    
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    is_valid_email = re.match(email_regex, new_email)

    if st.button("Daftar", key="btn_daftar"):
        if not new_username or not new_email or not new_password or not confirm_password or not nama_lengkap or provinsi_domisili == "Pilih Provinsi" or not wilayah_domisili or not merk_tv_digital:
            st.warning("Harap isi semua kolom!")
        elif new_username in users:
            st.warning("Username sudah terdaftar. Silakan pilih username lain.")
        elif not is_valid_email:
            st.warning("Format email tidak valid.")
        elif new_password != confirm_password:
            st.warning("Konfirmasi password tidak cocok.")
        else:
            hashed_password = hash_password(new_password)
            users_ref = db.reference("users")
            users_ref.child(new_username).set({
                "password": hashed_password,
                "email": new_email,
                "nama": nama_lengkap,
                "provinsi_domisili": provinsi_domisili,
                "wilayah_domisili": wilayah_domisili,
                "merk_tv_digital": merk_tv_digital,
                "points": 0,
                "created_at": datetime.now(WIB).isoformat()
            })
            st.success("Akun berhasil didaftarkan! Silakan login.")
            st.session_state.mode = "Login"
            st.rerun()

def display_forgot_password_form(users):
    """Menampilkan form lupa password."""
    st.subheader("Lupa Password?")
    reset_email = st.text_input("Masukkan Email Terdaftar", key="reset_email")

    user_found = False
    reset_username_val = ""
    for u_name, u_data in users.items():
        if u_data.get("email") == reset_email:
            user_found = True
            reset_username_val = u_name
            break

    if st.session_state.otp_sent:
        otp_input = st.text_input("Masukkan Kode OTP", key="otp_input")
        new_password_reset = st.text_input("Password Baru", type="password", key="new_password_reset")
        confirm_password_reset = st.text_input("Konfirmasi Password Baru", type="password", key="confirm_password_reset")

        if st.button("Reset Password", key="btn_reset_password"):
            if otp_input == st.session_state.otp_code:
                if new_password_reset == confirm_password_reset:
                    hashed_new_password = hash_password(new_password_reset)
                    db.reference(f"users/{st.session_state.reset_username}").update({"password": hashed_new_password})
                    st.success("Password berhasil direset! Silakan login.")
                    st.session_state.lupa_password = False
                    st.session_state.otp_sent = False
                    st.session_state.otp_code = ""
                    st.session_state.reset_username = ""
                    st.rerun()
                else:
                    st.warning("Konfirmasi password tidak cocok.")
            else:
                st.warning("Kode OTP salah.")
    else:
        if st.button("Kirim OTP", key="btn_send_otp"):
            if reset_email:
                if user_found:
                    st.session_state.otp_code = str(random.randint(100000, 999999))
                    st.session_state.reset_username = reset_username_val
                    if send_otp_email(reset_email, st.session_state.otp_code):
                        st.session_state.otp_sent = True
                        st.session_state.otp_expiry_time = time.time() + 300
                        st.success("Kode OTP telah dikirim. Cek email Anda.")
                        st.rerun()
                else:
                    st.error("Email tidak terdaftar.")
            else:
                st.warning("Harap masukkan email.")
    
    if st.button("⬅️ Kembali ke Login", key="btn_back_to_login_forgot"):
        st.session_state.lupa_password = False
        st.session_state.otp_sent = False
        st.session_state.otp_code = ""
        st.session_state.reset_username = ""
        st.rerun()

def display_add_data_form():
    """Menampilkan form penambahan data siaran."""
    st.subheader("Tambahkan Data Siaran Baru")

    provinsi_baru = st.selectbox(
        "Pilih Provinsi",
        ["Pilih Provinsi"] + list(get_provinsi_data().keys()),
        key="provinsi_add"
    )

    if provinsi_baru != "Pilih Provinsi":
        wilayah_layanan = st.text_input(
            "Wilayah Layanan (Contoh: Jakarta-1)",
            placeholder="Contoh: Jawa Timur-1, DKI Jakarta-2",
            key="wilayah_add"
        )
        penyelenggara_mux = st.text_input(
            "Penyelenggara MUX (Contoh: UHF 27 - Metro TV)",
            placeholder="Contoh: UHF 27 - Metro TV, UHF 31 - SCTV",
            key="mux_add"
        )
        st.info("Untuk Wilayah Layanan dan Penyelenggara MUX, pastikan formatnya konsisten agar data tidak duplikat.")

        st.subheader("Daftar Siaran")
        num_channels = st.number_input("Jumlah Saluran", min_value=1, value=1, key="num_channels")

        channels = []
        for i in range(int(num_channels)):
            col1, col2 = st.columns(2)
            with col1:
                channel_name = st.text_input(f"Nama Saluran {i+1}", key=f"channel_name_{i}")
            with col2:
                channel_status = st.selectbox(f"Status Saluran {i+1}", ["Aktif", "Tidak Aktif", "Belum Ada"], key=f"channel_status_{i}")
            if channel_name:
                channels.append({"nama": channel_name, "status": channel_status})

        catatan = st.text_area("Catatan Tambahan (Opsional)", key="catatan_add")

        if st.button("Simpan Data Siaran", key="btn_save_data"):
            if not wilayah_layanan or not penyelenggara_mux or not channels:
                st.warning("Harap isi Wilayah Layanan, Penyelenggara MUX, dan setidaknya satu Saluran.")
            elif any(not c["nama"] for c in channels):
                st.warning("Harap isi semua Nama Saluran yang ditambahkan.")
            else:
                try:
                    mux_data = {
                        "penyelenggara": penyelenggara_mux,
                        "siaran": channels,
                        "catatan": catatan,
                        "ditambahkan_oleh": st.session_state.username,
                        "timestamp": datetime.now(WIB).isoformat(),
                        "last_updated_by": st.session_state.username,
                        "last_updated_at": datetime.now(WIB).isoformat()
                    }

                    wilayah_ref = db.reference(f"wilayah/{provinsi_baru}/{wilayah_layanan}")
                    if not wilayah_ref.get():
                        wilayah_ref.set({"name": wilayah_layanan})

                    mux_id = penyelenggara_mux.replace('.', '_').replace('#', '_').replace('$', '_').replace('[', '_').replace(']', '_').replace('/', '_')
                    
                    mux_db_ref = db.reference(f"mux/{provinsi_baru}/{wilayah_layanan}/{mux_id}")
                    if mux_db_ref.get():
                        st.warning(f"Data MUX '{penyelenggara_mux}' di wilayah '{wilayah_layanan}' sudah ada. Silakan edit jika perlu.")
                    else:
                        mux_db_ref.set(mux_data)
                        add_user_points(st.session_state.username, 10)
                        st.success("Data siaran berhasil ditambahkan!")
                        st.experimental_rerun()

                except Exception as e:
                    st.error(f"Terjadi kesalahan saat menyimpan data: {e}")

def display_edit_data_form():
    """Menampilkan form untuk mengedit data siaran yang sudah ada."""
    st.subheader("Edit Data Siaran")

    if st.session_state.edit_data:
        provinsi_edit = st.session_state.edit_data["provinsi"]
        wilayah_edit = st.session_state.edit_data["wilayah"]
        mux_key_edit = st.session_state.edit_data["mux_key"]
        current_data = st.session_state.edit_data["data"]

        st.write(f"**Provinsi:** {provinsi_edit}")
        st.write(f"**Wilayah Layanan:** {wilayah_edit}")
        st.write(f"**Penyelenggara MUX:** {current_data['penyelenggara']}")
        st.write(f"**Ditambahkan oleh:** {current_data.get('ditambahkan_oleh', 'N/A')}")
        st.write(f"**Terakhir Diperbarui oleh:** {current_data.get('last_updated_by', 'N/A')}")
        st.write(f"**Terakhir Diperbarui pada:** {datetime.fromisoformat(current_data.get('last_updated_at', datetime.now(WIB).isoformat())).strftime('%d-%m-%Y %H:%M:%S')}")


        st.subheader("Edit Daftar Siaran")
        current_channels = current_data.get("siaran", [])
        num_current_channels = len(current_channels)

        new_num_channels = st.number_input("Jumlah Saluran", min_value=1, value=max(1, num_current_channels), key="edit_num_channels")

        edited_channels = []
        for i in range(int(new_num_channels)):
            col1, col2 = st.columns(2)
            default_name = current_channels[i]["nama"] if i < num_current_channels and "nama" in current_channels[i] else ""
            default_status = current_channels[i]["status"] if i < num_current_channels and "status" in current_channels[i] else "Aktif"

            with col1:
                channel_name = st.text_input(f"Nama Saluran {i+1}", value=default_name, key=f"edit_channel_name_{i}")
            with col2:
                channel_status = st.selectbox(f"Status Saluran {i+1}", ["Aktif", "Tidak Aktif", "Belum Ada"], index=["Aktif", "Tidak Aktif", "Belum Ada"].index(default_status) if default_status in ["Aktif", "Tidak Aktif", "Belum Ada"] else 0, key=f"edit_channel_status_{i}")
            
            if channel_name:
                edited_channels.append({"nama": channel_name, "status": channel_status})

        edited_catatan = st.text_area("Catatan Tambahan (Opsional)", value=current_data.get("catatan", ""), key="edit_catatan")

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("Simpan Perubahan", key="btn_save_edit"):
                if not edited_channels or any(not c["nama"] for c in edited_channels):
                    st.warning("Harap isi setidaknya satu Saluran dan semua Nama Saluran.")
                else:
                    try:
                        updated_mux_data = {
                            "siaran": edited_channels,
                            "catatan": edited_catatan,
                            "last_updated_by": st.session_state.username,
                            "last_updated_at": datetime.now(WIB).isoformat()
                        }
                        
                        db.reference(f"mux/{provinsi_edit}/{wilayah_edit}/{mux_key_edit}").update(updated_mux_data)
                        add_user_points(st.session_state.username, 5)
                        st.success("Data siaran berhasil diperbarui!")
                        st.session_state.edit_mode = False
                        st.session_state.edit_data = None
                        st.experimental_rerun()
                    except Exception as e:
                        st.error(f"Terjadi kesalahan saat memperbarui data: {e}")
        with col_btn2:
            if st.button("Batal Edit", key="btn_cancel_edit"):
                st.session_state.edit_mode = False
                st.session_state.edit_data = None
                st.experimental_rerun()
    else:
        st.warning("Tidak ada data yang dipilih untuk diedit.")
        if st.button("Kembali ke Beranda", key="btn_back_from_no_edit_data"):
            switch_page("beranda")
            st.rerun()

def display_profile_page():
    """Menampilkan halaman profil pengguna."""
    st.header("👤 Profil Saya")
    
    if not st.session_state.login:
        st.warning("Anda harus login untuk melihat profil Anda.")
        if st.button("Login"):
            switch_page("login")
            st.rerun()
        return

    users = db.reference("users").get() or {}
    user_data = users.get(st.session_state.username, {})

    if user_data:
        st.subheader(f"Username: {st.session_state.username}")
        st.write(f"**Nama Lengkap:** {user_data.get('nama', 'N/A')}")
        st.write(f"**Email:** {user_data.get('email', 'N/A')}")
        st.write(f"**Poin:** {user_data.get('points', 0)} ⭐")
        st.write(f"**Provinsi Domisili:** {user_data.get('provinsi_domisili', 'N/A')}")
        st.write(f"**Wilayah Domisili:** {user_data.get('wilayah_domisili', 'N/A')}")
        st.write(f"**Merk TV Digital/STB:** {user_data.get('merk_tv_digital', 'N/A')}")
        st.write(f"**Bergabung Sejak:** {datetime.fromisoformat(user_data.get('created_at', datetime.now(WIB).isoformat())).strftime('%d %B %Y')}")

        st.markdown("---")
        st.subheader("Edit Profil")
        with st.form("edit_profile_form"):
            new_nama = st.text_input("Nama Lengkap", value=user_data.get('nama', ''), key="edit_nama_profil")
            new_provinsi = st.selectbox("Provinsi Domisili", ["Pilih Provinsi"] + list(get_provinsi_data().keys()), index=["Pilih Provinsi"] + list(get_provinsi_data().keys()).index(user_data.get('provinsi_domisili', 'Pilih Provinsi')) if user_data.get('provinsi_domisili') else 0, key="edit_provinsi_profil")
            new_wilayah = st.text_input("Wilayah Domisili", value=user_data.get('wilayah_domisili', ''), key="edit_wilayah_profil")
            new_merk_tv = st.text_input("Merk TV Digital/STB", value=user_data.get('merk_tv_digital', ''), key="edit_merk_tv_profil")

            submit_edit = st.form_submit_button("Simpan Perubahan Profil")
            if submit_edit:
                if not new_nama or new_provinsi == "Pilih Provinsi" or not new_wilayah or not new_merk_tv:
                    st.warning("Harap isi semua kolom untuk pembaruan profil.")
                else:
                    try:
                        db.reference(f"users/{st.session_state.username}").update({
                            "nama": new_nama,
                            "provinsi_domisili": new_provinsi,
                            "wilayah_domisili": new_wilayah,
                            "merk_tv_digital": new_merk_tv
                        })
                        st.success("Profil berhasil diperbarui!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal memperbarui profil: {e}")
    else:
        st.warning("Data profil tidak ditemukan.")

    st.markdown("---")
    if st.button("⬅️ Kembali ke Beranda"):
        switch_page("beranda")
        st.rerun()

def display_other_users_page():
    """Menampilkan daftar pengguna lain dan profil mereka."""
    st.header("👥 Profil Pengguna Lain")

    users_data = db.reference("users").get() or {}
    
    other_users = {u: data for u, data in users_data.items() if u != st.session_state.username}

    if not other_users:
        st.info("Belum ada pengguna lain yang terdaftar selain Anda.")
        if st.button("⬅️ Kembali ke Beranda"):
            switch_page("beranda")
            st.rerun()
        return

    user_options = sorted(list(other_users.keys()))
    
    selected_user = st.selectbox(
        "Pilih Pengguna untuk Dilihat Profilnya",
        ["Pilih Pengguna"] + user_options,
        key="select_other_user"
    )

    if selected_user != "Pilih Pengguna":
        st.session_state.selected_other_user = selected_user
        
        user_data = other_users.get(selected_user, {})
        if user_data:
            st.subheader(f"Profil: {selected_user}")
            st.write(f"**Nama Lengkap:** {user_data.get('nama', 'N/A')}")
            st.write(f"**Poin:** {user_data.get('points', 0)} ⭐")
            st.write(f"**Provinsi Domisili:** {user_data.get('provinsi_domisili', 'N/A')}")
            st.write(f"**Wilayah Domisili:** {user_data.get('wilayah_domisili', 'N/A')}")
            st.write(f"**Merk TV Digital/STB:** {user_data.get('merk_tv_digital', 'N/A')}")
            st.write(f"**Bergabung Sejak:** {datetime.fromisoformat(user_data.get('created_at', datetime.now(WIB).isoformat())).strftime('%d %B %Y')}")
        else:
            st.warning("Data profil pengguna tidak ditemukan.")
    else:
        st.session_state.selected_other_user = None

    st.markdown("---")
    if st.button("⬅️ Kembali ke Beranda"):
        switch_page("beranda")
        st.rerun()

def display_leaderboard_page():
    """Menampilkan halaman leaderboard."""
    st.header("🏆 Leaderboard Pengguna")
    
    users_data = db.reference("users").get() or {}
    
    if not users_data:
        st.info("Belum ada data pengguna untuk leaderboard.")
        if st.button("⬅️ Kembali ke Beranda"):
            switch_page("beranda")
            st.rerun()
        return

    leaderboard_data = []
    for username, data in users_data.items():
        leaderboard_data.append({
            "Username": username,
            "Nama Lengkap": data.get("nama", "N/A"),
            "Poin": data.get("points", 0),
            "Bergabung Sejak": datetime.fromisoformat(data.get('created_at', datetime.now(WIB).isoformat())).strftime('%d %B %Y')
        })
    
    df_leaderboard = pd.DataFrame(leaderboard_data)
    df_leaderboard = df_leaderboard.sort_values(by="Poin", ascending=False).reset_index(drop=True)
    df_leaderboard.index = df_leaderboard.index + 1

    st.dataframe(df_leaderboard)

    st.markdown("---")
    if st.button("⬅️ Kembali ke Beranda"):
        switch_page("beranda")
        st.rerun()

def display_chatbot_page():
    """Menampilkan halaman FAQ Chatbot."""
    st.header("🤖 FAQ Chatbot KTVDI")
    st.info("Ajukan pertanyaan seputar KTVDI, TV Digital, atau siaran MUX. Saya akan bantu menjawab!")

    model = genai.GenerativeModel(
        model_name="gemini-pro",
        system_instruction=(
            "Anda adalah Chatbot FAQ untuk website Komunitas TV Digital Indonesia (KTVDI). "
            "Tugas Anda adalah menjawab pertanyaan pengguna seputar aplikasi KTVDI, "
            "fungsi-fungsinya (login, daftar, tambah data, edit data, hapus data, poin, leaderboard, profil, komentar), "
            "serta pertanyaan umum tentang TV Digital di Indonesia (DVB-T2, MUX, mencari siaran, antena, STB, merk TV). "
            "Jawab dengan ramah, informatif, dan ringkas. "
            "Gunakan bahasa Indonesia formal. "
            "Jika pertanyaan di luar cakupan Anda atau memerlukan informasi real-time yang tidak Anda miliki, "
            "arahkan pengguna untuk mencari informasi lebih lanjut di sumber resmi atau bertanya di forum/komunitas terkait TV Digital."
            "\n\nBerikut adalah beberapa contoh FAQ yang bisa Anda jawab dan informasi yang harus Anda pertimbangkan:"
            "\n- **Apa itu KTVDI?** KTVDI adalah platform komunitas online tempat pengguna dapat berbagi, menambahkan, memperbarui, dan melihat data siaran TV Digital (DVB-T2) di berbagai provinsi dan wilayah di Indonesia."
            "\n- **Bagaimana cara menambahkan data siaran?** Anda perlu login ke akun KTVDI Anda. Setelah login, Anda akan melihat bagian 'Tambahkan Data Siaran Baru' di halaman utama. Isi detail provinsi, wilayah, penyelenggara MUX, dan daftar siaran yang tersedia."
            "\n- **Bagaimana cara mendapatkan poin?** Anda mendapatkan 10 poin setiap kali Anda berhasil menambahkan data siaran baru. Anda mendapatkan 5 poin saat memperbarui data siaran yang sudah ada. Anda juga mendapatkan 1 poin setiap kali Anda mengirimkan komentar pada data MUX tertentu."
            "\n- **Apa itu MUX?** MUX adalah singkatan dari Multiplex. Dalam konteks TV Digital, MUX adalah teknologi yang memungkinkan beberapa saluran televisi digital disiarkan secara bersamaan melalui satu frekuensi atau kanal UHF. Setiap MUX biasanya dikelola oleh satu penyelenggara (misalnya, Metro TV, SCTV, Trans TV, TVRI)."
            "\n- **Bagaimana cara mencari siaran TV digital?** Anda dapat mencari siaran TV digital dengan melakukan pemindaian otomatis (auto scan) pada televisi digital Anda atau Set Top Box (STB) DVB-T2. Pastikan antena Anda terpasang dengan benar dan mengarah ke pemancar terdekat."
            "\n- **Apa itu DVB-T2?** DVB-T2 adalah standar penyiaran televisi digital terestrial generasi kedua yang digunakan di Indonesia. Standar ini memungkinkan kualitas gambar dan suara yang lebih baik serta efisiensi frekuensi yang lebih tinggi dibandingkan siaran analog."
            "\n- **Apakah saya bisa mengedit data yang diinput orang lain?** Tidak, Anda hanya bisa mengedit data siaran yang Anda tambahkan sendiri. Jika ada data yang salah atau perlu diperbarui yang diinput oleh pengguna lain, Anda dapat melaporkan atau menunggu kontributor yang bersangkutan untuk memperbaruinya."
            "\n- **Bagaimana cara melihat profil pengguna lain?** Di sidebar aplikasi, terdapat tombol 'Lihat Profil Pengguna Lain'. Anda bisa memilih username dari daftar untuk melihat informasi profil publik mereka seperti nama, poin, provinsi, wilayah, dan merk perangkat TV digital mereka."
            "\n- **Bagaimana cara reset password?** Jika Anda lupa password, di halaman login, klik tombol 'Lupa Password?'. Masukkan email yang terdaftar, dan Anda akan menerima kode OTP untuk mereset password Anda."
            "\n- **Bisakah saya menghapus komentar saya?** Saat ini, tidak ada fitur langsung untuk menghapus komentar setelah dikirim. Harap berhati-hati dalam menulis komentar Anda."
            "\n- **Poin untuk apa?** Poin adalah bentuk apresiasi atas kontribusi Anda dalam berbagi dan memperbarui data siaran. Pengguna dengan poin tertinggi akan ditampilkan di halaman Leaderboard."
            "\n- **Apakah harus login untuk melihat data siaran?** Tidak, Anda dapat melihat data siaran tanpa login. Login hanya diperlukan untuk menambahkan, mengedit, menghapus data, memberi komentar, melihat profil Anda, dan mengakses leaderboard."
            "\n- **Format apa untuk Wilayah Layanan?** Formatnya adalah 'Nama Provinsi-Angka'. Contoh: 'Jawa Timur-1', 'DKI Jakarta-2'."
            "\n- **Format apa untuk Penyelenggara MUX?** Formatnya adalah 'UHF XX - Nama MUX'. Contoh: 'UHF 27 - Metro TV'."
            "\n- **Bagaimana cara kerja poin?** Poin diberikan secara otomatis setiap kali Anda berkontribusi. Tambah data (10 poin), edit data (5 poin), komentar (1 poin)."
            "\n- **Apa yang harus saya lakukan jika siaran tidak muncul?** Pastikan TV/STB Anda mendukung DVB-T2, antena terpasang benar dan mengarah ke pemancar, serta lakukan scan ulang saluran."
        )
    )

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("Tanyakan sesuatu tentang KTVDI atau TV Digital..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.spinner("Mencari jawaban..."):
            try:
                chat_history_for_gemini = [
                    {"role": "user" if msg["role"] == "user" else "model", "parts": [msg["content"]]}
                    for msg in st.session_state.messages[:-1]
                ]

                chat = model.start_chat(history=chat_history_for_gemini)
                response = chat.send_message(prompt)

                full_response = response.text
                st.markdown(full_response)
                st.session_state.messages.append({"role": "assistant", "content": full_response})
            except Exception as e:
                st.error(f"Maaf, terjadi kesalahan saat menghubungi chatbot: {e}. Silakan coba lagi nanti.")
                st.session_state.messages.append({"role": "assistant", "content": "Maaf, terjadi kesalahan saat memproses permintaan Anda. Silakan coba lagi."})

    st.markdown("---")
    if st.button("⬅️ Kembali ke Beranda"):
        switch_page("beranda")
        st.rerun()

def display_sidebar(): # Definisi fungsi sidebar harus di sini, sebelum dipanggil
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
        if st.sidebar.button("🤖 FAQ Chatbot"):
            switch_page("chatbot")
            st.rerun()
        st.sidebar.button("🚪 Logout", on_click=proses_logout)


# --- ROUTING HALAMAN UTAMA APLIKASI ---

st.title("🇮🇩 KOMUNITAS TV DIGITAL INDONESIA 🇮🇩")
display_sidebar() # Sekarang fungsi ini sudah didefinisikan

if st.session_state.halaman == "beranda":
    st.header("Data Siaran TV Digital Terestrial (DVB-T2) Indonesia")
    st.write("Temukan dan bagikan informasi terbaru tentang siaran TV digital di berbagai provinsi dan wilayah.")

    provinsi_data = get_provinsi_data()

    if provinsi_data:
        provinsi_pilihan = st.selectbox(
            "Pilih Provinsi",
            ["Pilih Provinsi"] + sorted(list(provinsi_data.keys()))
        )

        if provinsi_pilihan != "Pilih Provinsi":
            st.subheader(f"Data Siaran di Provinsi {provinsi_pilihan}")
            wilayah_list = get_wilayah_data(provinsi_pilihan)

            if wilayah_list:
                for wilayah_nama in sorted(wilayah_list.keys()):
                    st.markdown(f"### Wilayah Layanan: {wilayah_nama}")
                    mux_data = get_mux_data(provinsi_pilihan, wilayah_nama)

                    if mux_data:
                        for mux_key, mux_details in mux_data.items():
                            st.markdown(f"**Penyelenggara MUX:** {mux_details.get('penyelenggara', 'N/A')}")
                            st.write(f"Ditambahkan oleh: {mux_details.get('ditambahkan_oleh', 'Anonim')} (Terakhir update: {datetime.fromisoformat(mux_details.get('last_updated_at', datetime.now(WIB).isoformat())).strftime('%d-%m-%Y %H:%M:%S')})")
                            
                            st.write("Saluran TV:")
                            if mux_details.get("siaran"):
                                for channel in mux_details["siaran"]:
                                    status_icon = "✅" if channel.get("status") == "Aktif" else "❌" if channel.get("status") == "Tidak Aktif" else "❓"
                                    st.write(f"- {channel.get('nama', 'N/A')} {status_icon} ({channel.get('status', 'N/A')})")
                            else:
                                st.info("Tidak ada data saluran untuk MUX ini.")
                            
                            if mux_details.get("catatan"):
                                st.write(f"Catatan: {mux_details['catatan']}")

                            if st.session_state.login and st.session_state.username == mux_details.get("ditambahkan_oleh"):
                                col1, col2 = st.columns(2)
                                with col1:
                                    if st.button("Edit", key=f"edit_btn_{provinsi_pilihan}_{wilayah_nama}_{mux_key}"):
                                        st.session_state.edit_mode = True
                                        st.session_state.edit_data = {
                                            "provinsi": provinsi_pilihan,
                                            "wilayah": wilayah_nama,
                                            "mux_key": mux_key,
                                            "data": mux_details
                                        }
                                        switch_page("edit_data")
                                        st.rerun()
                                with col2:
                                    if st.button("Hapus", key=f"delete_btn_{provinsi_pilihan}_{wilayah_nama}_{mux_key}"):
                                        if st.warning("Apakah Anda yakin ingin menghapus data ini?"):
                                            try:
                                                db.reference(f"mux/{provinsi_pilihan}/{wilayah_nama}/{mux_key}").delete()
                                                db.reference(f"comments/{provinsi_pilihan}/{wilayah_nama}/{mux_key}").delete()
                                                st.success("Data berhasil dihapus!")
                                                st.experimental_rerun()
                                            except Exception as e:
                                                st.error(f"Gagal menghapus data: {e}")
                            
                            st.markdown("##### Komentar")
                            comments = get_comment_data(provinsi_pilihan, wilayah_nama, mux_key)
                            if comments:
                                for comment in comments:
                                    comment_timestamp = datetime.fromisoformat(comment.get('timestamp', datetime.now(WIB).isoformat())).strftime('%d-%m-%Y %H:%M:%S')
                                    st.info(f"**{comment.get('display_name', 'Anonim')}** pada {comment_timestamp}:\n{comment.get('comment', 'N/A')}")
                            else:
                                st.info("Belum ada komentar.")

                            if st.session_state.login:
                                with st.form(key=f"comment_form_{provinsi_pilihan}_{wilayah_nama}_{mux_key}"):
                                    user_comment = st.text_area("Tulis komentar Anda:", key=f"comment_input_{provinsi_pilihan}_{wilayah_nama}_{mux_key}")
                                    submit_comment = st.form_submit_button("Kirim Komentar")
                                    if submit_comment:
                                        if user_comment:
                                            try:
                                                comment_data = {
                                                    "username": st.session_state.username,
                                                    "comment": user_comment,
                                                    "timestamp": datetime.now(WIB).isoformat()
                                                }
                                                db.reference(f"comments/{provinsi_pilihan}/{wilayah_nama}/{mux_key}").push(comment_data)
                                                add_user_points(st.session_state.username, 1)
                                                st.session_state.comment_success_message = "Komentar berhasil ditambahkan!"
                                                st.rerun()
                                            except Exception as e:
                                                st.error(f"Gagal menambahkan komentar: {e}")
                                        else:
                                            st.warning("Komentar tidak boleh kosong.")
                                if st.session_state.comment_success_message:
                                    st.success(st.session_state.comment_success_message)
                                    st.session_state.comment_success_message = ""
                            else:
                                st.info("Login untuk memberikan komentar.")
                            st.markdown("---")
                    else:
                        st.info(f"Belum ada data MUX untuk wilayah {wilayah_nama}.")
            else:
                st.info("Belum ada data wilayah untuk provinsi ini.")
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
    else:
        display_registration_form(users)

    if st.button("⬅️ Kembali ke Beranda"):
        switch_page("beranda")
        st.rerun()

elif st.session_state.halaman == "edit_data":
    if not st.session_state.login:
        st.warning("Anda harus login untuk mengakses halaman ini.")
        switch_page("login")
    else:
        display_edit_data_form()

elif st.session_state.halaman == "profile":
    display_profile_page()

elif st.session_state.halaman == "other_users":
    display_other_users_page()

elif st.session_state.halaman == "leaderboard":
    display_leaderboard_page()

elif st.session_state.halaman == "chatbot":
    display_chatbot_page()