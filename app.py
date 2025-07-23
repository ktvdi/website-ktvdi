import streamlit as st
import firebase_admin
import hashlib
import smtplib
import random
import time
import re
from email.mime.text import MIMEText
from firebase_admin import credentials, db
from pytz import timezone
from datetime import datetime

# Import tambahan untuk membuat gambar
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import textwrap

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
        "edit_data": None # Menyimpan data yang sedang diedit
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
    """Meng-hash password menggunakan SHA256."""
    return hashlib.sha256(password.encode()).hexdigest()

def generate_otp():
    """Menghasilkan kode OTP 6 digit secara acak."""
    return str(random.randint(100000, 999999))

def send_otp_email(receiver_email, otp, purpose="reset"):
    """
    Mengirim email berisi kode OTP.
    Purpose bisa 'reset' untuk reset password atau 'daftar' untuk pendaftaran.
    """
    sender = st.secrets["email"]["sender"]
    app_password = st.secrets["email"]["app_password"]

    if purpose == "reset":
        subject = "Kode OTP Reset Password KTVDI"
        body = f"Kode OTP untuk reset password Anda adalah: {otp}"
    else: # daftar
        subject = "Kode OTP Pendaftaran Akun KTVDI"
        body = f"Kode OTP untuk pendaftaran akun Anda adalah: {otp}"

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = receiver_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, app_password)
            server.sendmail(sender, receiver_email, msg.as_string())
        return True
    except Exception as e:
        st.error(f"Gagal mengirim email: {e}")
        return False

def switch_page(page_name):
    """Fungsi untuk berpindah halaman."""
    st.session_state.halaman = page_name

def proses_logout():
    """Membersihkan session state saat logout."""
    st.session_state.login = False
    st.session_state.username = ""
    switch_page("beranda")

# --- FUNGSI UNTUK MERENDER KOMPONEN UI ---

def display_sidebar():
    """Menampilkan sidebar untuk pengguna yang sudah login."""
    if st.session_state.login:
        users = db.reference("users").get() or {}
        user_data = users.get(st.session_state.username, {})
        nama_pengguna = user_data.get("nama", st.session_state.username)

        st.sidebar.title(f"Hai, {nama_pengguna}!")
        st.sidebar.button("🚪 Logout", on_click=proses_logout)

def display_login_form(users):
    """Menampilkan form untuk login."""
    st.header("🔐 Login Akun KTVDI")
    
    def proses_login():
        user = st.session_state.get("login_user", "").strip()
        pw = st.session_state.get("login_pass", "").strip()
        
        if not user or not pw:
            st.toast("Username dan password tidak boleh kosong.")
            return

        hashed_pw = hash_password(pw)
        if user in users and users[user].get("password") == hashed_pw:
            st.session_state.login = True
            st.session_state.username = user
            st.session_state.login_error = ""
            switch_page("beranda")
        else:
            st.toast("Username atau password salah.")

    st.text_input("Username", key="login_user")
    st.text_input("Password", type="password", key="login_pass")
    st.button("Login", on_click=proses_login)

    if st.button("Lupa Password?"):
        st.session_state.lupa_password = True
        st.rerun()

def display_forgot_password_form(users):
    """Menampilkan form untuk proses lupa password."""
    st.header("🔑 Reset Password")

    # Tahap 1: Kirim OTP
    if not st.session_state.otp_sent:
        lupa_nama = st.text_input("Nama Lengkap", key="reset_nama")
        username = st.text_input("Username", key="reset_user")

        if st.button("Kirim OTP ke Email"):
            user_data = users.get(username)
            if not lupa_nama or not username:
                st.toast("Nama lengkap dan username harus diisi.")
            elif not user_data:
                st.toast("❌ Username tidak ditemukan.")
            elif user_data.get("nama", "").strip().lower() != lupa_nama.strip().lower():
                st.toast("❌ Nama tidak cocok dengan username terdaftar.")
            else:
                otp = generate_otp()
                if send_otp_email(user_data["email"], otp, purpose="reset"):
                    st.session_state.otp_code = otp
                    st.session_state.reset_username = username
                    st.session_state.otp_sent = True
                    st.success(f"OTP berhasil dikirim ke {user_data['email']}.")
                    time.sleep(2)
                    st.rerun()

    # Tahap 2: Verifikasi OTP dan Reset Password
    else:
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
                
                # Reset state dan kembali ke halaman login
                st.session_state.lupa_password = False
                st.session_state.otp_sent = False
                time.sleep(2)
                st.rerun()

    if st.button("❌ Batalkan"):
        st.session_state.lupa_password = False
        st.session_state.otp_sent = False
        st.rerun()

def display_registration_form(users):
    """Menampilkan form untuk pendaftaran akun baru."""
    st.header("📝 Daftar Akun Baru")

    with st.form("form_daftar", clear_on_submit=False):
        full_name = st.text_input("Nama Lengkap")
        new_email = st.text_input("Email")
        user = st.text_input("Username Baru (huruf kecil/angka tanpa spasi)", placeholder="Contoh: akbar123")
        pw = st.text_input("Password Baru (minimal 6 karakter)", type="password")
        
        email_exists = any(u.get("email", "").lower() == new_email.lower() for u in users.values())

        submitted = st.form_submit_button("Daftar")
        if submitted:
            if not all([full_name, new_email, user, pw]):
                st.toast("❌ Semua kolom wajib diisi.")
            elif user in users:
                st.toast("❌ Username sudah digunakan.")
            elif email_exists:
                st.toast("❌ Email sudah terdaftar.")
            elif not user.isalnum() or not user.islower() or " " in user:
                st.toast("❌ Username hanya boleh huruf kecil dan angka, tanpa spasi.")
            elif len(pw) < 6:
                st.toast("❌ Password minimal 6 karakter.")
            else:
                # Simpan data sementara di session state untuk verifikasi OTP
                st.session_state.temp_reg_data = {
                    "nama": full_name, "email": new_email, "user": user, "pw": pw
                }
                otp = generate_otp()
                if send_otp_email(new_email, otp, purpose="daftar"):
                    st.session_state.otp_sent_daftar = True
                    st.session_state.otp_code_daftar = otp
                    st.success("OTP berhasil dikirim ke email Anda.")
                    st.rerun()
                else:
                    st.error("Gagal mengirim OTP. Coba lagi nanti.")

    if st.session_state.get("otp_sent_daftar"):
        st.info("Masukkan OTP yang telah dikirim ke email Anda untuk menyelesaikan pendaftaran.")
        input_otp = st.text_input("Masukkan Kode OTP", key="daftar_otp")
        
        if st.button("Verifikasi dan Selesaikan Pendaftaran"):
            if input_otp != st.session_state.get("otp_code_daftar"):
                st.error("❌ Kode OTP salah.")
            else:
                reg_data = st.session_state.temp_reg_data
                db.reference("users").child(reg_data["user"]).set({
                    "nama": reg_data["nama"],
                    "password": hash_password(reg_data["pw"]),
                    "email": reg_data["email"]
                })
                st.success("✅ Akun berhasil dibuat! Silakan login.")
                
                # Bersihkan state pendaftaran
                st.session_state.otp_sent_daftar = False
                st.session_state.temp_reg_data = {}
                st.session_state.mode = "Login"
                time.sleep(2)
                st.rerun()

def display_add_data_form():
    """Menampilkan form untuk menambahkan data siaran (hanya untuk user login)."""
    st.markdown("---")
    st.markdown("## ✍️ Tambahkan Data Siaran Baru")

    provinsi_data = db.reference("provinsi").get()
    if not provinsi_data:
        st.warning("Data provinsi belum tersedia.")
        return

    provinsi_list = sorted(provinsi_data.values()) # Daftar provinsi yang valid
    
    with st.form("add_data_form", clear_on_submit=True):
        provinsi = st.selectbox("Pilih Provinsi", provinsi_list, key="provinsi_input_add")
        wilayah = st.text_input("Masukkan Wilayah Layanan", placeholder="Contoh: Jawa Timur-1", key="wilayah_input_add")
        mux = st.text_input("Masukkan Penyelenggara MUX", placeholder="Contoh: UHF 27 - Metro TV", key="mux_input_add")
        siaran_input = st.text_area(
            "Masukkan Daftar Siaran (pisahkan dengan koma)",
            placeholder="Contoh: Metro TV, Magna Channel, BN Channel",
            key="siaran_input_add"
        )

        submitted = st.form_submit_button("Simpan Data Baru")
        
        if submitted:
            if not all([provinsi, wilayah, mux, siaran_input]):
                st.warning("Harap isi semua kolom.")
                is_valid = False
            else:
                wilayah_clean = wilayah.strip()
                wilayah_clean = re.sub(r'\s*-\s*', '-', wilayah_clean) # Normalisasi spasi di sekitar tanda hubung

                mux_clean = mux.strip()
                siaran_list = [s.strip() for s in siaran_input.split(",") if s.strip()]
                
                is_valid = True 
                
                # Validasi Format Wilayah Layanan: "Nama Provinsi-Angka"
                wilayah_pattern = r"^[a-zA-Z\s]+-\d+$" 
                if not re.fullmatch(wilayah_pattern, wilayah_clean):
                    st.error("Format **Wilayah Layanan** tidak valid. Harap gunakan format 'Nama Provinsi-Angka'. Contoh: 'Jawa Timur-1', 'DKI Jakarta-2'.")
                    is_valid = False
                else:
                    # --- Validasi Baru: Nama Provinsi di Wilayah Layanan harus ada di daftar provinsi ---
                    # Ekstrak nama provinsi dari wilayah_clean (bagian sebelum tanda hubung)
                    wilayah_parts = wilayah_clean.split('-')
                    if len(wilayah_parts) > 1:
                        provinsi_from_wilayah = '-'.join(wilayah_parts[:-1]).strip() # Menggabungkan kembali jika ada '-' di nama provinsi
                        if provinsi_from_wilayah not in provinsi_list:
                            st.error(f"Nama provinsi '{provinsi_from_wilayah}' dalam Wilayah Layanan tidak ditemukan di daftar provinsi yang ada. Mohon periksa kembali.")
                            is_valid = False
                    else:
                        # Ini seharusnya tidak terjadi jika regex wilayah_pattern sudah terpenuhi
                        st.error("Format Wilayah Layanan tidak lengkap (tidak ada tanda hubung dan angka).")
                        is_valid = False
                    # --- End Validasi Baru ---
                
                # Validasi Format Penyelenggara MUX
                mux_pattern = r"^UHF\s+\d{1,3}\s*-\s*.+$"
                if not re.fullmatch(mux_pattern, mux_clean, re.IGNORECASE):
                    st.error("Format **Penyelenggara MUX** tidak valid. Harap gunakan format 'UHF XX - Nama MUX'. Contoh: 'UHF 27 - Metro TV'.")
                    is_valid = False

                # Validasi Daftar Siaran
                if not siaran_list:
                    st.warning("Daftar **Siaran** tidak boleh kosong.")
                    is_valid = False
                else:
                    for s in siaran_list:
                        if not re.fullmatch(r"^[a-zA-Z0-9\s&()_.,'-]+$", s): 
                            st.error(f"Nama siaran '{s}' tidak valid. Hanya boleh huruf, angka, spasi, dan karakter '&()_.,'-'.")
                            is_valid = False
                            break
                            
                if is_valid:
                    try:
                        updater_username = st.session_state.username
                        users_ref = db.reference("users").child(updater_username).get()
                        updater_name = users_ref.get("nama", updater_username)
                        
                        now_wib = datetime.now(WIB)
                        updated_date = now_wib.strftime("%d-%m-%Y")
                        updated_time = now_wib.strftime("%H:%M:%S WIB")

                        data_to_save = {
                            "siaran": sorted(siaran_list),
                            "last_updated_by_username": updater_username,
                            "last_updated_by_name": updater_name,
                            "last_updated_date": updated_date,
                            "last_updated_time": updated_time
                        }
                        
                        db.reference(f"siaran/{provinsi}/{wilayah_clean}/{mux_clean}").set(data_to_save)
                        st.success("Data berhasil disimpan!")
                        st.balloons()
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal menyimpan data: {e}")

# Fungsi untuk menangani tindakan edit dan hapus
def handle_edit_delete_actions(provinsi, wilayah, mux_key, mux_details_full, current_selected_mux_filter=None):
    """
    Menampilkan tombol edit/delete dan memicu aksi terkait.
    Fungsi ini dipanggil di mana pun data siaran ditampilkan.
    """
    # Pastikan mux_details_full adalah dictionary untuk mendapatkan semua info
    if isinstance(mux_details_full, list):
        current_siaran_list = mux_details_full
        current_updated_by_username = None
        current_updated_by_name = "Belum Diperbarui"
        current_updated_date = "N/A"
        current_updated_time = "N/A"
    else: # Sudah format dictionary
        current_siaran_list = mux_details_full.get("siaran", [])
        current_updated_by_username = mux_details_full.get("last_updated_by_username")
        current_updated_by_name = mux_details_full.get("last_updated_by_name", "N/A")
        current_updated_date = mux_details_full.get("last_updated_date", "N/A")
        current_updated_time = mux_details_full.get("last_updated_time", "N/A")

    # Menampilkan keterangan "Diperbarui oleh..."
    st.markdown(f"<p style='font-size: small; color: grey;'>Diperbarui oleh: <b>{current_updated_by_name}</b> pada {current_updated_date} pukul {current_updated_time}</p>", unsafe_allow_html=True)

    col_edit_del_1, col_edit_del_2 = st.columns(2)
    with col_edit_del_1:
        if st.button(f"✏️ Edit {mux_key}", key=f"edit_{provinsi}_{wilayah}_{mux_key}"):
            st.session_state.edit_mode = True # Set edit_mode
            st.session_state.edit_data = {
                "provinsi": provinsi,
                "wilayah": wilayah,
                "mux": mux_key,
                "siaran": current_siaran_list,
                "last_updated_by_username": current_updated_by_username,
                "last_updated_by_name": current_updated_by_name,
                "last_updated_date": current_updated_date,
                "last_updated_time": current_updated_time,
                "parent_selected_mux_filter": current_selected_mux_filter
            }
            switch_page("edit_data") # PINDAH KE HALAMAN BARU UNTUK EDIT
            st.rerun()
    with col_edit_del_2:
        if st.button(f"🗑️ Hapus {mux_key}", key=f"delete_{provinsi}_{wilayah}_{mux_key}"):
            try:
                db.reference(f"siaran/{provinsi}/{wilayah}/{mux_key}").delete()
                st.success(f"Data {mux_key} berhasil dihapus!")
                time.sleep(2)
                st.rerun()
            except Exception as e:
                st.error(f"Gagal menghapus data: {e}")
    st.markdown("---")

# --- FUNGSI BARU UNTUK HALAMAN EDIT ---
def display_edit_data_page():
    """Menampilkan halaman terpisah untuk mengedit data siaran."""
    st.header("📝 Edit Data Siaran")

    if not st.session_state.login:
        st.warning("Anda harus login untuk mengakses halaman ini.")
        switch_page("login")
        return
    
    if not st.session_state.edit_mode or st.session_state.edit_data is None:
        st.warning("Tidak ada data siaran yang dipilih untuk diedit. Silakan pilih data dari halaman utama.")
        if st.button("Kembali ke Beranda"):
            switch_page("beranda")
        return

    edit_data = st.session_state.edit_data
    
    selected_provinsi = edit_data.get("provinsi", "N/A")
    default_wilayah = edit_data.get("wilayah", "")
    default_mux = edit_data.get("mux", "")
    default_siaran_list = edit_data.get("siaran", [])
    default_siaran = ", ".join(default_siaran_list)

    # Ambil daftar provinsi untuk validasi
    provinsi_data = db.reference("provinsi").get()
    provinsi_list = sorted(provinsi_data.values()) if provinsi_data else []

    st.info(f"Anda sedang mengedit data untuk **{default_mux}** di **{default_wilayah}, {selected_provinsi}**.")

    with st.form("edit_form_page", clear_on_submit=False):
        st.text_input("Provinsi", value=selected_provinsi, disabled=True, key="edit_provinsi_page")
        new_wilayah = st.text_input("Wilayah Layanan", value=default_wilayah, placeholder="Contoh: Jawa Timur-1", key="edit_wilayah_page")
        new_mux = st.text_input("Penyelenggara MUX", value=default_mux, placeholder="Contoh: UHF 27 - Metro TV", key="edit_mux_page")
        new_siaran_input = st.text_area(
            "Daftar Siaran (pisahkan dengan koma)",
            value=default_siaran,
            placeholder="Contoh: Metro TV, Magna Channel, BN Channel",
            key="edit_siaran_page"
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.form_submit_button("Simpan Perubahan"):
                # --- VALIDASI PADA FORM EDIT ---
                if not all([new_wilayah, new_mux, new_siaran_input]):
                    st.warning("Harap isi semua kolom.")
                    is_valid = False
                else:
                    new_wilayah_clean = new_wilayah.strip()
                    new_wilayah_clean = re.sub(r'\s*-\s*', '-', new_wilayah_clean) # Normalisasi spasi di sekitar tanda hubung

                    new_mux_clean = new_mux.strip()
                    new_siaran_list = [s.strip() for s in new_siaran_input.split(",") if s.strip()]
                    
                    is_valid = True 
                    
                    # Validasi Format Wilayah Layanan: "Nama Provinsi-Angka"
                    wilayah_pattern = r"^[a-zA-Z\s]+-\d+$" 
                    if not re.fullmatch(wilayah_pattern, new_wilayah_clean):
                        st.error("Format **Wilayah Layanan** tidak valid. Harap gunakan format 'Nama Provinsi-Angka'. Contoh: 'Jawa Timur-1', 'DKI Jakarta-2'.")
                        is_valid = False
                    else:
                        # --- Validasi Baru: Nama Provinsi di Wilayah Layanan harus ada di daftar provinsi ---
                        wilayah_parts = new_wilayah_clean.split('-')
                        if len(wilayah_parts) > 1:
                            provinsi_from_wilayah = '-'.join(wilayah_parts[:-1]).strip()
                            if provinsi_from_wilayah not in provinsi_list:
                                st.error(f"Nama provinsi '{provinsi_from_wilayah}' dalam Wilayah Layanan tidak ditemukan di daftar provinsi yang ada. Mohon periksa kembali.")
                                is_valid = False
                        else:
                            st.error("Format Wilayah Layanan tidak lengkap (tidak ada tanda hubung dan angka).")
                            is_valid = False
                        # --- End Validasi Baru ---
                    
                    # Validasi Format Penyelenggara MUX
                    mux_pattern = r"^UHF\s+\d{1,3}\s*-\s*.+$"
                    if not re.fullmatch(mux_pattern, new_mux_clean, re.IGNORECASE):
                        st.error("Format **Penyelenggara MUX** tidak valid. Harap gunakan format 'UHF XX - Nama MUX'. Contoh: 'UHF 27 - Metro TV'.")
                        is_valid = False

                    # Validasi Daftar Siaran
                    if not new_siaran_list:
                        st.warning("Daftar **Siaran** tidak boleh kosong.")
                        is_valid = False
                    else:
                        for s in new_siaran_list:
                            if not re.fullmatch(r"^[a-zA-Z0-9\s&()_.,'-]+$", s): 
                                st.error(f"Nama siaran '{s}' tidak valid. Hanya boleh huruf, angka, spasi, dan karakter '&()_.,'-'.")
                                is_valid = False
                                break
                                
                    if is_valid:
                        try:
                            updater_username = st.session_state.username
                            users_ref = db.reference("users").child(updater_username).get()
                            updater_name = users_ref.get("nama", updater_username)
                            
                            now_wib = datetime.now(WIB)
                            updated_date = now_wib.strftime("%d-%m-%Y")
                            updated_time = now_wib.strftime("%H:%M:%S WIB")

                            data_to_update = {
                                "siaran": sorted(new_siaran_list),
                                "last_updated_by_username": updater_username,
                                "last_updated_by_name": updater_name,
                                "last_updated_date": updated_date,
                                "last_updated_time": updated_time
                            }

                            default_wilayah_normalized = re.sub(r'\s*-\s*', '-', default_wilayah)
                            
                            if default_wilayah_normalized != new_wilayah_clean or default_mux != new_mux_clean:
                                db.reference(f"siaran/{selected_provinsi}/{default_wilayah}/{default_mux}").delete()
                                st.toast("Data lama dihapus.")
                                db.reference(f"siaran/{selected_provinsi}/{new_wilayah_clean}/{new_mux_clean}").set(data_to_update)
                            else:
                                db.reference(f"siaran/{selected_provinsi}/{new_wilayah_clean}/{new_mux_clean}").update(data_to_update)
                                
                            st.success("Data berhasil diperbarui!")
                            st.balloons()
                            st.session_state.edit_mode = False
                            st.session_state.edit_data = None
                            time.sleep(1)
                            switch_page("beranda")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Gagal memperbarui data: {e}")
        with col2:
            if st.form_submit_button("Batal"):
                st.session_state.edit_mode = False
                st.session_state.edit_data = None
                switch_page("beranda")
                st.rerun()

# --- FUNGSI UNTUK GENERATE GAMBAR DARI TEMPLATE ---
def generate_siaran_image(provinsi, wilayah, mux_data_for_image, selected_mux_filter):
    """
    Menghasilkan gambar JPG dari data siaran menggunakan template desain yang sudah ada
    dan font dari repositori GitHub.
    """
    # --- KONFIGURASI TEMPLATE DAN POSISI TEKS ---
    # Ganti 'assets/template_siaran.png' dengan path ke file desain Anda di repositori GitHub
    # Contoh: jika Anda menaruhnya di folder 'images', maka jadi 'images/template_siaran.png'
    template_path = "assets/template.jng" # <--- SESUAIKAN PATH INI

    # --- KONFIGURASI FONT ---
    # PASTI DULU: BUAT FOLDER 'fonts' DI ROOT REPOSITORI ANDA
    # DAN LETAKKAN FILE .ttf DI DALAMNYA, CONTOH: 'fonts/Montserrat-Regular.ttf'
    font_path_in_repo = "font/PoetsenOne-Regular.ttf" # <--- SESUAIKAN PATH DAN NAMA FILE FONT ANDA

    # Koordinat awal (X, Y) untuk setiap bagian teks pada template Anda
    # Anda perlu menyesuaikan nilai-nilai ini agar sesuai dengan desain Anda
    # GUNAKAN SOFTWARE PENGOLAH GAMBAR (seperti Paint, GIMP, Photoshop) untuk menentukan koordinat ini.
    # Arahkan kursor ke pojok kiri atas area tempat teks akan dimulai.
    pos_provinsi_wilayah = (48, 57) # Contoh: (X, Y) untuk teks Provinsi dan Wilayah
    pos_mux_start_y = 150 # Y awal untuk MUX pertama. X akan sama dengan pos_general_mux_title[0]
    pos_general_mux_title_x = 50 # X yang sama untuk semua judul MUX
    pos_general_siaran_list_x = 65 # X yang sama untuk semua daftar siaran
    pos_general_updated_info_x = 50 # X yang sama untuk semua info "Diperbarui oleh"

    # Lebar maksimum baris teks untuk siaran, jika perlu dibungkus
    # Sesuaikan lebar ini agar teks tidak keluar dari batas desain Anda
    max_siaran_text_width = 700

    # Jarak antar baris (line height)
    line_height_siaran = 20
    line_height_info = 15
    spacing_between_mux = 25 # Jarak tambahan setelah setiap blok MUX

    # --- Pemuatan Font (Diperbarui untuk menggunakan font dari repo) ---
    try:
        # Coba muat font dari path yang ditentukan di repositori
        # Jika font ini tidak ditemukan, itu akan memicu IOError
        header_font = ImageFont.truetype(font_path_in_repo, 20)
        content_font = ImageFont.truetype(font_path_in_repo, 16)
        small_font = ImageFont.truetype(font_path_in_repo, 12)
        
    except IOError:
        st.error(f"Gagal memuat font kustom dari '{font_path_in_repo}'. Pastikan file font ada di lokasi tersebut.")
        st.warning("Menggunakan font PIL default. Kualitas gambar mungkin bervariasi.")
        # Fallback ke font default jika font kustom tidak ditemukan
        header_font = ImageFont.load_default()
        content_font = ImageFont.load_default()
        small_font = ImageFont.load_default()
        

    # --- Membuka Template Gambar ---
    try:
        img = Image.open(template_path).convert("RGB") # Pastikan dikonversi ke RGB
        d = ImageDraw.Draw(img)
    except FileNotFoundError:
        st.error(f"File template gambar tidak ditemukan di: '{template_path}'. Pastikan path benar dan file ada di repositori GitHub Anda.")
        # Fallback ke gambar kosong jika template tidak ditemukan (untuk debug)
        img = Image.new('RGB', (800, 600), color = (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.text((50, 50), "Error: Template not found!", fill=(255, 0, 0), font=header_font)
        # Hentikan eksekusi lebih lanjut jika ada error fatal agar tidak crash
        return BytesIO().getvalue() # Kembalikan byte kosong atau tangani sesuai kebutuhan

    # --- Menulis Data ke Gambar ---
    
    # Data Provinsi dan Wilayah
    d.text(pos_provinsi_wilayah, f"Provinsi: {provinsi} | Wilayah: {wilayah}", fill=(0, 0, 0), font=header_font)

    # Inisialisasi offset Y untuk konten MUX
    current_y_offset = pos_mux_start_y
    
    # Fungsi pembantu untuk menggambar konten MUX
    def draw_mux_content_on_image(mux_key, mux_details, y_offset_ref):
        nonlocal current_y_offset # Mengakses dan memodifikasi variabel dari scope luar
        
        # Gambar judul MUX
        d.text((pos_general_mux_title_x, y_offset_ref), f"📡 {mux_key}", fill=(0, 0, 128), font=header_font)
        y_offset_ref += header_font.getbbox(f"📡 {mux_key}")[3] + 5

        siaran_list = mux_details.get("siaran", []) if isinstance(mux_details, dict) else mux_details
        
        # Gambar daftar siaran, bungkus jika terlalu panjang
        for tv in siaran_list:
            # Estimasi karakter per baris berdasarkan lebar piksel dan ukuran font
            chars_per_line = int(max_siaran_text_width / (content_font.getbbox('A')[2])) # bbox[2] adalah lebar karakter
            wrapped_text = textwrap.wrap(f"- {tv}", width=chars_per_line)
            for line in wrapped_text:
                d.text((pos_general_siaran_list_x, y_offset_ref), line, fill=(0, 0, 0), font=content_font)
                y_offset_ref += line_height_siaran
            
        # Gambar info pembaruan
        if isinstance(mux_details, dict):
            last_updated_by_name = mux_details.get("last_updated_by_name", "N/A")
            last_updated_date = mux_details.get("last_updated_date", "N/A")
            last_updated_time = mux_details.get("last_updated_time", "N/A")
            updated_info = f"Diperbarui oleh: {last_updated_by_name} pada {last_updated_date} pukul {last_updated_time}"
        else:
            updated_info = "Diperbarui oleh: Belum Diperbarui pada N/A pukul N/A"
            
        d.text((pos_general_updated_info_x, y_offset_ref), updated_info, fill=(100, 100, 100), font=small_font)
        y_offset_ref += small_font.getbbox(updated_info)[3] + spacing_between_mux # Tambah ruang antar MUX

        return y_offset_ref # Kembalikan y_offset yang diperbarui

    # Loop untuk menggambar semua MUX atau MUX tertentu
    if selected_mux_filter == "Semua MUX":
        sorted_mux_keys = sorted(mux_data_for_image.keys()) # Pastikan MUX diurutkan
        for mux_key in sorted_mux_keys:
            mux_details = mux_data_for_image[mux_key]
            current_y_offset = draw_mux_content_on_image(mux_key, mux_details, current_y_offset)
    else:
        mux_details = mux_data_for_image.get(selected_mux_filter, {})
        if mux_details:
            current_y_offset = draw_mux_content_on_image(selected_mux_filter, mux_details, current_y_offset)
        else:
            d.text((pos_general_mux_title_x, current_y_offset), "Tidak ada data siaran untuk MUX ini.", fill=(150, 0, 0), font=content_font)

    # Simpan gambar ke stream byte
    buf = BytesIO()
    # Anda bisa pilih format "PNG" jika template Anda PNG dan Anda ingin menjaga kualitas lossless
    img.save(buf, format="JPEG", quality=90) 
    byte_im = buf.getvalue()
    return byte_im

# --- HALAMAN UTAMA APLIKASI ---

st.title("🇮🇩 KOMUNITAS TV DIGITAL INDONESIA 🇮🇩")
display_sidebar()

# --- ROUTING HALAMAN ---

if st.session_state.halaman == "beranda":
    st.header("📺 Data Siaran TV Digital di Indonesia")
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
                        st.markdown("---")
                else:
                    st.info("Tidak ada data siaran untuk MUX ini.")

            # --- Tombol Unduh sebagai JPG ---
            if st.session_state.login:
                st.markdown("---")
                st.subheader("⬇️ Unduh Data Siaran sebagai JPG")
                
                # Mendapatkan data yang akan dirender dalam gambar
                data_to_render_for_image = {}
                if selected_mux_filter == "Semua MUX":
                    # Jika "Semua MUX", kirim semua data MUX dari wilayah yang dipilih
                    data_to_render_for_image = mux_data
                else:
                    # Jika MUX spesifik, kirim hanya data MUX yang dipilih
                    data_to_render_for_image = {selected_mux_filter: mux_data.get(selected_mux_filter, {})}

                if st.button("Unduh Gambar Data Siaran"):
                    with st.spinner("Mempersiapkan gambar..."):
                        image_bytes = generate_siaran_image(selected_provinsi, selected_wilayah, data_to_render_for_image, selected_mux_filter)
                        
                        # Hanya sediakan tombol download jika image_bytes valid (tidak kosong)
                        if image_bytes:
                            st.download_button(
                                label="Klik untuk Unduh File JPG",
                                data=image_bytes,
                                file_name=f"Data_Siaran_{selected_provinsi}_{selected_wilayah}_{selected_mux_filter.replace(' ', '_').replace('/', '-')}.jpg",
                                mime="image/jpeg"
                            )
                            st.success("Gambar siap diunduh!")
                        else:
                            st.error("Gagal membuat gambar. Periksa log konsol untuk detail.")
            # --- Akhir Tombol Unduh ---

        else:
            st.info("Belum ada data siaran untuk provinsi ini.")
    else:
        st.warning("Gagal memuat data provinsi.")

    # Tampilkan form tambah data jika sudah login
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

    # Reset state lupa password jika user memilih daftar
    if st.session_state.mode == "Daftar Akun":
        st.session_state.lupa_password = False
    
    # Navigasi antara Login dan Daftar
    if not st.session_state.lupa_password:
        st.session_state.mode = st.selectbox(
            "Pilih Aksi", ["Login", "Daftar Akun"], key="login_reg_select"
        )

    # Tampilkan form yang sesuai
    if st.session_state.lupa_password:
        display_forgot_password_form(users)
    elif st.session_state.mode == "Login":
        display_login_form(users)
    else: # Daftar Akun
        display_registration_form(users)

    if st.button("⬅️ Kembali ke Beranda"):
        switch_page("beranda")
        st.rerun()

# --- Routing untuk halaman edit_data ---
elif st.session_state.halaman == "edit_data":
    if not st.session_state.login: # Pastikan user login untuk mengakses halaman edit
        st.warning("Anda harus login untuk mengakses halaman ini.")
        switch_page("login")
    else:
        display_edit_data_page() # Panggil fungsi untuk merender halaman edit
