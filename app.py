import streamlit as st
import firebase_admin
import hashlib
import smtplib
import random
import time
from email.mime.text import MIMEText
from firebase_admin import credentials, db
from pytz import timezone

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
        "otp_code_daftar": ""
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
    st.markdown("## ✍️ Tambahkan atau Perbarui Data Siaran")

    provinsi_data = db.reference("provinsi").get()
    if not provinsi_data:
        st.warning("Data provinsi belum tersedia.")
        return

    provinsi_list = sorted(provinsi_data.values())
    provinsi = st.selectbox("Pilih Provinsi", provinsi_list, key="provinsi_input")
    wilayah = st.text_input("Masukkan Wilayah Layanan", placeholder="Contoh: Kalimantan Timur-1")
    mux = st.text_input("Masukkan Penyelenggara MUX", placeholder="Contoh: Metro TV")
    siaran_input = st.text_area(
        "Masukkan Daftar Siaran (pisahkan dengan koma)",
        placeholder="Contoh: Metro TV, Magna Channel, BN Channel"
    )

    if st.button("Simpan Data"):
        if not all([provinsi, wilayah, mux, siaran_input]):
            st.warning("Harap isi semua kolom.")
        else:
            # Membersihkan dan memvalidasi input
            wilayah_clean = wilayah.strip()
            mux_clean = mux.strip()
            siaran_list = sorted([s.strip() for s in siaran_input.split(",") if s.strip()])
            
            if not siaran_list:
                st.warning("Daftar siaran tidak boleh kosong.")
            else:
                try:
                    db.reference(f"siaran/{provinsi}/{wilayah_clean}/{mux_clean}").set(siaran_list)
                    st.success("Data berhasil disimpan!")
                    st.balloons()
                except Exception as e:
                    st.error(f"Gagal menyimpan data: {e}")

def display_manage_data_form(selected_provinsi, selected_wilayah, selected_mux, mux_data):
    """Menampilkan form untuk mengelola (edit/hapus) data siaran."""
    st.markdown("---")
    st.markdown("## ⚙️ Kelola Data Siaran")

    if st.session_state.edit_mode:
        st.subheader("📝 Edit Data Siaran")
        edit_data = st.session_state.edit_data
        
        # Default values for the edit form
        default_wilayah = edit_data.get("wilayah", "")
        default_mux = edit_data.get("mux", "")
        default_siaran = ", ".join(edit_data.get("siaran", []))

        with st.form("edit_form", clear_on_submit=False):
            # Provinsi tidak bisa diubah langsung dari form edit ini, karena struktur data Firebase
            st.text_input("Provinsi", value=selected_provinsi, disabled=True)
            new_wilayah = st.text_input("Wilayah Layanan", value=default_wilayah, key="edit_wilayah")
            new_mux = st.text_input("Penyelenggara MUX", value=default_mux, key="edit_mux")
            new_siaran_input = st.text_area(
                "Daftar Siaran (pisahkan dengan koma)",
                value=default_siaran,
                key="edit_siaran"
            )

            col1, col2 = st.columns(2)
            with col1:
                if st.form_submit_button("Simpan Perubahan"):
                    if not all([new_wilayah, new_mux, new_siaran_input]):
                        st.warning("Harap isi semua kolom.")
                    else:
                        new_wilayah_clean = new_wilayah.strip()
                        new_mux_clean = new_mux.strip()
                        new_siaran_list = sorted([s.strip() for s in new_siaran_input.split(",") if s.strip()])

                        if not new_siaran_list:
                            st.warning("Daftar siaran tidak boleh kosong.")
                        else:
                            try:
                                # Hapus data lama jika ada perubahan di wilayah atau mux
                                if default_wilayah != new_wilayah_clean or default_mux != new_mux_clean:
                                    db.reference(f"siaran/{selected_provinsi}/{default_wilayah}/{default_mux}").delete()
                                    st.toast("Data lama dihapus.")

                                # Simpan data baru
                                db.reference(f"siaran/{selected_provinsi}/{new_wilayah_clean}/{new_mux_clean}").set(new_siaran_list)
                                st.success("Data berhasil diperbarui!")
                                st.session_state.edit_mode = False
                                st.session_state.edit_data = None
                                st.balloons()
                                st.rerun()
                            except Exception as e:
                                st.error(f"Gagal memperbarui data: {e}")
            with col2:
                if st.form_submit_button("Batal Edit"):
                    st.session_state.edit_mode = False
                    st.session_state.edit_data = None
                    st.rerun()
    else:
        st.info("Pilih data di bawah untuk mengedit atau menghapus.")
        # Tampilkan daftar data yang bisa diedit/dihapus
        if mux_data:
            for mux_key, siaran_list in mux_data.items():
                st.subheader(f"📡 {mux_key}")
                for tv in siaran_list:
                    st.write(f"- {tv}")
                
                col_edit_del_1, col_edit_del_2 = st.columns(2)
                with col_edit_del_1:
                    if st.button(f"✏️ Edit {mux_key}", key=f"edit_{selected_provinsi}_{selected_wilayah}_{mux_key}"):
                        st.session_state.edit_mode = True
                        st.session_state.edit_data = {
                            "provinsi": selected_provinsi,
                            "wilayah": selected_wilayah,
                            "mux": mux_key,
                            "siaran": siaran_list
                        }
                        st.rerun()
                with col_edit_del_2:
                    if st.button(f"🗑️ Hapus {mux_key}", key=f"delete_{selected_provinsi}_{selected_wilayah}_{mux_key}"):
                        if st.warning(f"Anda yakin ingin menghapus data {mux_key} di {selected_wilayah}, {selected_provinsi}?"):
                            try:
                                db.reference(f"siaran/{selected_provinsi}/{selected_wilayah}/{mux_key}").delete()
                                st.success(f"Data {mux_key} berhasil dihapus!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Gagal menghapus data: {e}")
                st.markdown("---")
        else:
            st.info("Tidak ada data siaran untuk dikelola di wilayah ini.")

# --- HALAMAN UTAMA APLIKASI ---

st.title("🇮🇩 KOMUNITAS TV DIGITAL INDONEggSIA 🇮🇩")
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
            
            # Add MUX operator filter
            selected_mux = st.selectbox("Pilih Penyelenggara MUX", ["Semua MUX"] + mux_list, key="select_mux")

            if selected_mux == "Semua MUX":
                for mux in mux_list:
                    st.subheader(f"📡 {mux}")
                    for tv in mux_data[mux]:
                        st.write(f"- {tv}")
                    st.markdown("---")
            else:
                st.subheader(f"📡 {selected_mux}")
                for tv in mux_data[selected_mux]:
                    st.write(f"- {tv}")
                st.markdown("---")
        else:
            st.info("Belum ada data siaran untuk provinsi ini.")
    else:
        st.warning("Gagal memuat data provinsi.")

    # Tampilkan form tambah data jika sudah login
    if st.session_state.login:
        display_add_data_form()
    else:
        st.info("Untuk menambahkan atau memperbarui data, silakan login terlebih dahulu.")
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
