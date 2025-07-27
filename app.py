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
        "edit_data": None, # Menyimpan data yang sedang diedit
        "selected_other_user": None, # Menyimpan username pengguna lain yang dipilih untuk dilihat
        "comment_success_message": "" # Tambahkan ini untuk pesan sukses komentar
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
    st.session_state.selected_other_user = None
    switch_page("beranda")

# --- FUNGSI UNTUK MERENDER KOMPONEN UI ---

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

    if not st.session_state.otp_sent:
        reset_email = st.text_input("Email Terdaftar", key="reset_email")

        if st.button("Kirim OTP ke Email"):
            if not reset_email:
                st.toast("Email tidak boleh kosong.")
                return

            # Cari username berdasarkan email
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
                    st.session_state.reset_username = found_username # Simpan username yang ditemukan
                    st.session_state.otp_sent = True
                    st.success(f"OTP berhasil dikirim ke {user_data['email']}.")
                    # Tampilkan username di sini
                    st.info(f"Username Anda adalah: **{found_username}**")
                    time.sleep(2)
                    st.rerun()

    else: # OTP sudah terkirim, tampilkan form untuk input OTP dan password baru
        # Tampilkan username yang disimpan di session_state
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
                    "email": reg_data["email"],
                    "points": 0
                })
                st.success("✅ Akun berhasil dibuat! Silakan login.")
                
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

    provinsi_list = sorted(provinsi_data.values())
    
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
                wilayah_clean = re.sub(r'\s*-\s*', '-', wilayah_clean)

                mux_clean = mux.strip()
                siaran_list = [s.strip() for s in siaran_input.split(",") if s.strip()]
                
                is_valid = True 
                
                wilayah_pattern = r"^[a-zA-Z\s]+-\d+$" 
                if not re.fullmatch(wilayah_pattern, wilayah_clean):
                    st.error("Format **Wilayah Layanan** tidak valid. Harap gunakan format 'Nama Provinsi-Angka'. Contoh: 'Jawa Timur-1', 'DKI Jakarta-2'.")
                    is_valid = False
                else:
                    wilayah_parts = wilayah_clean.split('-')
                    if len(wilayah_parts) > 1:
                        provinsi_from_wilayah = '-'.join(wilayah_parts[:-1]).strip()
                        if provinsi_from_wilayah.lower() != provinsi.lower():
                            st.error(f"Nama provinsi '{provinsi_from_wilayah}' dalam **Wilayah Layanan** tidak cocok dengan **Provinsi** yang dipilih ('{provinsi}').")
                            is_valid = False
                    else:
                        st.error("Format **Wilayah Layanan** tidak lengkap (tidak ada tanda hubung dan angka).")
                        is_valid = False
                
                mux_pattern = r"^UHF\s+\d{1,3}\s*-\s*.+$"
                if not re.fullmatch(mux_pattern, mux_clean, re.IGNORECASE):
                    st.error("Format **Penyelenggara MUX** tidak valid. Harap gunakan format 'UHF XX - Nama MUX'. Contoh: 'UHF 27 - Metro TV'.")
                    is_valid = False

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
                        users_ref = db.reference(f"users/{updater_username}")
                        updater_data = users_ref.get()
                        updater_name = updater_data.get("nama", updater_username)
                        
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
                        
                        current_points = updater_data.get("points", 0)
                        users_ref.update({"points": current_points + 10})
                        db.reference("app_metadata/last_leaderboard_update_timestamp").set(now_wib.strftime("%Y-%m-%d %H:%M:%S"))
                        st.toast("Anda mendapatkan 10 poin untuk kontribusi ini!")

                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal menyimpan data: {e}")

def handle_edit_delete_actions(provinsi, wilayah, mux_key, mux_details_full, current_selected_mux_filter=None):
    """
    Menampilkan tombol edit/delete dan memicu aksi terkait.
    Fungsi ini dipanggil di mana pun data siaran ditampilkan.
    """
    if isinstance(mux_details_full, list):
        current_siaran_list = mux_details_full
        current_updated_by_username = None
        current_updated_by_name = "Belum Diperbarui"
        current_updated_date = "N/A"
        current_updated_time = "N/A"
    else:
        current_siaran_list = mux_details_full.get("siaran", [])
        current_updated_by_username = mux_details_full.get("last_updated_by_username")
        current_updated_by_name = mux_details_full.get("last_updated_by_name", "N/A")
        current_updated_date = mux_details_full.get("last_updated_date", "N/A")
        current_updated_time = mux_details_full.get("last_updated_time", "N/A")

    st.markdown(f"<p style='font-size: small; color: grey;'>Diperbarui oleh: <b>{current_updated_by_name}</b> pada {current_updated_date} pukul {current_updated_time}</p>", unsafe_allow_html=True)

    col_edit_del_1, col_edit_del_2 = st.columns(2)
    with col_edit_del_1:
        if st.button(f"✏️ Edit {mux_key}", key=f"edit_{provinsi}_{wilayah}_{mux_key}"):
            st.session_state.edit_mode = True
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
            switch_page("edit_data")
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
                if not all([new_wilayah, new_mux, new_siaran_input]):
                    st.warning("Harap isi semua kolom.")
                    is_valid = False
                else:
                    new_wilayah_clean = new_wilayah.strip()
                    new_wilayah_clean = re.sub(r'\s*-\s*', '-', new_wilayah_clean)

                    new_mux_clean = new_mux.strip()
                    new_siaran_list = [s.strip() for s in new_siaran_input.split(",") if s.strip()]
                    
                    is_valid = True 
                    
                    wilayah_pattern = r"^[a-zA-Z\s]+-\d+$" 
                    if not re.fullmatch(wilayah_pattern, new_wilayah_clean):
                        st.error("Format **Wilayah Layanan** tidak valid. Harap gunakan format 'Nama Provinsi-Angka'. Contoh: 'Jawa Timur-1', 'DKI Jakarta-2'.")
                        is_valid = False
                    else:
                        wilayah_parts = new_wilayah_clean.split('-')
                        if len(wilayah_parts) > 1:
                            provinsi_from_wilayah = '-'.join(wilayah_parts[:-1]).strip()
                            if provinsi_from_wilayah.lower() != selected_provinsi.lower():
                                st.error(f"Nama provinsi '{provinsi_from_wilayah}' dalam **Wilayah Layanan** tidak cocok dengan **Provinsi** yang dipilih ('{selected_provinsi}').")
                                is_valid = False
                        else:
                            st.error("Format **Wilayah Layanan** tidak lengkap (tidak ada tanda hubung dan angka).")
                            is_valid = False
                            
                    mux_pattern = r"^UHF\s+\d{1,3}\s*-\s*.+$"
                    if not re.fullmatch(mux_pattern, new_mux_clean, re.IGNORECASE):
                        st.error("Format **Penyelenggara MUX** tidak valid. Harap gunakan format 'UHF XX - Nama MUX'. Contoh: 'UHF 27 - Metro TV'.")
                        is_valid = False

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
                            users_ref = db.reference(f"users/{updater_username}")
                            updater_data = users_ref.get()
                            updater_name = updater_data.get("nama", updater_username)
                            
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
                            
                            current_points = updater_data.get("points", 0)
                            users_ref.update({"points": current_points + 5})
                            db.reference("app_metadata/last_leaderboard_update_timestamp").set(now_wib.strftime("%Y-%m-%d %H:%M:%S"))
                            st.toast("Anda mendapatkan 5 poin untuk pembaruan ini!")

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

def display_profile_page():
    """Menampilkan halaman profil pengguna yang sedang login."""
    st.header("👤 Profil Saya")

    if not st.session_state.login:
        st.warning("Anda harus login untuk melihat profil Anda.")
        switch_page("login")
        return

    username = st.session_state.username
    user_ref = db.reference(f"users/{username}")
    user_data = user_ref.get()

    if not user_data:
        st.error("Data profil tidak ditemukan.")
        if st.button("Kembali ke Beranda"):
            switch_page("beranda")
        return

    st.subheader(f"Nama: {user_data.get('nama', 'N/A')}")
    st.write(f"Email: {user_data.get('email', 'N/A')}")
    st.write(f"**Poin Anda:** {user_data.get('points', 0)} ⭐")

    st.markdown("---")
    st.subheader("Informasi Lokasi dan Perangkat TV Digital")

    provinsi_data = db.reference("provinsi").get()
    provinsi_list = sorted(provinsi_data.values()) if provinsi_data else []
    
    current_provinsi = user_data.get('provinsi', None)
    current_wilayah = user_data.get('wilayah', '')
    current_tv_brand = user_data.get('tv_brand', '')
    current_stb_brand = user_data.get('stb_brand', '')
    current_antenna_brand = user_data.get('antenna_brand', '')

    with st.form("profile_form"):
        default_provinsi_index = 0
        if current_provinsi in provinsi_list:
            default_provinsi_index = provinsi_list.index(current_provinsi) + 1 

        new_provinsi = st.selectbox("Provinsi Anda", options=[""] + provinsi_list, index=default_provinsi_index, key="profile_provinsi")
        new_wilayah = st.text_input("Wilayah Layanan Anda", value=current_wilayah, key="profile_wilayah")
        new_tv_brand = st.text_input("Merk TV Anda", value=current_tv_brand, key="profile_tv_brand")
        new_stb_brand = st.text_input("Merk STB Anda", value=current_stb_brand, key="profile_stb_brand")
        new_antenna_brand = st.text_input("Merk Antena Anda", value=current_antenna_brand, key="profile_antenna_brand")

        submitted = st.form_submit_button("Simpan Perubahan Profil")
        if submitted:
            updates = {
                "provinsi": new_provinsi,
                "wilayah": new_wilayah.strip(),
                "tv_brand": new_tv_brand.strip(),
                "stb_brand": new_stb_brand.strip(),
                "antenna_brand": new_antenna_brand.strip()
            }
            try:
                user_ref.update(updates)
                st.success("Profil berhasil diperbarui!")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Gagal memperbarui profil: {e}")

    if st.button("⬅️ Kembali ke Beranda"):
        switch_page("beranda")
        st.rerun()

def display_other_users_page():
    """Menampilkan daftar pengguna lain dan memungkinkan untuk melihat profil mereka."""
    st.header("👥 Profil Pengguna Lain")

    if not st.session_state.login:
        st.warning("Anda harus login untuk melihat profil pengguna lain.")
        switch_page("login")
        return

    all_users = db.reference("users").get() or {}
    
    other_users = {
        username: data for username, data in all_users.items() 
        if username != st.session_state.username
    }

    if not other_users:
        st.info("Tidak ada pengguna lain yang terdaftar saat ini.")
        if st.button("⬅️ Kembali ke Beranda"):
            switch_page("beranda")
        return

    user_display_names = ["Pilih Pengguna"] + sorted([data.get('nama', username) for username, data in other_users.items()])
    
    selected_display_name = st.selectbox(
        "Pilih Pengguna untuk Dilihat Profilnya", 
        user_display_names,
        key="select_other_user"
    )

    selected_username = None
    if selected_display_name != "Pilih Pengguna":
        for username, data in other_users.items():
            if data.get('nama', username) == selected_display_name:
                selected_username = username
                break

    st.session_state.selected_other_user = selected_username

    if st.session_state.selected_other_user:
        st.markdown("---")
        st.subheader(f"Profil dari {selected_display_name}")
        
        selected_user_data = all_users.get(st.session_state.selected_other_user)

        if selected_user_data:
            st.write(f"**Nama:** {selected_user_data.get('nama', 'N/A')}")
            st.write(f"**Poin:** {selected_user_data.get('points', 0)} ⭐")
            st.write(f"**Provinsi:** {selected_user_data.get('provinsi', 'N/A')}")
            st.write(f"**Wilayah Layanan:** {selected_user_data.get('wilayah', 'N/A')}")
            st.write(f"**Merk TV:** {selected_user_data.get('tv_brand', 'N/A')}")
            st.write(f"**Merk STB:** {selected_user_data.get('stb_brand', 'N/A')}")
            st.write(f"**Merk Antena:** {selected_user_data.get('antenna_brand', 'N/A')}")
        else:
            st.warning("Data profil pengguna yang dipilih tidak ditemukan.")
    
    st.markdown("---")
    if st.button("⬅️ Kembali ke Beranda"):
        st.session_state.selected_other_user = None
        switch_page("beranda")
        st.rerun()

def display_comments_section(provinsi, wilayah, mux_key):
    """
    Menampilkan bagian komentar untuk MUX tertentu dan memungkinkan pengguna menambah komentar.
    """
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

    # MODIFIKASI DIMULAI DI SINI
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
                        db.reference("app_metadata/last_leaderboard_update_timestamp").set(now_wib.strftime("%Y-%m-%d %H:%M:%S"))
                        
                        st.session_state.comment_success_message = "Komentar berhasil dikirim dan Anda mendapatkan 1 poin!"
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal mengirim komentar: {e}")
                else:
                    st.warning("Komentar tidak boleh kosong.")
    else: # Jika belum login
        if not comments_list: # Jika belum login DAN belum ada komentar
            st.info("Belum ada komentar untuk MUX ini. Login untuk dapat menulis komentar!")
        else: # Jika belum login TAPI sudah ada komentar
            st.info("Login untuk dapat menulis komentar.")
    # MODIFIKASI BERAKHIR DI SINI

    st.markdown("---")
    if comments_list:
        st.write("### Komentar Sebelumnya:")
        for comment in comments_list:
            st.markdown(f"**{comment['nama_pengguna']}** ({comment['timestamp']}):")
            st.write(comment['text'])
            st.markdown("---")

def display_leaderboard_page():
    """Menampilkan halaman leaderboard kontributor."""
    st.header("🏆 Leaderboard Kontributor")

    all_users = db.reference("users").get() or {}
    
    leaderboard_data = []
    for username, data in all_users.items():
        # Hanya tampilkan pengguna yang memiliki poin > 0
        if data.get("points", 0) > 0:
            leaderboard_data.append({
                "nama": data.get("nama", username),
                "username": username,
                "points": data.get("points", 0)
            })
    
    leaderboard_data.sort(key=lambda x: x["points"], reverse=True)

    # Dapatkan waktu saat ini dalam WIB
    now_wib = datetime.now(WIB)
    update_time_str = now_wib.strftime("%d-%m-%Y %H:%M:%S WIB")

    if leaderboard_data:
        st.write("Berikut adalah daftar kontributor teratas berdasarkan poin:")
        
        leaderboard_df = pd.DataFrame(leaderboard_data)
        leaderboard_df.index = leaderboard_df.index + 1
        st.dataframe(leaderboard_df[["nama", "points"]].rename(columns={"nama": "Nama Kontributor", "points": "Poin"}), use_container_width=True)
        
        # Tambahkan keterangan waktu update
        st.markdown(f"<p style='font-size: small; color: grey;'>Data diperbarui pada: {update_time_str}</p>", unsafe_allow_html=True)
    else:
        st.info("Belum ada kontributor dengan poin yang tercatat.")
    
    st.markdown("---")
    if st.button("⬅️ Kembali ke Beranda"):
        switch_page("beranda")
        st.rerun()

# --- ROUTING HALAMAN UTAMA APLIKASI ---

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
