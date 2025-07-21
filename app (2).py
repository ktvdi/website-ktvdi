import streamlit as st
import json
import os
import firebase_admin
import hashlib
import smtplib
import random
import re
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from firebase_admin import credentials, db
from datetime import datetime
from pytz import timezone
from fpdf import FPDF

st.session_state.setdefault("login", False)
st.session_state.setdefault("lupa_password", False)
st.session_state.setdefault("password_reset_success", False)
st.session_state.setdefault("otp_sent", False)
st.session_state.setdefault("otp_code", "")
st.session_state.setdefault("reset_username", "")
st.session_state.setdefault("login_attempted", False)
st.session_state.setdefault("login_error", "")

st.title("🇮🇩 Aplikasi Karang Taruna Bina Bhakti")


def generate_otp():
    return str(random.randint(100000, 999999))

def send_otp_email(receiver_email, otp):
    sender = st.secrets["email"]["sender"]
    app_password = st.secrets["email"]["app_password"]

    msg = MIMEText(f"Kode OTP untuk reset password Anda: {otp}")
    msg["Subject"] = "Kode OTP Reset Password"
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

def send_newotp_email(receiver_email, otp):
    sender = st.secrets["email"]["sender"]
    app_password = st.secrets["email"]["app_password"]

    msg = MIMEText(f"Kode OTP untuk Pendaftaran Akun Anda: {otp}")
    msg["Subject"] = "Kode OTP Pendaftaran Akun Karang Taruna Bina Bhakti"
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

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Zona Waktu Indonesia
wib = timezone("Asia/Jakarta")

if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["FIREBASE"]))
    firebase_admin.initialize_app(cred, {
        "databaseURL": "https://lomba-17an-default-rtdb.firebaseio.com/"
    })

# Session Init
if "login" not in st.session_state:
    st.session_state.login = False
    st.session_state.username = ""
if "login_error" not in st.session_state:
    st.session_state.login_error = ""
if "lupa_password" not in st.session_state:
    st.session_state.lupa_password = False
if "login_attempted" not in st.session_state:
    st.session_state.login_attempted = False
if "login_triggered" not in st.session_state:
    st.session_state.login_triggered = False

if not st.session_state.login_triggered:
    st.session_state.login_error = ""
    st.session_state.login_attempted = False
else:
    st.session_state.login_triggered = False

# Admin Akun Default
# Ambil data users dari Firebase
users_ref = db.reference("users")
users = users_ref.get() or {}

# Tambahkan field email jika belum ada
for uname, udata in users.items():
    if "email" not in udata:
        users[uname]["email"] = ""  # atau None

# Simpan kembali ke Firebase
users_ref.set(users)

def proses_login():
    user = st.session_state.get("login_user","").strip()
    pw = st.session_state.get("login_pass","").strip()
    st.session_state.login_triggered = True
    st.session_state.login_attempted = True
    if not user or not pw:
        st.session_state.login_error = "Username dan password tidak boleh kosong."
        return

    if user in users and users[user]["password"] == hash_password(pw):
        st.session_state.login = True
        st.session_state.username = user
        st.session_state.login_error = ""
        st.session_state.login_attempted = False
    else:
        st.session_state.login_error = "Username atau password salah."

# Login/Register
if not st.session_state.get("login"):
    # Tampilkan selectbox hanya jika tidak dalam mode lupa password atau reset OTP
    if not st.session_state.get("lupa_password", False) and not st.session_state.get("otp_sent", False):
        mode = st.selectbox("Pilih", ["Login", "Daftar Akun"])
        st.session_state.mode = mode  # simpan mode agar tidak hilang saat rerun
    else:
        mode = st.session_state.get("mode", "Login")  # ambil dari session_state

    if mode != "Login":
        st.session_state.lupa_password = False
        st.session_state.password_reset_success = False
        st.session_state.otp_sent = False
        st.session_state.otp_code = ""
        st.session_state.reset_username = ""

    if mode == "Login":
        if not st.session_state.lupa_password:
            st.header("Login Anggota Karang Taruna")
            st.text_input("Username", key="login_user")
            st.text_input("Password", type="password", key="login_pass")
            user_input = st.session_state.get("login_user", "")
            pass_input = st.session_state.get("login_pass", "")
            st.button("Login", on_click=proses_login)

            if st.session_state.login_attempted and st.session_state.login_error:
                st.toast(st.session_state.login_error)

            if st.button("Lupa Password?"):
                st.session_state.lupa_password = True
                st.rerun()
        else:
            st.header("Reset Password")

            if not st.session_state.otp_sent:
                lupa_nama = st.text_input("Nama Lengkap")
                username = st.text_input("Username")

                if st.button("Kirim OTP ke Email"):
                    if not lupa_nama or not username:
                        st.toast("Semua kolom harus diisi.")
                    elif username not in users:
                        st.error("Username tidak ditemukan.")
                    elif users[username]["nama"].strip().lower() != lupa_nama.strip().lower():
                        st.error("Nama lengkap tidak cocok dengan data.")
                    else:
                        otp = generate_otp()
                        if send_otp_email(users[username]["email"], otp):
                            st.session_state.otp_code = otp
                            st.session_state.reset_username = username
                            st.session_state.otp_sent = True
                            st.success(f"Kode OTP telah dikirim ke {users[username]['email']}.")
                            time.sleep(2)
                            st.rerun()

                if st.button("❌ Batalkan"):
                    st.session_state.lupa_password = False
                    st.rerun()
            else:
                # Tahap 2: Verifikasi OTP dan ganti password
                input_otp = st.text_input("Masukkan Kode OTP")
                new_pw = st.text_input("Password Baru", type="password")

                if st.button("Reset Password"):
                    if input_otp != st.session_state.otp_code:
                        st.error("Kode OTP salah.")
                    elif not new_pw:
                        st.error("Password tidak boleh kosong.")
                    else:
                        username = st.session_state.reset_username
                        db.reference("users").child(username).update({
                            "password": hash_password(new_pw)
                        })
                        st.success("Password berhasil direset. Silakan login kembali.")
                        st.session_state.password_reset_success = True
                        st.session_state.lupa_password = False
                        st.session_state.otp_sent = False
                        st.session_state.otp_code = ""
                        st.session_state.reset_username = ""
                        time.sleep(3)
                        st.rerun()

                if st.button("❌ Batalkan"):
                    st.session_state.lupa_password = False
                    st.session_state.otp_sent = False
                    st.session_state.otp_code = ""
                    st.session_state.reset_username = ""
                    st.rerun()

    elif mode == "Daftar Akun":
        st.header("Daftar Akun Baru")
        full_name = st.text_input("Nama Lengkap")
        new_email = st.text_input("Email:", key="email_input")
        user = st.text_input("Username Baru (huruf kecil/angka tanpa spasi)")
        pw = st.text_input("Password Baru", type="password")
        kode = st.text_input("Kode Undangan")

        if not st.session_state.get("otp_sent_daftar"):
            if st.button("Kirim OTP ke Email"):
                users_ref = db.reference("users")
                users = users_ref.get() or {}
                invite_ref = db.reference("invite")
                invite = invite_ref.get() or {"aktif": ""}
                if not user or not pw or not kode or not new_email:
                    st.toast("Semua kolom harus diisi.")
                elif any(u.get("email", "").lower() == new_email.lower() for u in users.values()):
                    st.toast("❌ Email sudah digunakan oleh pengguna lain.")
                elif not user.isalnum() or not user.islower() or " " in user:
                    st.toast("Username hanya boleh huruf kecil dan angka tanpa spasi.")
                elif user in users:
                    st.toast("Username sudah ada.")
                elif kode != invite["aktif"]:
                    st.toast("Kode undangan tidak valid.")
                else:
                    otp = generate_otp()
                    if send_newotp_email(new_email, otp):
                        st.session_state.otp_sent_daftar = True
                        st.session_state.otp_code_daftar = otp
                        st.success("Kode OTP telah dikirim ke email anda.")
                    else:
                        st.error("Gagal mengirim OTP.")
        if st.session_state.get("otp_sent_daftar"):
            input_otp = st.text_input("Masukkan Kode OTP")
            if st.button("Daftar"):
                if input_otp != st.session_state.get("otp_code_daftar", ""):
                    st.error("Kode OTP salah.")
                elif not user or not pw or not kode or not new_email or not full_name:
                    st.error("Semua kolom harus diisi.")
                else:
                    db.reference("users").child(user).set({
                        "nama": full_name,
                        "password": hash_password(pw),
                        "email": new_email
                    })
                    st.success("Akun berhasil dibuat. Silakan login.")
                    # Reset session
                    st.session_state.otp_sent_daftar = False
                    st.session_state.otp_code_daftar = ""
                    st.session_state.update({"Pilih": "Login", "mode": "Login"})
                    st.stop()

def proses_logout():
    st.session_state.login = False
    st.session_state.username = ""
    st.session_state.login_error = False

# Sidebar
username = st.session_state.get("username")
is_logged_in = st.session_state.get("login", False)

if is_logged_in and username:
    users_ref = db.reference("users")
    users = users_ref.get() or {}
    user_data = users.get(username, {})

    nama_pengguna = user_data.get("nama", username)
    st.sidebar.title(f"Hai, {nama_pengguna}!")

    if not user_data.get("email"):
        st.sidebar.warning("💡 Masukkan email untuk keamanan akun Anda.")
        new_email = st.sidebar.text_input("Masukkan email:")
        if st.sidebar.button("Simpan Email"):
            if not new_email:
                st.sidebar.error("❌ Email tidak boleh kosong.")
            elif not re.match(r"[^@]+@[^@]+\.[^@]+", new_email):
                st.sidebar.error("❌ Format email tidak valid.")
            elif any(
                u != username and udata.get("email", "").lower() == new_email.lower()
                for u, udata in users.items()
            ):
                st.sidebar.error("❌ Email sudah digunakan oleh pengguna lain.")
            else:
                users_ref.child(username).update({"email": new_email})
                st.sidebar.success("✅ Email berhasil disimpan.")
                st.rerun()  # reload setelah simpan email

    else:
        st.sidebar.button("Logout", on_click=proses_logout)

        # Admin Panel
        if username == "admin":
            st.sidebar.title("Admin Panel")
            kode_baru = st.sidebar.text_input("Kode Undangan Baru")
            if st.sidebar.button("Perbarui Kode"):
                invite_ref = db.reference("invite")
                invite_ref.set({"aktif": kode_baru})
                st.sidebar.success("Kode diperbarui")

        menu = st.sidebar.selectbox("Menu", ["Manajemen Anggota", "Manajemen Lomba"])

        # Mulai isi halaman
        if menu == "Manajemen Anggota":
            acara_ref = db.reference("acara")
            acara = acara_ref.get() or []

            absen_ref = db.reference("absensi")
            absen = absen_ref.get() or {}

            if username == "admin":
                mode = st.selectbox("Pilih", ["Buat Acara", "Daftar Acara", "Kehadiran"])

                if mode == "Buat Acara":
                    st.header("Buat Acara")
                    judul = st.text_input("Judul Acara")
                    waktu_str = st.text_input("Tanggal & Jam (dd-mm-yyyy hh:mm)")
                    kode = st.text_input("Kode Absensi")

                    if st.button("Simpan Acara"):
                        try:
                            waktu = datetime.strptime(waktu_str, "%d-%m-%Y %H:%M")
                            acara.append({
                                "judul": judul,
                                "waktu": waktu.strftime("%d-%m-%Y %H:%M"),
                                "kode": kode
                            })
                            db.reference("acara").set(acara)
                            st.success("Acara dibuat.")
                        except:
                            st.error("Format waktu salah.")

                elif mode == "Daftar Acara":
                    st.header("Filter Absensi Berdasarkan Tanggal")
                    tgl_awal = st.date_input("Dari Tanggal")
                    tgl_akhir = st.date_input("Sampai Tanggal")

                    for i, ac in enumerate(acara):
                        waktu_acara = datetime.strptime(ac["waktu"], "%d-%m-%Y %H:%M")
                        if tgl_awal <= waktu_acara.date() <= tgl_akhir:
                            key = f"{ac['judul']} - {ac['waktu']}"
                            daftar = absen.get(key, [])

                            st.subheader(key)
                            with st.expander(f"📌 {len(daftar)} orang hadir"):
                                if daftar:
                                    for username in daftar:
                                        nama_lengkap = users.get(username, {}).get("nama", f"{username} (nama tidak ditemukan)")
                                        st.write(f"✅ {nama_lengkap}")
                                else:
                                    st.info("Belum ada yang absen.")

                            col1, col2 = st.columns([1, 1])
                            with col1:
                                if st.button("Edit", key=f"edit_{i}"):
                                    st.session_state.editing_index = i
                            with col2:
                                if st.button("Hapus", key=f"hapus_{i}"):
                                    st.session_state.hapus_index = i
                                    st.rerun()

                            if st.session_state.get("hapus_index") == i:
                                acara.pop(i)
                                db.reference("acara").set(acara)
                                st.session_state.hapus_index = None
                                st.rerun()

                            if st.session_state.get("editing_index") == i:
                                st.markdown("**✏️ Edit Acara:**")

                                new_judul = st.text_input("Judul Baru", value=ac["judul"], key=f"judul_{i}")
                                new_waktu = st.text_input("Waktu Baru (dd-mm-yyyy hh:mm)", value=ac["waktu"], key=f"waktu_{i}")
                                new_kode = st.text_input("Kode Baru", value=ac["kode"], key=f"kode_{i}")

                                if st.session_state.get("edit_error") == i:
                                    st.error("❌ Format waktu salah. Gunakan format: dd-mm-yyyy hh:mm.")

                                def simpan_perubahan():
                                    try:
                                        new_judul = st.session_state[f"judul_{i}"]
                                        new_waktu = st.session_state[f"waktu_{i}"]
                                        new_kode = st.session_state[f"kode_{i}"]

                                        datetime.strptime(new_waktu, "%d-%m-%Y %H:%M")

                                        old_key = f"{acara[i]['judul']} - {acara[i]['waktu']}"
                                        new_key = f"{new_judul} - {new_waktu}"

                                        acara[i]["judul"] = new_judul
                                        acara[i]["waktu"] = new_waktu
                                        acara[i]["kode"] = new_kode
                                        db.reference("acara").set(acara)

                                        absen_data = db.reference("absensi").get() or {}
                                        if old_key in absen_data:
                                            absen_data[new_key] = absen_data.pop(old_key)
                                            db.reference("absensi").set(absen_data)

                                        st.session_state["edit_success"] = True
                                        st.session_state["edit_success_index"] = i
                                    except:
                                        st.session_state["edit_error"] = i

                                st.button("💾 Simpan Perubahan", key=f"simpan_{i}", on_click=simpan_perubahan)

                                if st.session_state.get("edit_success"):
                                    del st.session_state["edit_success"]
                                    del st.session_state["editing_index"]
                                    if "edit_error" in st.session_state:
                                        del st.session_state["edit_error"]
                                    st.rerun()

                elif mode == "Kehadiran":
                    st.header("Persentase Kehadiran")
                    semua_user = [(u, users[u]["nama"]) for u in users if u != "admin"]
                    total_acara = len(acara)
                    for username, full_name in semua_user:
                        hadir = sum(
                            username in absen.get(f"{a['judul']} - {a['waktu']}", [])
                            for a in acara
                        )
                        persen = (hadir / total_acara) * 100 if total_acara else 0
                        st.write(f"{full_name} ({username}): {hadir}/{total_acara} hadir ({persen:.1f}%)")

            else:
                st.header("Absen Kehadiran Hari Ini")
                hari_ini = datetime.now(wib).strftime("%d-%m-%Y")
                aktif = [a for a in acara if a["waktu"].startswith(hari_ini)]

                if not aktif:
                    st.info("Tidak ada acara hari ini.")
                else:
                    pilihan = st.selectbox("Pilih Acara", [f"{a['judul']} - {a['waktu']}" for a in aktif])
                    dipilih = next((a for a in aktif if f"{a['judul']} - {a['waktu']}" == pilihan), None)

                    full_name = users.get(username, {}).get("nama", "")
                    st.text_input("Nama", value=full_name, disabled=True)
                    kode_input = st.text_input("Masukkan Kode Absensi")

                    if st.button("Absen"):
                        if kode_input != dipilih["kode"]:
                            st.error("Kode salah.")
                        else:
                            if pilihan not in absen:
                                absen[pilihan] = []
                            if username in absen[pilihan]:
                                st.warning("Sudah absen.")
                            else:
                                absen[pilihan].append(username)
                                db.reference("absensi").set(absen)
                                st.success("Berhasil absen.")
        elif menu == "Manajemen Lomba":
            st.header("Lomba")
            # Tambahkan logika lomba di sini jika a
