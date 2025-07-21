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
st.session_state.setdefault("halaman", "beranda")

st.title("🇮🇩 KOMUNITAS TV DIGITAL INDONESIA 🇮🇩")

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
    msg["Subject"] = "Kode OTP Pendaftaran Akun KTVDI"
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
        "databaseURL": "https://website-ktvdi-default-rtdb.firebaseio.com/"
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

# Atur session state untuk halaman default
if "halaman" not in st.session_state:
    st.session_state["halaman"] = "beranda"
if "login" not in st.session_state:
    st.session_state["login"] = False

if not st.session_state.login_triggered:
    st.session_state.login_error = ""
    st.session_state.login_attempted = False
else:
    st.session_state.login_triggered = False

def halaman_login_daftar():
    users_ref = db.reference("users")
    users = users_ref.get() or {}

    def proses_login():
        user = st.session_state.get("login_user", "").strip()
        pw = st.session_state.get("login_pass", "").strip()

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
            st.session_state["halaman"] = "beranda"
        else:
            st.session_state.login_error = "Username atau password salah."

    # Login/Register UI
    if not st.session_state.get("login"):
        if not st.session_state.get("lupa_password", False) and not st.session_state.get("otp_sent", False):
            mode = st.selectbox("Pilih", ["Login", "Daftar Akun"])
            st.session_state.mode = mode
        else:
            mode = st.session_state.get("mode", "Login")

        if mode != "Login":
            st.session_state.lupa_password = False
            st.session_state.password_reset_success = False
            st.session_state.otp_sent = False
            st.session_state.otp_code = ""
            st.session_state.reset_username = ""

        if mode == "Login":
            if not st.session_state.lupa_password:
                st.header("🔐 Login Akun KTVDI")
                st.text_input("Username", key="login_user")
                st.text_input("Password", type="password", key="login_pass")
                st.button("Login", on_click=proses_login)

                if st.session_state.get("login_attempted") and st.session_state.get("login_error"):
                    st.toast(st.session_state.login_error)

                if st.button("Lupa Password?"):
                    st.session_state.lupa_password = True
                    st.rerun()
            else:
                st.header("Reset Password")
                if not st.session_state.get("otp_sent"):
                    lupa_nama = st.text_input("Nama Lengkap")
                    username = st.text_input("Username")

                    if st.button("Kirim OTP ke Email"):
                        if not lupa_nama or not username:
                            st.toast("Semua kolom harus diisi.")
                        elif username not in users:
                            st.error("Username tidak ditemukan.")
                        elif users[username]["nama"].strip().lower() != lupa_nama.strip().lower():
                            st.error("Nama tidak cocok.")
                        else:
                            otp = generate_otp()
                            if send_otp_email(users[username]["email"], otp):
                                st.session_state.otp_code = otp
                                st.session_state.reset_username = username
                                st.session_state.otp_sent = True
                                st.success(f"OTP dikirim ke {users[username]['email']}")
                                time.sleep(2)
                                st.rerun()

                    if st.button("❌ Batalkan"):
                        st.session_state.lupa_password = False
                        st.rerun()
                else:
                    input_otp = st.text_input("Masukkan Kode OTP")
                    new_pw = st.text_input("Password Baru", type="password")

                    if st.button("Reset Password"):
                        if input_otp != st.session_state.get("otp_code", ""):
                            st.error("OTP salah.")
                        elif not new_pw:
                            st.error("Password tidak boleh kosong.")
                        else:
                            username = st.session_state.reset_username
                            db.reference("users").child(username).update({
                                "password": hash_password(new_pw)
                            })
                            st.success("Password berhasil direset. Silakan login.")
                            st.session_state.update({
                                "lupa_password": False,
                                "otp_sent": False,
                                "otp_code": "",
                                "reset_username": ""
                            })
                            time.sleep(3)
                            st.rerun()

                    if st.button("❌ Batalkan"):
                        st.session_state.update({
                            "lupa_password": False,
                            "otp_sent": False,
                            "otp_code": "",
                            "reset_username": ""
                        })
                        st.rerun()

        elif mode == "Daftar Akun":
            st.header("📝 Daftar Akun Baru")
            full_name = st.text_input("Nama Lengkap")
            new_email = st.text_input("Email:", key="email_input")
            user = st.text_input("Username Baru (huruf kecil/angka tanpa spasi)")
            pw = st.text_input("Password Baru", type="password")

            if not st.session_state.get("otp_sent_daftar"):
                if st.button("Kirim OTP ke Email"):
                    if not user or not pw or not new_email:
                        st.toast("Semua kolom harus diisi.")
                    elif any(u.get("email", "").lower() == new_email.lower() for u in users.values()):
                        st.toast("❌ Email sudah digunakan.")
                    elif not user.isalnum() or not user.islower() or " " in user:
                        st.toast("Gunakan huruf kecil/angka tanpa spasi.")
                    elif user in users:
                        st.toast("Username sudah terdaftar.")
                    else:
                        otp = generate_otp()
                        if send_newotp_email(new_email, otp):
                            st.session_state.otp_sent_daftar = True
                            st.session_state.otp_code_daftar = otp
                            st.success("OTP dikirim ke email.")
                        else:
                            st.error("Gagal mengirim OTP.")

            if st.session_state.get("otp_sent_daftar"):
                input_otp = st.text_input("Masukkan Kode OTP")
                if st.button("Daftar"):
                    if input_otp != st.session_state.get("otp_code_daftar", ""):
                        st.error("OTP salah.")
                    elif not user or not pw or not new_email or not full_name:
                        st.error("Semua kolom harus diisi.")
                    else:
                        db.reference("users").child(user).set({
                            "nama": full_name,
                            "password": hash_password(pw),
                            "email": new_email
                        })
                        st.success("Akun berhasil dibuat. Silakan login.")
                        st.session_state.update({
                            "otp_sent_daftar": False,
                            "otp_code_daftar": "",
                            "Pilih": "Login",
                            "mode": "Login"
                        })
                        st.stop()
    if st.button("⬅️ Kembali ke Beranda"):
        st.session_state["halaman"] = "beranda"
        st.rerun()

if st.session_state["halaman"] == "beranda":
    # Halaman Utama
    st.header("📺 Data Siaran TV Digital di Indonesia")
    # Menampilkan data siaran
    provinsi_data = db.reference("provinsi").get()
    if provinsi_data:
        provinsi_list = sorted(provinsi_data.values())
        selected_provinsi = st.selectbox("Pilih Provinsi", provinsi_list, key="provinsi_filter")
        siaran_data = db.reference(f"siaran/{selected_provinsi}").get()

        if siaran_data:
            wilayah_list = sorted(siaran_data.keys())
            selected_wilayah = st.selectbox("Pilih Wilayah Layanan", wilayah_list)

            mux_data = siaran_data[selected_wilayah]
            mux_list = sorted(mux_data.keys())
            selected_mux = st.selectbox("Pilih Penyelenggara MUX", mux_list)

            st.subheader("📡 Daftar Siaran TV:")
            for tv in mux_data[selected_mux]:
                st.write(f"- {tv}")
        else:
            st.info("Belum ada data wilayah layanan untuk provinsi ini.")
    else:
        st.warning("Belum ada data provinsi.")
    
    if not st.session_state["login"]:
        st.info("Untuk menambahkan data, silakan login terlebih dahulu.")
        if st.button("🔐 Login / Daftar Akun"):
            st.session_state["halaman"] = "login"
            st.rerun()


if st.session_state.get("halaman") == "login":
    halaman_login_daftar()

def proses_logout():
    st.session_state.login = False
    st.session_state.username = ""
    st.session_state.login_error = False

# === Sidebar jika login ===
if st.session_state.get("login"):
    username = st.session_state["username"]
    users = db.reference("users").get() or {}
    user_data = users.get(username, {})
    nama_pengguna = user_data.get("nama", username)

    st.sidebar.title(f"Hai, {nama_pengguna}!")
    st.sidebar.button("🚪 Logout", on_click=proses_logout)

    st.markdown("## ✍️ Tambahkan Data Siaran")

    # Pilih provinsi
    provinsi_data = db.reference("provinsi").get()
    if provinsi_data:
        provinsi_list = sorted(provinsi_data.values())
        provinsi = st.selectbox("Pilih Provinsi", provinsi_list, key="provinsi_input")
    else:
        st.warning("Belum ada data provinsi.")
        provinsi = ""

    # Input wilayah, mux, siaran
    wilayah = st.text_input("Masukkan Wilayah Layanan")
    mux = st.text_input("Masukkan Nama Penyelenggara MUX")
    siaran_input = st.text_area(
        "Masukkan Daftar Siaran (pisahkan dengan koma)",
        placeholder="Contoh: RCTI, SCTV, Indosiar"
    )

    if st.button("Simpan Data"):
        if not (provinsi and wilayah and mux and siaran_input):
            st.warning("Harap isi semua kolom.")
        else:
            siaran_list = [s.strip() for s in siaran_input.split(",") if s.strip()]
            db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").set(siaran_list)
            st.success("Data berhasil disimpan!")
