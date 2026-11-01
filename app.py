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

st.set_page_config(page_title="KTVDI", page_icon="🇮🇩", layout="wide", initial_sidebar_state="collapsed")

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
        "messages": [],
    }
    for key, value in states.items():
        if key not in st.session_state:
            st.session_state[key] = value

# Inisialisasi awal
initialize_firebase()
initialize_session_state()
initialize_gemini()
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

def is_admin(username=None):
    """Memeriksa peran admin dari Firebase: admins/{username} = true."""
    username = username or st.session_state.get("username", "")
    if not username:
        return False
    return db.reference(f"admins/{username}").get() is True

def write_audit_log(action, provinsi, wilayah, mux, before=None, after=None):
    """Mencatat perubahan data siaran untuk riwayat/audit."""
    try:
        username = st.session_state.get("username", "system")
        user_data = db.reference(f"users/{username}").get() or {}
        now = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
        db.reference("audit_logs").push().set({
            "action": action,
            "provinsi": provinsi,
            "wilayah": wilayah,
            "mux": mux,
            "username": username,
            "nama": user_data.get("nama", username),
            "timestamp": now,
            "before": before,
            "after": after
        })
    except Exception as exc:
        st.warning(f"Perubahan tersimpan, tetapi log audit gagal dicatat: {exc}")

def display_report_page():
    """Form laporan koreksi data siaran dari komunitas."""
    st.header("🚩 Laporkan Kesalahan Data Siaran")
    all_data = db.reference("siaran").get() or {}
    options = []
    for prov, wilayah_data in all_data.items():
        for wilayah, mux_data in (wilayah_data or {}).items():
            for mux in (mux_data or {}).keys():
                options.append((prov, wilayah, mux))
    if not options:
        st.info("Belum ada data siaran yang dapat dilaporkan.")
        return
    labels = [f"{p} / {w} / {m}" for p, w, m in options]
    with st.form("report_broadcast_form", clear_on_submit=True):
        selected = st.selectbox("Pilih data yang bermasalah", range(len(options)), format_func=lambda i: labels[i])
        category = st.selectbox("Jenis kesalahan", [
            "Nama kanal salah", "Kanal sudah tidak bersiaran", "MUX/frekuensi salah",
            "Wilayah layanan salah", "Data tidak lengkap", "Lainnya"
        ])
        description = st.text_area("Keterangan / usulan koreksi", placeholder="Jelaskan informasi yang perlu diperbaiki...", max_chars=1500)
        evidence = st.text_input("Tautan bukti (opsional)", placeholder="https://...")
        submitted = st.form_submit_button("Kirim Laporan")
    if submitted:
        if not description.strip():
            st.warning("Mohon isi keterangan laporan.")
        else:
            prov, wilayah, mux = options[selected]
            username = st.session_state.get("username", "anonim")
            user_data = db.reference(f"users/{username}").get() or {}
            db.reference("broadcast_reports").push().set({
                "provinsi": prov, "wilayah": wilayah, "mux": mux,
                "category": category, "description": description.strip(),
                "evidence_url": evidence.strip(),
                "reporter_username": username,
                "reporter_name": user_data.get("nama", username),
                "status": "Menunggu", "admin_note": "", "created_at": datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
            })
            st.success("Laporan berhasil dikirim. Terima kasih membantu menjaga keakuratan data!")

def display_admin_dashboard():
    """Dashboard admin untuk meninjau laporan dan riwayat perubahan."""
    if not st.session_state.get("login") or not is_admin():
        st.error("Halaman ini hanya dapat diakses oleh admin.")
        return
    st.header("🛠️ Dashboard Admin")
    reports = db.reference("broadcast_reports").get() or {}
    pending = {k: v for k, v in reports.items() if v.get("status", "Menunggu") == "Menunggu"}
    st.metric("Laporan menunggu", len(pending))
    if pending:
        st.subheader("Laporan Kesalahan Data")
        for report_id, report in pending.items():
            with st.expander(f"{report.get('provinsi')} / {report.get('wilayah')} / {report.get('mux')} — {report.get('category')}"):
                st.write(report.get("description", ""))
                if report.get("evidence_url", "").startswith(("https://", "http://")):
                    st.markdown(f"[Buka bukti]({report.get('evidence_url')})")
                st.caption(f"Oleh {report.get('reporter_name', report.get('reporter_username', ''))} • {report.get('created_at', '')}")
                admin_note = st.text_input("Catatan admin", value=report.get("admin_note", ""), key=f"report_note_{report_id}")
                status_choice = st.selectbox("Status laporan", ["Menunggu", "Sedang ditinjau", "Selesai", "Ditolak"], index=["Menunggu", "Sedang ditinjau", "Selesai", "Ditolak"].index(report.get("status", "Menunggu")) if report.get("status", "Menunggu") in ["Menunggu", "Sedang ditinjau", "Selesai", "Ditolak"] else 0, key=f"report_status_{report_id}")
                if st.button("Simpan status/catatan", key=f"resolve_report_{report_id}"):
                    db.reference(f"broadcast_reports/{report_id}").update({
                        "status": status_choice, "admin_note": admin_note.strip(),
                        "resolved_by": st.session_state.username,
                        "resolved_at": datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
                    })
                    write_audit_log("update_report_status", report.get("provinsi", ""), report.get("wilayah", ""), report.get("mux", ""), before=report, after={"status": status_choice, "admin_note": admin_note.strip()})
                    st.rerun()
    else:
        st.info("Tidak ada laporan yang menunggu ditinjau.")
    st.subheader("Semua Laporan")
    if reports:
        report_rows = []
        for rid, r in reports.items():
            report_rows.append({"Status": r.get("status", "Menunggu"), "Provinsi": r.get("provinsi"), "Wilayah": r.get("wilayah"), "MUX": r.get("mux"), "Jenis": r.get("category"), "Pelapor": r.get("reporter_name"), "Waktu": r.get("created_at"), "Keterangan": r.get("description")})
        st.dataframe(pd.DataFrame(report_rows), use_container_width=True, hide_index=True)
    st.subheader("🧾 Riwayat Perubahan (Audit Log)")
    logs = db.reference("audit_logs").get() or {}
    if logs:
        rows = []
        for log in sorted(logs.values(), key=lambda x: x.get("timestamp", ""), reverse=True):
            rows.append({"Waktu": log.get("timestamp"), "Aksi": log.get("action"), "Pengguna": log.get("nama", log.get("username")), "Provinsi": log.get("provinsi"), "Wilayah": log.get("wilayah"), "MUX": log.get("mux")})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        with st.expander("Lihat detail perubahan"):
            for log_id, log in sorted(logs.items(), key=lambda item: item[1].get("timestamp", ""), reverse=True):
                st.json(log)
    else:
        st.info("Belum ada riwayat perubahan.")
    display_restore_history()

def get_all_broadcast_rows():
    """Flatten data siaran untuk pencarian, statistik, dan peta."""
    all_data = db.reference("siaran").get() or {}
    rows = []
    for prov, areas in (all_data or {}).items():
        for wilayah, muxes in (areas or {}).items():
            for mux, details in (muxes or {}).items():
                if isinstance(details, list):
                    details = {"siaran": details}
                details = details or {}
                channels = details.get("siaran", []) or []
                rows.append({"provinsi": prov, "wilayah": wilayah, "mux": mux,
                             "siaran": channels, "detail": details,
                             "latitude": details.get("latitude"), "longitude": details.get("longitude")})
    return rows


def display_global_search():
    if st.button("⬅️ Kembali ke Beranda", key="back_global_search"):
        switch_page("beranda"); st.rerun()
    st.header("🔎 Pencarian Siaran Global")
    query = st.text_input("Cari kanal, MUX, wilayah, atau provinsi", placeholder="Contoh: TVRI, UHF 27, Jawa Barat").strip().casefold()
    rows = get_all_broadcast_rows()
    if not query:
        st.caption(f"Tersedia {sum(len(r['siaran']) for r in rows)} kanal pada {len(rows)} MUX. Masukkan kata kunci untuk mencari.")
        return
    matches = []
    for r in rows:
        searchable = " ".join([r["provinsi"], r["wilayah"], r["mux"], " ".join(map(str, r["siaran"]))]).casefold()
        if query in searchable:
            matches.append(r)
    st.write(f"Ditemukan **{len(matches)}** MUX yang cocok.")
    if not matches:
        st.info("Tidak ada hasil. Coba kata kunci lain.")
    for r in matches:
        with st.expander(f"📡 {r['mux']} — {r['wilayah']}, {r['provinsi']}"):
            st.write("**Daftar kanal:** " + (", ".join(map(str, r["siaran"])) if r["siaran"] else "Belum tersedia"))
            st.caption(f"Pembaruan terakhir: {r['detail'].get('last_updated_date', 'N/A')} {r['detail'].get('last_updated_time', '')}")


def display_digital_statistics():
    """Statistik publik, tidak memerlukan login."""
    if st.button("⬅️ Kembali ke Beranda", key="back_digital_stats"):
        switch_page("beranda"); st.rerun()
    st.header("📊 Statistik TV Digital Indonesia")
    rows = get_all_broadcast_rows()
    provinces = {r["provinsi"] for r in rows}
    areas = {(r["provinsi"], r["wilayah"]) for r in rows}
    channels = {str(c).strip().casefold() for r in rows for c in r["siaran"] if str(c).strip()}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Provinsi dengan data", len(provinces))
    c2.metric("Wilayah layanan", len(areas))
    c3.metric("MUX terdata", len(rows))
    c4.metric("Nama kanal unik", len(channels))
    if rows:
        df = pd.DataFrame([{"Provinsi": r["provinsi"], "Wilayah": r["wilayah"], "MUX": r["mux"], "Jumlah kanal": len(r["siaran"])} for r in rows])
        st.subheader("MUX dan kanal per provinsi")
        summary = df.groupby("Provinsi", as_index=False).agg({"MUX": "count", "Jumlah kanal": "sum"}).sort_values("MUX", ascending=False)
        st.bar_chart(summary.set_index("Provinsi")["MUX"])
        st.dataframe(summary, use_container_width=True, hide_index=True)
    else:
        st.info("Belum ada data siaran untuk dihitung.")


def display_notifications():
    if st.button("⬅️ Kembali ke Beranda", key="back_notifications"):
        switch_page("beranda"); st.rerun()
    st.header("🔔 Perubahan Data Siaran Terbaru")
    logs = db.reference("audit_logs").get() or {}
    relevant = [(k, v) for k, v in logs.items() if v.get("action") in {"add_broadcast", "edit_broadcast", "delete_broadcast", "restore_broadcast"}]
    relevant.sort(key=lambda item: item[1].get("timestamp", ""), reverse=True)
    if not relevant:
        st.info("Belum ada perubahan data yang tercatat.")
        return
    for _, log in relevant[:50]:
        action = {"add_broadcast": "menambahkan", "edit_broadcast": "memperbarui", "delete_broadcast": "menghapus", "restore_broadcast": "memulihkan"}.get(log.get("action"), log.get("action", "mengubah"))
        st.markdown(f"**{log.get('mux', 'MUX')}** — {action} oleh **{log.get('nama', log.get('username', 'pengguna'))}**")
        st.caption(f"{log.get('wilayah', '')}, {log.get('provinsi', '')} • {log.get('timestamp', '')}")
        st.divider()


def _uhf_frequency_mhz(mux_name):
    """Perkiraan frekuensi tengah UHF DVB-T2 kanal 21-48; nilai DB eksplisit lebih diutamakan."""
    match = re.search(r"\bUHF\s*(\d{1,3})\b", str(mux_name), re.IGNORECASE)
    if not match:
        return None
    channel = int(match.group(1))
    if not 21 <= channel <= 48:
        return None
    return 474.0 + (channel - 21) * 8.0


def _haversine_km(lat1, lon1, lat2, lon2):
    """Jarak permukaan bumi dalam kilometer."""
    from math import radians, sin, cos, asin, sqrt
    radius_km = 6371.0088
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radius_km * asin(sqrt(min(1, a)))


def _load_signal_measurements():
    """Ambil pengukuran komunitas dan abaikan koordinat/nilai yang tidak valid."""
    raw = db.reference("signal_measurements").get() or {}
    records = []
    for provinsi, areas in raw.items():
        for wilayah, muxes in (areas or {}).items():
            for mux, entries in (muxes or {}).items():
                for measurement_id, item in (entries or {}).items():
                    if not isinstance(item, dict):
                        continue
                    try:
                        lat, lon = float(item["latitude"]), float(item["longitude"])
                        if -11 <= lat <= 6 and 95 <= lon <= 141:
                            record = {
                                **item, "id": measurement_id, "provinsi": provinsi,
                                "wilayah": wilayah, "mux": mux,
                                "latitude": lat, "longitude": lon
                            }
                            try:
                                q = float(record.get("quality"))
                                record["_quality_num"] = q if 0 <= q <= 100 else None
                            except (TypeError, ValueError):
                                record["_quality_num"] = None
                            records.append(record)
                    except (KeyError, TypeError, ValueError):
                        continue
    records.sort(key=lambda x: str(x.get("created_at") or x.get("timestamp", "")), reverse=True)
    return records


def _parse_measurement_datetime(record):
    """Parse waktu ISO atau format tampilan WIB yang dipakai data lama."""
    from datetime import datetime
    raw = record.get("created_at") or record.get("timestamp")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace(" WIB", ""))
        # Normalisasi ke waktu lokal-naive agar kompatibel dengan cutoff filter periode.
        return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed
    except (TypeError, ValueError):
        return None


def _estimate_tv_signal(tx, distance_km, frequency_mhz, erp_watt, tx_height_m,
                        rx_height_m, rx_gain_dbi, system_loss_db, model_name):
    """
    Estimasi kasar level daya terima. Hata hanya dipakai dalam rentang validnya;
    selain itu kembali ke FSPL. Bukan model terrain-aware atau prediksi coverage resmi.
    """
    from math import log10
    distance_km = max(float(distance_km), 0.05)
    frequency_mhz = float(frequency_mhz)
    erp_watt = max(float(erp_watt), 0.001)
    eirp_dbm = 10 * log10(erp_watt * 1000.0) + 2.15
    selected_model = "FSPL"
    path_loss_db = 32.44 + 20 * log10(frequency_mhz) + 20 * log10(distance_km)

    if model_name == "Hata (perkotaan)" and 150 <= frequency_mhz <= 1500 and 1 <= distance_km <= 20 and 30 <= tx_height_m <= 200 and 1 <= rx_height_m <= 10:
        log_f = log10(frequency_mhz)
        log_hm = log10(rx_height_m)
        correction = (1.1 * log_f - 0.7) * rx_height_m - (1.56 * log_f - 0.8)
        path_loss_db = (69.55 + 26.16 * log_f - 13.82 * log10(tx_height_m)
                        - correction + (44.9 - 6.55 * log10(tx_height_m)) * log10(distance_km))
        selected_model = "Okumura-Hata perkotaan"
    elif model_name == "Hata (pinggiran kota)" and 150 <= frequency_mhz <= 1500 and 1 <= distance_km <= 20 and 30 <= tx_height_m <= 200 and 1 <= rx_height_m <= 10:
        log_f = log10(frequency_mhz)
        log_hm = log10(rx_height_m)
        correction = (1.1 * log_f - 0.7) * rx_height_m - (1.56 * log_f - 0.8)
        urban_loss = (69.55 + 26.16 * log_f - 13.82 * log10(tx_height_m)
                      - correction + (44.9 - 6.55 * log10(tx_height_m)) * log10(distance_km))
        path_loss_db = urban_loss - 2 * (log10(frequency_mhz / 28) ** 2) - 5.4
        selected_model = "Okumura-Hata pinggiran kota"
    received_dbm = eirp_dbm - path_loss_db + float(rx_gain_dbi) - float(system_loss_db)
    return {
        "received_dbm": received_dbm, "path_loss_db": path_loss_db,
        "eirp_dbm": eirp_dbm, "model": selected_model
    }


def display_broadcast_map():
    if st.button("⬅️ Kembali ke Beranda", key="back_broadcast_map"):
        switch_page("beranda")
        st.rerun()

    st.header("🗺️ Peta Pemancar & Kualitas Sinyal TV Digital")
    st.markdown(
        "Peta menggabungkan lokasi pemancar, estimasi propagasi, dan laporan penerimaan "
        "aktual komunitas. Gunakan filter untuk membandingkan MUX dan periode pengukuran."
    )
    st.warning(
        "Peta hasil pengukuran bukan peta prediksi. Strength/Quality/SNR/BER tetap harus "
        "dimasukkan dari menu TV/STB. Model propagasi di halaman ini tidak memakai DEM "
        "elevasi, profil bukit, gedung, interferensi, atau pola antena; hasilnya indikatif, "
        "bukan jaminan cakupan maupun pengganti pengukuran lapangan."
    )

    rows = get_all_broadcast_rows()
    located = []
    for r in rows:
        try:
            lat, lon = float(r["latitude"]), float(r["longitude"])
            if -11 <= lat <= 6 and 95 <= lon <= 141:
                located.append({**r, "latitude": lat, "longitude": lon})
        except (TypeError, ValueError, KeyError):
            continue
    measurements = _load_signal_measurements()
    logged_in = bool(st.session_state.get("login"))
    admin_can_manage = logged_in and is_admin()

    # Filter bersama untuk peta, ringkasan, dan grafik.
    st.subheader("🔎 Filter peta dan analisis")
    f1, f2, f3 = st.columns(3)
    province_options = ["Semua provinsi"] + sorted({str(r.get("provinsi", "")) for r in rows if r.get("provinsi")})
    selected_province = f1.selectbox("Provinsi", province_options, key="map_filter_province")
    mux_options = ["Semua MUX"] + sorted({str(r.get("mux", "")) for r in rows if r.get("mux")})
    selected_mux_filter = f2.selectbox("MUX", mux_options, key="map_filter_mux")
    display_mode = f3.selectbox(
        "Lapisan pengukuran", ["Titik pengukuran", "Heatmap kualitas", "Titik + heatmap"],
        key="map_measurement_layer"
    )
    days_filter = st.selectbox(
        "Periode laporan", ["Semua waktu", "7 hari terakhir", "30 hari terakhir", "90 hari terakhir"],
        key="map_filter_period"
    )

    filtered_rows = [
        r for r in rows
        if (selected_province == "Semua provinsi" or r.get("provinsi") == selected_province)
        and (selected_mux_filter == "Semua MUX" or r.get("mux") == selected_mux_filter)
    ]
    filtered_located = [
        r for r in located
        if (selected_province == "Semua provinsi" or r.get("provinsi") == selected_province)
        and (selected_mux_filter == "Semua MUX" or r.get("mux") == selected_mux_filter)
    ]
    filtered_measurements = [
        m for m in measurements
        if (selected_province == "Semua provinsi" or m.get("provinsi") == selected_province)
        and (selected_mux_filter == "Semua MUX" or m.get("mux") == selected_mux_filter)
    ]
    if days_filter != "Semua waktu":
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=int(days_filter.split()[0]))
        filtered_measurements = [
            m for m in filtered_measurements
            if (_parse_measurement_datetime(m) is not None and _parse_measurement_datetime(m) >= cutoff)
        ]

    good_count = sum(1 for m in filtered_measurements if m.get("_quality_num") is not None and m["_quality_num"] >= 70)
    medium_count = sum(1 for m in filtered_measurements if m.get("_quality_num") is not None and 40 <= m["_quality_num"] < 70)
    poor_count = sum(1 for m in filtered_measurements if m.get("_quality_num") is not None and m["_quality_num"] < 40)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Pemancar berkoordinat", len(filtered_located))
    k2.metric("Laporan terfilter", len(filtered_measurements))
    k3.metric("Quality ≥ 70", good_count)
    k4.metric("Quality < 40", poor_count)
    st.caption(f"Quality sedang (40–69): {medium_count}. Ambang warna adalah kategori visual awal, bukan standar universal lintas perangkat.")

    selected_row = None
    if logged_in and filtered_rows:
        selected_idx = st.selectbox(
            "Pilih MUX untuk laporan dan pengelolaan",
            range(len(filtered_rows)),
            format_func=lambda i: f"{filtered_rows[i].get('provinsi', '')} / {filtered_rows[i].get('wilayah', '')} / {filtered_rows[i].get('mux', '')}",
            key="map_mux_to_position"
        )
        selected_row = filtered_rows[selected_idx]
        if admin_can_manage:
            st.info("Admin dapat mengelola koordinat dan parameter teknis pemancar. Pengguna login dapat mengirim pengukuran.")
        else:
            st.info("Koordinat laporan diambil dari pusat peta yang dipilih pengguna. Periksa posisi sebelum mengirim.")
    elif not logged_in:
        st.caption("Peta dapat dilihat tanpa login. Login diperlukan untuk mengirim laporan pengukuran.")
    elif not filtered_rows:
        st.info("Tidak ada MUX yang cocok dengan filter saat ini.")

    try:
        import folium
        from folium.plugins import HeatMap
        from streamlit_folium import st_folium
        import html

        # Parameter model dipakai bersama oleh heatmap prediksi dan tabel estimasi.
        if filtered_located:
            st.subheader("📡 Pengaturan heatmap prediksi pemancar")
            pc1, pc2, pc3 = st.columns(3)
            model_choice = pc1.selectbox(
                "Model propagasi", ["FSPL (ruang bebas)", "Hata (perkotaan)", "Hata (pinggiran kota)"],
                key="map_path_model"
            )
            rx_height = pc2.number_input("Tinggi antena penerima (m)", min_value=1.0, max_value=30.0,
                value=3.0, step=0.5, key="map_rx_height")
            rx_gain = pc3.number_input("Gain antena penerima (dBi)", min_value=-5.0, max_value=25.0,
                value=8.0, step=0.5, key="map_rx_gain")
            system_loss = st.slider("Rugi kabel/konektor/sistem (dB)", min_value=0.0, max_value=20.0,
                value=3.0, step=0.5, key="map_system_loss")
            prediction_radius_km = st.slider(
                "Radius simulasi dari setiap pemancar (km)", min_value=10, max_value=100,
                value=40, step=5, key="map_prediction_radius"
            )
            environment = model_choice.replace("FSPL (ruang bebas)", "FSPL")
        else:
            environment = "FSPL"
            rx_height, rx_gain, system_loss, prediction_radius_km = 3.0, 8.0, 3.0, 40

        if filtered_located:
            center_lat = sum(r["latitude"] for r in filtered_located) / len(filtered_located)
            center_lon = sum(r["longitude"] for r in filtered_located) / len(filtered_located)
            zoom = 7
        elif filtered_measurements:
            center_lat = sum(r["latitude"] for r in filtered_measurements) / len(filtered_measurements)
            center_lon = sum(r["longitude"] for r in filtered_measurements) / len(filtered_measurements)
            zoom = 7
        else:
            center_lat, center_lon, zoom = -2.5, 118.0, 5

        if selected_row:
            try:
                center_lat = float(selected_row.get("latitude", center_lat))
                center_lon = float(selected_row.get("longitude", center_lon))
            except (TypeError, ValueError):
                pass

        fmap = folium.Map(location=[center_lat, center_lon], zoom_start=zoom, control_scale=True, tiles=None)
        folium.TileLayer("OpenStreetMap", name="Peta Jalan", overlay=False, control=True, show=True).add_to(fmap)
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
            name="Satelit", overlay=False, control=True, show=False
        ).add_to(fmap)
        try:
            from folium.plugins import LocateControl
            LocateControl(
                auto_start=False, position="topleft",
                strings={"title": "Tampilkan lokasi GPS saya"},
                flyTo=True, keepCurrentZoomLevel=False, showPopup=False
            ).add_to(fmap)
        except (ImportError, AttributeError):
            st.caption("Kontrol GPS tidak tersedia. Perbarui Folium.")

        for tx in filtered_located:
            mux_label = html.escape(str(tx.get("mux", "")))
            popup = (
                f"<b>Pemancar / MUX:</b> {mux_label}<br>"
                f"<b>Wilayah:</b> {html.escape(str(tx.get('wilayah', '')))}, {html.escape(str(tx.get('provinsi', '')))}<br>"
                f"<b>Koordinat:</b> {tx['latitude']:.5f}, {tx['longitude']:.5f}<br>"
                f"<b>Frekuensi tersimpan:</b> {html.escape(str(tx['detail'].get('frequency_mhz', 'belum diisi')))} MHz<br>"
                f"<b>ERP:</b> {html.escape(str(tx['detail'].get('erp_watt', 'belum diisi')))} W"
            )
            folium.Marker(
                [tx["latitude"], tx["longitude"]],
                tooltip=f"Pemancar: {mux_label}",
                popup=folium.Popup(popup, max_width=320),
                icon=folium.Icon(color="red", icon="tower-broadcast", prefix="fa")
            ).add_to(fmap)

        # Heatmap prediksi dihitung dari koordinat setiap pemancar, bukan titik laporan.
        # Grid sengaja dibuat jarang agar peta tetap responsif; bukan simulasi terrain-aware.
        if filtered_located:
            from math import cos, radians
            predicted_points = []
            grid_step_deg = 0.04
            max_transmitters_for_grid = 30
            for tx in filtered_located[:max_transmitters_for_grid]:
                detail = tx.get("detail", {}) or {}
                frequency = detail.get("frequency_mhz") or _uhf_frequency_mhz(tx.get("mux", ""))
                if not frequency:
                    continue
                try:
                    frequency = float(frequency)
                    erp = float(detail.get("erp_watt") or 1000.0)
                    tx_height = float(detail.get("antenna_height_m") or 30.0)
                    if frequency <= 0 or erp <= 0 or tx_height <= 0:
                        continue
                except (TypeError, ValueError):
                    continue

                lat_radius = prediction_radius_km / 111.0
                lon_scale = max(0.2, cos(radians(tx["latitude"])))
                lon_radius = prediction_radius_km / (111.0 * lon_scale)
                lat_steps = int(lat_radius / grid_step_deg) + 1
                lon_steps = int(lon_radius / grid_step_deg) + 1
                for iy in range(-lat_steps, lat_steps + 1):
                    grid_lat = tx["latitude"] + iy * grid_step_deg
                    if not -11 <= grid_lat <= 6:
                        continue
                    for ix in range(-lon_steps, lon_steps + 1):
                        grid_lon = tx["longitude"] + ix * grid_step_deg
                        if not 95 <= grid_lon <= 141:
                            continue
                        distance = _haversine_km(tx["latitude"], tx["longitude"], grid_lat, grid_lon)
                        if distance > prediction_radius_km:
                            continue
                        result = _estimate_tv_signal(
                            tx, distance, frequency, erp, tx_height,
                            rx_height, rx_gain, system_loss, environment
                        )
                        received_dbm = result["received_dbm"]
                        # Skala warna relatif -120 hingga -50 dBm; bukan ambang penerimaan resmi.
                        intensity = max(0.03, min(1.0, (received_dbm + 120.0) / 70.0))
                        predicted_points.append([grid_lat, grid_lon, intensity])

            if predicted_points:
                HeatMap(
                    predicted_points, name="Heatmap Prediksi dari Pemancar",
                    radius=18, blur=22, min_opacity=0.18, max_zoom=12
                ).add_to(fmap)
            else:
                st.info("Heatmap prediksi belum dapat dibuat. Periksa koordinat, frekuensi, dan parameter pemancar.")
            if len(filtered_located) > max_transmitters_for_grid:
                st.caption(f"Simulasi dibatasi pada {max_transmitters_for_grid} pemancar pertama agar peta tetap ringan.")

        if display_mode in ("Heatmap kualitas", "Titik + heatmap"):
            heat_points = [
                [m["latitude"], m["longitude"], max(0.05, min(1.0, m["_quality_num"] / 100.0))]
                for m in filtered_measurements if m.get("_quality_num") is not None
            ]
            if heat_points:
                HeatMap(heat_points, name="Heatmap Quality (hasil laporan)", radius=22, blur=18,
                        min_opacity=0.25, max_zoom=13).add_to(fmap)
            else:
                st.info("Belum ada nilai Quality valid untuk membentuk heatmap pada filter ini.")

        if display_mode in ("Titik pengukuran", "Titik + heatmap"):
            for m in filtered_measurements[:1500]:
                q = m.get("_quality_num")
                color = "green" if q is not None and q >= 70 else ("orange" if q is not None and q >= 40 else ("red" if q is not None else "blue"))
                popup = (
                    f"<b>Pengukuran komunitas</b><br>MUX: {html.escape(str(m.get('mux', '')))}"
                    f"<br>Wilayah: {html.escape(str(m.get('wilayah', '')))}"
                    f"<br>Strength: {html.escape(str(m.get('strength', '-')))}%"
                    f"<br>Quality: {html.escape(str(m.get('quality', '-')))}%"
                    f"<br>SNR: {html.escape(str(m.get('snr', '-')))} dB"
                    f"<br>BER: {html.escape(str(m.get('ber', '-')))}"
                    f"<br>Perangkat: {html.escape(str(m.get('device_type', '-')))}"
                    f"<br>Waktu: {html.escape(str(m.get('timestamp', '-')))}"
                )
                folium.CircleMarker(
                    [m["latitude"], m["longitude"]], radius=6, color=color,
                    fill=True, fill_opacity=0.75,
                    tooltip=f"{m.get('mux', '')}: Quality {m.get('quality', '-')}%",
                    popup=folium.Popup(popup, max_width=320)
                ).add_to(fmap)

        folium.LayerControl(collapsed=False, position="topright").add_to(fmap)
        if logged_in and selected_row is not None:
            crosshair = """<div style="position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:9999;pointer-events:none;color:#1769aa;font-size:30px;font-weight:bold;text-shadow:0 0 3px white,0 0 5px white">⊕</div>"""
            fmap.get_root().html.add_child(folium.Element(crosshair))

        map_result = st_folium(
            fmap, width=None, height=570, use_container_width=True,
            key="digital_transmitter_map", returned_objects=["center", "zoom"]
        )
        st.caption(
            f"{len(filtered_located)} pemancar • {len(filtered_measurements)} laporan pada filter. "
            "Heatmap Quality berasal dari titik laporan pengguna; Heatmap Prediksi dihitung dari titik pemancar menggunakan model propagasi sederhana."
        )
        current_center = (map_result or {}).get("center") or {"lat": center_lat, "lng": center_lon}
        try:
            target_lat = float(current_center.get("lat", center_lat))
            target_lon = float(current_center.get("lng", center_lon))
        except (TypeError, ValueError, AttributeError):
            target_lat, target_lon = center_lat, center_lon

        # Parameter teknis pemancar dapat diperbarui admin, tetap opsional dan bersumber dari data resmi.
        if admin_can_manage and selected_row is not None:
            st.subheader("🧰 Data teknis pemancar (admin)")
            detail = selected_row.get("detail", {}) or {}
            with st.expander("Kelola parameter teknis", expanded=False):
                tc1, tc2, tc3 = st.columns(3)
                frequency_value = tc1.number_input("Frekuensi aktual (MHz)", min_value=0.0, max_value=1000.0,
                    value=float(detail.get("frequency_mhz") or _uhf_frequency_mhz(selected_row.get("mux", "")) or 0.0),
                    step=0.1, key="map_tx_frequency")
                erp_value = tc2.number_input("ERP aktual (W)", min_value=0.0, max_value=10000000.0,
                    value=float(detail.get("erp_watt") or 0.0), step=100.0, key="map_tx_erp")
                height_value = tc3.number_input("Tinggi antena pemancar (m)", min_value=0.0, max_value=500.0,
                    value=float(detail.get("antenna_height_m") or 0.0), step=1.0, key="map_tx_height")
                tc4, tc5, tc6 = st.columns(3)
                gain_value = tc4.number_input("Gain antena pemancar (dBd)", min_value=-10.0, max_value=30.0,
                    value=float(detail.get("antenna_gain_dbd") or 0.0), step=0.5, key="map_tx_gain")
                azimuth_value = tc5.number_input("Azimuth antena (°)", min_value=0.0, max_value=360.0,
                    value=float(detail.get("azimuth_deg") or 0.0), step=1.0, key="map_tx_azimuth")
                polarization_value = tc6.selectbox("Polarisasi", ["Tidak diketahui", "Horizontal", "Vertikal"],
                    index=["Tidak diketahui", "Horizontal", "Vertikal"].index(detail.get("polarization", "Tidak diketahui"))
                    if detail.get("polarization", "Tidak diketahui") in ["Tidak diketahui", "Horizontal", "Vertikal"] else 0,
                    key="map_tx_polarization")
                if st.button("💾 Simpan parameter teknis", key="save_tx_technical"):
                    path = f"siaran/{selected_row['provinsi']}/{selected_row['wilayah']}/{selected_row['mux']}"
                    ref = db.reference(path)
                    before = ref.get() or {}
                    if isinstance(before, list):
                        before = {"siaran": before}
                    after = {**before, "frequency_mhz": frequency_value or None,
                             "erp_watt": erp_value or None, "antenna_height_m": height_value or None,
                             "antenna_gain_dbd": gain_value, "azimuth_deg": azimuth_value,
                             "polarization": polarization_value}
                    ref.set(after)
                    write_audit_log("update_transmitter_technical", selected_row["provinsi"], selected_row["wilayah"],
                                    selected_row["mux"], before=before, after=after)
                    st.success("Parameter teknis tersimpan.")
                    st.rerun()

        if logged_in and selected_row is not None:
            st.subheader("📍 Kelola koordinat pemancar")
            st.caption(f"Posisi tengah peta: {target_lat:.6f}, {target_lon:.6f}. Ini bukan pembacaan akurasi GPS; pastikan titik tepat sebelum menyimpan.")
            has_saved_location = selected_row.get("latitude") is not None and selected_row.get("longitude") is not None
            can_save_location = admin_can_manage or not has_saved_location
            save_label = "💾 Simpan posisi pemancar" if admin_can_manage else "📍 Tambahkan titik pemancar"
            if st.button(save_label, key="save_map_center_point", disabled=not can_save_location):
                if not (-11 <= target_lat <= 6 and 95 <= target_lon <= 141):
                    st.error("Titik berada di luar rentang wilayah Indonesia.")
                elif has_saved_location and not admin_can_manage:
                    st.error("Hanya admin yang dapat mengubah titik yang sudah ada.")
                else:
                    r = selected_row
                    ref = db.reference(f"siaran/{r['provinsi']}/{r['wilayah']}/{r['mux']}")
                    before = ref.get()
                    if isinstance(before, list):
                        before = {"siaran": before}
                    updated = {**(before or {}), "latitude": target_lat, "longitude": target_lon}
                    ref.set(updated)
                    write_audit_log("update_coordinates" if has_saved_location else "add_coordinates",
                                    r["provinsi"], r["wilayah"], r["mux"], before=before, after=updated)
                    st.success("Koordinat pemancar berhasil disimpan.")
                    st.rerun()
            if admin_can_manage:
                confirm_delete = st.checkbox("Saya yakin ingin menghapus titik pemancar terpilih",
                    key="confirm_delete_transmitter_location", disabled=not has_saved_location)
                if st.button("🗑️ Hapus titik pemancar", key="delete_transmitter_location",
                             disabled=(not has_saved_location or not confirm_delete)):
                    r = selected_row
                    ref = db.reference(f"siaran/{r['provinsi']}/{r['wilayah']}/{r['mux']}")
                    before = ref.get()
                    if isinstance(before, list):
                        before = {"siaran": before}
                    before = before if isinstance(before, dict) else {}
                    updated = {k: v for k, v in before.items() if k not in {"latitude", "longitude"}}
                    ref.set(updated)
                    write_audit_log("delete_coordinates", r["provinsi"], r["wilayah"], r["mux"], before=before, after=updated)
                    st.success("Titik pemancar dihapus; data kanal tetap tersimpan.")
                    st.rerun()

        # Estimasi seluruh kandidat pemancar, bukan sekadar yang terdekat.
        st.subheader("📡 Perbandingan estimasi penerimaan dari pemancar")
        if filtered_located:
            estimates = []
            for tx in filtered_located:
                distance = _haversine_km(target_lat, target_lon, tx["latitude"], tx["longitude"])
                detail = tx.get("detail", {}) or {}
                frequency = detail.get("frequency_mhz") or _uhf_frequency_mhz(tx.get("mux", ""))
                erp = detail.get("erp_watt") or 1000.0
                tx_height = detail.get("antenna_height_m") or 30.0
                if frequency:
                    result = _estimate_tv_signal(tx, distance, frequency, erp, tx_height,
                                                 rx_height, rx_gain, system_loss, environment)
                    estimates.append({
                        "MUX": tx.get("mux"), "Wilayah": tx.get("wilayah"),
                        "Jarak (km)": round(distance, 2), "Frekuensi (MHz)": round(float(frequency), 1),
                        "ERP (W)": erp, "Model terpakai": result["model"],
                        "Path loss (dB)": round(result["path_loss_db"], 1),
                        "Estimasi daya (dBm)": round(result["received_dbm"], 1),
                        "_tx": tx, "_result": result
                    })
            estimates.sort(key=lambda x: x["Estimasi daya (dBm)"], reverse=True)
            if estimates:
                st.dataframe(pd.DataFrame([{k: v for k, v in item.items() if not k.startswith("_")} for item in estimates]),
                             use_container_width=True, hide_index=True)
                best = estimates[0]
                st.metric("Estimasi daya tertinggi dalam daftar", f"{best['Estimasi daya (dBm)']:.1f} dBm",
                          help="Perbandingan model indikatif, bukan jaminan MUX paling mudah diterima.")
                st.caption(
                    f"Kandidat tertinggi: {best['MUX']} — {best['Wilayah']}, jarak {best['Jarak (km)']} km. "
                    "Frekuensi eksplisit dari data teknis diprioritaskan; jika kosong, kanal UHF pada nama MUX diperkirakan. "
                    "ERP default 1.000 W hanya asumsi saat ERP aktual belum diisi. Gain, tinggi, dan rugi sistem juga memengaruhi hasil."
                )
            else:
                st.info("Frekuensi tidak tersedia. Isi frekuensi aktual atau gunakan nama MUX dengan format UHF 21–48.")
        else:
            st.info("Belum ada koordinat pemancar yang cocok dengan filter.")

        st.subheader("📝 Kirim pengukuran aktual dari TV/STB")
        if not logged_in:
            st.info("Login diperlukan untuk mengirim laporan pengukuran.")
        elif selected_row is None:
            st.info("Pilih MUX yang tersedia pada filter untuk mengirim pengukuran.")
        else:
            st.write("Salin nilai dari menu *Informasi Sinyal* TV/STB. Jangan mengisi nilai yang tidak ditampilkan perangkat.")
            with st.form("signal_measurement_form", clear_on_submit=True):
                st.caption(f"MUX: **{selected_row['mux']}** — {selected_row['wilayah']}, {selected_row['provinsi']}")
                st.caption(f"Koordinat yang akan disimpan: {target_lat:.6f}, {target_lon:.6f} (pusat peta, periksa kembali posisinya).")
                strength = st.number_input("Signal Strength (%)", min_value=0, max_value=100, value=0, step=1)
                quality = st.number_input("Signal Quality (%)", min_value=0, max_value=100, value=0, step=1)
                snr_input = st.text_input("SNR (dB), jika tersedia", placeholder="Contoh: 24.5")
                ber_input = st.text_input("BER, jika tersedia", placeholder="Contoh: 0.000001")
                antenna_type = st.selectbox("Jenis antena", ["Indoor", "Outdoor", "Outdoor + booster", "Tidak tahu"])
                device_type = st.selectbox("Perangkat penerima", ["TV DVB-T2", "STB DVB-T2", "Lainnya"])
                device_brand = st.text_input("Merek/model TV atau STB (opsional)", max_chars=80)
                notes = st.text_input("Catatan (opsional)", max_chars=250)
                submitted_measurement = st.form_submit_button("📤 Kirim hasil pengukuran")
                if submitted_measurement:
                    if not (-11 <= target_lat <= 6 and 95 <= target_lon <= 141):
                        st.error("Koordinat laporan tidak valid untuk wilayah Indonesia.")
                    else:
                        try:
                            snr_value = float(snr_input.replace(",", ".")) if snr_input.strip() else None
                            if snr_value is not None and not -10 <= snr_value <= 60:
                                raise ValueError("SNR harus berada pada rentang -10 sampai 60 dB.")
                            ber_value = float(ber_input.replace(",", ".")) if ber_input.strip() else None
                            if ber_value is not None and not 0 <= ber_value <= 1:
                                raise ValueError("BER harus berada pada rentang 0 sampai 1.")
                            now = datetime.now(WIB)
                            username = st.session_state.username
                            user_data = db.reference(f"users/{username}").get() or {}
                            measurement = {
                                "username": username, "display_name": user_data.get("nama", username),
                                "latitude": target_lat, "longitude": target_lon,
                                "location_source": "map_center_user_confirmed",
                                "strength": int(strength), "quality": int(quality),
                                "snr": snr_value, "ber": ber_value,
                                "antenna_type": antenna_type, "device_type": device_type,
                                "device_brand": device_brand.strip(), "notes": notes.strip(),
                                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S WIB"),
                                "created_at": now.isoformat()
                            }
                            measurement_ref = db.reference(
                                f"signal_measurements/{selected_row['provinsi']}/{selected_row['wilayah']}/{selected_row['mux']}"
                            ).push()
                            measurement_ref.set(measurement)
                            st.success("Terima kasih! Hasil pengukuran berhasil dikirim.")
                            st.rerun()
                        except ValueError as exc:
                            st.error(f"Periksa nilai SNR/BER: {exc}")
                        except Exception as exc:
                            st.error(f"Gagal menyimpan pengukuran: {exc}")

        st.subheader("📈 Tren kualitas penerimaan")
        chart_records = [
            m for m in filtered_measurements
            if m.get("_quality_num") is not None
            and (selected_row is None or (
                m.get("provinsi") == selected_row.get("provinsi")
                and m.get("wilayah") == selected_row.get("wilayah")
                and m.get("mux") == selected_row.get("mux")
            ))
        ]
        if chart_records:
            chart_rows = []
            for m in chart_records:
                dt = _parse_measurement_datetime(m)
                if dt:
                    chart_rows.append({"Waktu": dt, "Quality (%)": m["_quality_num"],
                                       "Strength (%)": pd.to_numeric(m.get("strength"), errors="coerce"),
                                       "SNR (dB)": pd.to_numeric(m.get("snr"), errors="coerce")})
            if chart_rows:
                chart_df = pd.DataFrame(chart_rows).sort_values("Waktu").set_index("Waktu")
                st.line_chart(chart_df[["Quality (%)", "Strength (%)"]], use_container_width=True)
                if chart_df["SNR (dB)"].notna().any():
                    st.line_chart(chart_df[["SNR (dB)"]], use_container_width=True)
            else:
                st.info("Data waktu belum cukup untuk membentuk grafik tren.")
        else:
            st.info("Belum ada Quality valid pada MUX/periode terpilih.")

        st.subheader("📋 Riwayat pengukuran komunitas")
        history_records = [
            m for m in filtered_measurements
            if selected_row is None or (
                m.get("provinsi") == selected_row.get("provinsi")
                and m.get("wilayah") == selected_row.get("wilayah")
                and m.get("mux") == selected_row.get("mux")
            )
        ]
        if history_records:
            table_rows = [{
                "Waktu": m.get("timestamp", "-"), "MUX": m.get("mux", "-"),
                "Wilayah": m.get("wilayah", "-"), "Strength (%)": m.get("strength", "-"),
                "Quality (%)": m.get("quality", "-"), "SNR (dB)": m.get("snr", "-"),
                "BER": m.get("ber", "-"), "Antena": m.get("antenna_type", "-"),
                "Perangkat": m.get("device_type", "-"), "Model perangkat": m.get("device_brand", "-")
            } for m in history_records[:250]]
            st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
            if admin_can_manage:
                st.markdown("#### 🗑️ Kelola laporan sinyal (Admin)")
                st.caption("Penghapusan laporan bersifat permanen dan dicatat pada audit log.")
                for measurement in history_records:
                    measurement_id = measurement.get("id")
                    if not measurement_id:
                        continue
                    report_label = (
                        f"{measurement.get('timestamp', '-')} — "
                        f"{measurement.get('display_name', measurement.get('username', 'Pengguna'))} — "
                        f"Quality {measurement.get('quality', '-')}%"
                    )
                    with st.expander(report_label):
                        st.write(f"**MUX:** {measurement.get('mux', '-')} | **Wilayah:** {measurement.get('wilayah', '-')}, {measurement.get('provinsi', '-')}")
                        if st.checkbox("Konfirmasi hapus laporan ini", key=f"confirm_delete_signal_{measurement_id}"):
                            if st.button("🗑️ Hapus laporan", key=f"delete_signal_{measurement_id}", type="primary"):
                                try:
                                    path = (f"signal_measurements/{measurement['provinsi']}/"
                                            f"{measurement['wilayah']}/{measurement['mux']}/{measurement_id}")
                                    db.reference(path).delete()
                                    db.reference("signal_measurement_audit_logs").push().set({
                                        "action": "delete_signal_measurement", "measurement_id": measurement_id,
                                        "provinsi": measurement.get("provinsi", ""), "wilayah": measurement.get("wilayah", ""),
                                        "mux": measurement.get("mux", ""), "deleted_by": st.session_state.get("username", ""),
                                        "deleted_at": datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB"),
                                        "before": measurement
                                    })
                                    st.success("Laporan berhasil dihapus.")
                                    st.rerun()
                                except Exception as exc:
                                    st.error(f"Gagal menghapus laporan: {exc}")
        else:
            st.info("Belum ada laporan untuk filter terpilih.")
    except ImportError:
        st.warning("Peta interaktif memerlukan paket `folium` dan `streamlit-folium`. Pasang dengan: `pip install folium streamlit-folium`.")
        if filtered_located:
            st.dataframe(pd.DataFrame([{
                "MUX": r.get("mux", ""), "Wilayah": r.get("wilayah", ""),
                "Latitude": r["latitude"], "Longitude": r["longitude"]
            } for r in filtered_located]), use_container_width=True, hide_index=True)


def display_restore_history():
    """Pemulihan versi sebelumnya hanya untuk admin."""
    st.subheader("♻️ Riwayat Perubahan dan Pemulihan Data")
    if not st.session_state.get("login") or not is_admin():
        st.info("Pemulihan data hanya tersedia untuk admin.")
        return
    logs = db.reference("audit_logs").get() or {}
    restorable = [(k, v) for k, v in logs.items() if v.get("before") is not None and v.get("action") in {"edit_broadcast", "delete_broadcast", "restore_broadcast"}]
    restorable.sort(key=lambda item: item[1].get("timestamp", ""), reverse=True)
    if not restorable:
        st.info("Belum ada versi sebelumnya yang dapat dipulihkan. Riwayat versi mulai tersedia setelah perubahan baru tercatat.")
        return
    labels = [f"{v.get('timestamp', '')} — {v.get('provinsi', '')}/{v.get('wilayah', '')}/{v.get('mux', '')} ({v.get('action', '')})" for _, v in restorable]
    chosen = st.selectbox("Pilih versi yang akan dipulihkan", range(len(restorable)), format_func=lambda i: labels[i], key="restore_log_select")
    log_id, log = restorable[chosen]
    st.json(log.get("before"))
    confirm = st.checkbox("Saya memahami pemulihan akan mengganti data MUX saat ini", key="confirm_restore")
    if st.button("Pulihkan versi terpilih", disabled=not confirm):
        path = f"siaran/{log.get('provinsi')}/{log.get('wilayah')}/{log.get('mux')}"
        current = db.reference(path).get()
        previous = log.get("before")
        db.reference(path).set(previous)
        write_audit_log("restore_broadcast", log.get("provinsi", ""), log.get("wilayah", ""), log.get("mux", ""), before=current, after=previous)
        st.success("Versi sebelumnya berhasil dipulihkan.")
        st.rerun()


def switch_page(page_name):
    """Fungsi untuk berpindah halaman."""
    st.session_state.halaman = page_name

def proses_logout():
    """Membersihkan session state saat logout."""
    st.session_state.login = False
    st.session_state.username = ""
    st.session_state.selected_other_user = None
    st.session_state.messages = []
    switch_page("beranda")

# --- FUNGSI UNTUK MERENDER KOMPONEN UI ---

def display_sidebar():
    """Navbar modern dengan dropdown hamburger; sidebar Streamlit disembunyikan."""
    st.markdown("""
    <style>
      /* Hilangkan seluruh navigasi dan chrome bawaan Streamlit */
      [data-testid="stSidebar"],
      [data-testid="stSidebarNav"],
      [data-testid="collapsedControl"],
      [data-testid="stHeader"],
      [data-testid="stToolbar"],
      [data-testid="stDecoration"],
      #MainMenu,
      footer,
      header[data-testid="stHeader"] {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        min-height: 0 !important;
      }
      /* Pastikan konten tidak berada di bawah header Streamlit */
      .stApp,
      [data-testid="stAppViewContainer"],
      [data-testid="stAppViewContainer"] > .main {
        padding-top: 0 !important;
        margin-top: 0 !important;
      }
      .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 2rem !important;
        max-width: 1440px;
      }
      /* Header navigasi bergaya website */
      .ktvdi-navbar {
        display:flex; align-items:center; justify-content:space-between;
        gap:16px; padding:14px 20px; margin:0 0 22px 0;
        border:1px solid rgba(128,128,128,.22); border-radius:16px;
        background:var(--secondary-background-color);
        box-shadow:0 5px 18px rgba(0,0,0,.06);
      }
      .ktvdi-brand {display:flex; align-items:center; gap:12px; min-width:0;}
      .ktvdi-logo {font-size:28px; line-height:1;}
      .ktvdi-brand-title {font-size:18px; font-weight:750; letter-spacing:.2px;}
      .ktvdi-brand-sub {font-size:12px; opacity:.68; margin-top:2px;}
      [data-testid="stPopover"] > button {
        border-radius:11px !important; border:1px solid rgba(128,128,128,.35) !important;
        font-weight:650 !important; min-height:42px !important;
        padding:0 16px !important; background:var(--background-color) !important;
      }
      [data-testid="stPopoverBody"] {
        min-width:275px !important; padding:14px !important;
        border-radius:14px !important; border:1px solid rgba(128,128,128,.25) !important;
        box-shadow:0 12px 35px rgba(0,0,0,.16) !important;
      }
      [data-testid="stPopoverBody"] [data-testid="stBaseButton-secondary"] {
        text-align:left !important; justify-content:flex-start !important;
        border:0 !important; border-radius:9px !important; min-height:40px !important;
      }
      [data-testid="stPopoverBody"] [data-testid="stBaseButton-secondary"]:hover {
        background:rgba(128,128,128,.13) !important;
      }
      @media (max-width:640px) {
        .block-container {padding-top: 1rem !important;}
        .ktvdi-navbar {padding:11px 12px; border-radius:12px;}
        .ktvdi-brand-title {font-size:14px;}
        .ktvdi-brand-sub {font-size:10px;}
        [data-testid="stPopover"] > button {padding:0 11px !important;}
      }
      :root {--ktvdi-blue:#1769aa;--ktvdi-blue-deep:#103b66;--ktvdi-cyan:#38bdf8;--ktvdi-radius:18px;}
      .block-container {max-width:1320px !important;padding-left:clamp(1rem,4vw,3rem) !important;padding-right:clamp(1rem,4vw,3rem) !important;}
      .ktvdi-brand {padding:13px 17px;border:1px solid rgba(128,128,128,.20);border-radius:16px;background:var(--secondary-background-color);box-shadow:0 8px 28px rgba(15,45,75,.07);}
      .ktvdi-logo {display:grid;place-items:center;width:48px;height:48px;border-radius:14px;background:linear-gradient(135deg,#e0f2fe,#dbeafe);font-size:26px;flex:0 0 auto;}
      .ktvdi-brand-title {font-size:clamp(13px,1.5vw,17px);font-weight:800;letter-spacing:.035em;}
      .ktvdi-brand-sub {font-size:12px;opacity:.72;}
      h1,h2,h3 {letter-spacing:-.025em;font-weight:750 !important;} h1 {font-size:clamp(1.65rem,3vw,2.35rem) !important;} h2 {font-size:clamp(1.25rem,2.2vw,1.65rem) !important;} h3 {font-size:1.08rem !important;}
      [data-testid="stAppViewContainer"] {background:radial-gradient(ellipse at 8% 0%,rgba(56,189,248,.08),transparent 32%),var(--background-color);}
      [data-testid="stVerticalBlockBorderWrapper"] {border-radius:var(--ktvdi-radius) !important;border-color:rgba(128,128,128,.20) !important;}
      [data-testid="stMetric"] {padding:16px 18px;border:1px solid rgba(128,128,128,.20);border-radius:16px;background:var(--secondary-background-color);box-shadow:0 6px 20px rgba(15,45,75,.045);}
      [data-testid="stMetricLabel"] {font-weight:650;} [data-testid="stMetricValue"] {font-weight:800;letter-spacing:-.04em;}
      [data-testid="stBaseButton-primary"] {border:0 !important;border-radius:11px !important;background:linear-gradient(135deg,#1769aa,#258bd0) !important;box-shadow:0 5px 14px rgba(23,105,170,.18);font-weight:700 !important;}
      [data-testid="stBaseButton-secondary"],[data-testid="stDownloadButton"] button {border-radius:11px !important;font-weight:650 !important;transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease;}
      [data-testid="stBaseButton-secondary"]:hover {transform:translateY(-1px);border-color:rgba(23,105,170,.55) !important;box-shadow:0 5px 15px rgba(15,45,75,.08);}
      [data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea,[data-testid="stSelectbox"] [data-baseweb="select"] > div,[data-testid="stNumberInput"] input {border-radius:11px !important;}
      [data-testid="stExpander"] {border:1px solid rgba(128,128,128,.20) !important;border-radius:14px !important;overflow:hidden;background:var(--secondary-background-color);}
      [data-testid="stDataFrame"],[data-testid="stTable"] {border:1px solid rgba(128,128,128,.18);border-radius:13px;overflow:hidden;}
      [data-testid="stAlert"] {border-radius:13px;} [data-testid="stChatMessage"] {border-radius:15px;border:1px solid rgba(128,128,128,.12);}
      .ktvdi-hero {position:relative;overflow:hidden;padding:clamp(24px,4vw,42px);margin:8px 0 24px;border-radius:22px;color:white;background:linear-gradient(120deg,#0d3158 0%,#1769aa 58%,#1596c5 100%);box-shadow:0 16px 36px rgba(12,67,112,.20);}
      .ktvdi-hero:after {content:"";position:absolute;width:280px;height:280px;right:-70px;top:-130px;border:1px solid rgba(255,255,255,.20);border-radius:50%;box-shadow:0 0 0 28px rgba(255,255,255,.045),0 0 0 58px rgba(255,255,255,.035);}
      .ktvdi-hero-kicker {font-size:11px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;opacity:.78;}
      .ktvdi-hero-title {position:relative;z-index:1;max-width:760px;margin:9px 0 10px;font-size:clamp(25px,4vw,39px);line-height:1.13;font-weight:850;letter-spacing:-.04em;}
      .ktvdi-hero-copy {position:relative;z-index:1;max-width:660px;margin:0;color:rgba(255,255,255,.82);font-size:14px;line-height:1.7;}
      .ktvdi-section-note {font-size:13px;opacity:.72;margin-top:-8px;margin-bottom:16px;}
      @media(max-width:640px){.block-container{padding-left:1rem !important;padding-right:1rem !important;}.ktvdi-brand{padding:10px 11px;gap:9px;}.ktvdi-logo{width:39px;height:39px;font-size:22px;border-radius:11px;}.ktvdi-hero{padding:23px 20px;border-radius:17px;}[data-testid="stMetric"]{padding:12px;}}
    </style>
    """, unsafe_allow_html=True)

    logged_in = bool(st.session_state.get("login"))
    if logged_in:
        users = db.reference("users").get() or {}
        user_data = users.get(st.session_state.username, {})
        nama_pengguna = user_data.get("nama", st.session_state.username)
        user_points = user_data.get("points", 0)
        user_label = f"👤 {nama_pengguna} · ⭐ {user_points} poin"
    else:
        user_label = "Komunitas TV Digital Indonesia"

    brand_col, menu_col = st.columns([5, 1.35], vertical_alignment="center")
    with brand_col:
        st.markdown(
            '<div class="ktvdi-brand"><div class="ktvdi-logo">🇮🇩</div>'
            '<div><div class="ktvdi-brand-title">KOMUNITAS TV DIGITAL INDONESIA</div>'
            f'<div class="ktvdi-brand-sub">{user_label}</div></div></div>',
            unsafe_allow_html=True,
        )
    with menu_col:
        with st.popover("☰  Menu", use_container_width=True):
            st.markdown("#### Navigasi")
            menu_items = [
                ("🏠  Beranda", "beranda"),
                ("🔎  Pencarian Global", "search"),
                ("📊  Statistik TV Digital", "statistics"),
                ("🗺️  Peta Pemancar", "map"),
                ("🔔  Notifikasi Siaran", "notifications"),
            ]
            if logged_in:
                menu_items.extend([
                    ("➕  Tambah Data Siaran", "add_data"),
                    ("👤  Profil Saya", "profile"),
                    ("👥  Profil Pengguna Lain", "other_users"),
                    ("🏆  Leaderboard", "leaderboard"),
                    ("🤖  Chatbot KTVDI", "chatbot"),
                    ("🚩  Laporkan Kesalahan Data", "report_data"),
                ])
                if is_admin():
                    menu_items.append(("🛠️  Dashboard Admin", "admin"))
            else:
                menu_items.append(("🔐  Login / Daftar Akun", "login"))

            for label, page in menu_items:
                if st.button(label, key=f"nav_menu_{page}", use_container_width=True):
                    if page == "profile":
                        st.session_state.selected_other_user = None
                    switch_page(page)
                    st.rerun()

            if logged_in:
                st.divider()
                st.button(
                    "🚪  Logout", key="nav_menu_logout",
                    on_click=proses_logout, use_container_width=True,
                )


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
    st.markdown('<div class="ktvdi-section-note">Lengkapi informasi wilayah, penyelenggara MUX, dan daftar kanal siaran.</div>', unsafe_allow_html=True)
    st.header("✍️ Tambah Data Siaran")

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
                        write_audit_log("add_broadcast", provinsi, wilayah_clean, mux_clean, before=None, after=data_to_save)
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
                write_audit_log("delete_broadcast", provinsi, wilayah, mux_key, before=mux_details_full, after=None)
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
                            
                            old_path = f"siaran/{selected_provinsi}/{default_wilayah}/{default_mux}"
                            old_snapshot = db.reference(old_path).get()
                            write_audit_log("edit_broadcast", selected_provinsi, default_wilayah, default_mux, before=old_snapshot, after=data_to_update)
                            if default_wilayah_normalized != new_wilayah_clean or default_mux != new_mux_clean:
                                db.reference(old_path).delete()
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
        if data.get("points", 0) > 0:
            leaderboard_data.append({
                "nama": data.get("nama", username),
                "username": username,
                "points": data.get("points", 0)
            })
    
    leaderboard_data.sort(key=lambda x: x["points"], reverse=True)

    # --- Bagian yang dimodifikasi untuk membaca timestamp dari Firebase ---
    last_update_timestamp_str = db.reference("app_metadata/last_leaderboard_update_timestamp").get()
    
    # Konversi string timestamp menjadi objek datetime, lalu format ulang ke WIB
    display_update_time_str = "Belum ada update poin tercatat"
    if last_update_timestamp_str:
        try:
            # Parse string timestamp dari Firebase
            # Asumsi format: "YYYY-MM-DD HH:MM:SS"
            dt_object = datetime.strptime(last_update_timestamp_str, "%Y-%m-%d %H:%M:%S")
            # Firebase tidak menyimpan timezone, jadi kita asumsikan UTC atau waktu server
            # Kemudian konversi ke WIB untuk tampilan
            
            # Jika Anda menyimpan waktu server Firebase (biasanya UTC)
            # dt_object_utc = pytz.utc.localize(dt_object)
            # dt_object_wib = dt_object_utc.astimezone(WIB)
            
            # Jika Anda menyimpan waktu WIB langsung (seperti di kode sebelumnya)
            # Maka tidak perlu konversi timezone, cukup lokalisaai untuk memastikan
            dt_object_wib = WIB.localize(dt_object) # Atau dt_object.astimezone(WIB) jika dt_object sudah ada timezone

            display_update_time_str = dt_object_wib.strftime("%d-%m-%Y %H:%M:%S WIB")
        except ValueError:
            display_update_time_str = f"Waktu update tidak valid: {last_update_timestamp_str}"
        except Exception as e:
            display_update_time_str = f"Error waktu: {e}"
    # --- Akhir bagian yang dimodifikasi ---

    if leaderboard_data:
        st.write("Berikut adalah daftar kontributor teratas berdasarkan poin:")
        
        leaderboard_df = pd.DataFrame(leaderboard_data)
        leaderboard_df.index = leaderboard_df.index + 1
        st.dataframe(leaderboard_df[["nama", "points"]].rename(columns={"nama": "Nama Kontributor", "points": "Poin"}), use_container_width=True)
        
        # Tampilkan keterangan waktu update yang baru
        st.markdown(f"<p style='font-size: small; color: grey;'>Data diperbarui pada: {display_update_time_str}</p>", unsafe_allow_html=True)
    else:
        st.info("Belum ada kontributor dengan poin yang tercatat.")
        # Tampilkan juga keterangan waktu jika tidak ada data
        st.markdown(f"<p style='font-size: small; color: grey;'>Terakhir diperbarui: {display_update_time_str}</p>", unsafe_allow_html=True) # Tambahkan ini

    st.markdown("---")
    if st.button("⬅️ Kembali ke Beranda"):
        switch_page("beranda")
        st.rerun()
        
def display_chatbot_page():
    """Menampilkan halaman FAQ Chatbot."""
    st.header("🤖 Chatbot KTVDI")
    st.info("Ajukan pertanyaan seputar TV Digital Indonesia. Saya akan bantu menjawab!")

    # Inisialisasi model generatif dengan instruksi sistem (pengetahuan dasar FAQ)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=(
            "Anda adalah Chatbot AI KTVDI untuk website Komunitas TV Digital Indonesia (KTVDI). "
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

    # Tampilkan pesan chat dari riwayat saat aplikasi dijalankan ulang
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Reaksi terhadap input pengguna
    if prompt := st.chat_input("Tanyakan sesuatu tentang KTVDI atau TV Digital..."):
        # Tampilkan pesan pengguna di kontainer pesan chat
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Tampilkan respons asisten di kontainer pesan chat
        with st.chat_message("assistant"):
            with st.spinner("Mencari jawaban..."):
                try:
                    # Siapkan riwayat chat untuk Gemini (berbasis giliran)
                    # Jangan masukkan prompt saat ini ke riwayat yang diberikan ke start_chat
                    chat_history_for_gemini = [
                        {"role": "user" if msg["role"] == "user" else "model", "parts": [msg["content"]]}
                        for msg in st.session_state.messages[:-1] # Semua pesan kecuali yang terakhir (prompt saat ini)
                    ]

                    # Mulai chat dengan model
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

# --- ROUTING HALAMAN UTAMA APLIKASI ---

# Navbar website dengan dropdown hamburger (tanpa sidebar Streamlit).
display_sidebar()

if st.session_state.halaman == "beranda":
    st.markdown(
        '<section class="ktvdi-hero">'
        '<div class="ktvdi-hero-kicker">Komunitas • Informasi • Kolaborasi</div>'
        '<div class="ktvdi-hero-title">Jelajahi Siaran TV Digital Indonesia</div>'
        '<p class="ktvdi-hero-copy">Temukan informasi kanal DVB-T2, wilayah layanan, dan penyelenggara MUX. '
        'Bantu komunitas menjaga data siaran tetap akurat dan terkini.</p>'
        '</section>', unsafe_allow_html=True,
    )
    st.header("📺 Data Siaran TV Digital di Indonesia")
    st.markdown('<p class="ktvdi-section-note">Pilih wilayah untuk melihat daftar MUX dan kanal yang tersedia.</p>', unsafe_allow_html=True)
    try:
        overview_rows = get_all_broadcast_rows()
        overview_provinces = len({row["provinsi"] for row in overview_rows})
        overview_areas = len({(row["provinsi"], row["wilayah"]) for row in overview_rows})
        overview_channels = sum(len(row["siaran"]) for row in overview_rows)
        overview_mux = len(overview_rows)
        metric_cols = st.columns(4)
        metric_cols[0].metric("Provinsi terdata", overview_provinces)
        metric_cols[1].metric("Wilayah layanan", overview_areas)
        metric_cols[2].metric("MUX terdata", overview_mux)
        metric_cols[3].metric("Kanal terdata", overview_channels)
    except Exception:
        pass
    quick1, quick2, quick3 = st.columns(3)
    if quick1.button("🔎 Pencarian Global", use_container_width=True):
        switch_page("search"); st.rerun()
    if quick2.button("📊 Statistik TV Digital", use_container_width=True):
        switch_page("statistics"); st.rerun()
    if quick3.button("🗺️ Peta Pemancar", use_container_width=True):
        switch_page("map"); st.rerun()
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

    if not st.session_state.login:
        st.info("Untuk menambahkan, memperbarui, atau menghapus data, silakan login terlebih dahulu melalui tombol Login / Daftar Akun di bagian atas halaman.")

elif st.session_state.halaman == "add_data":
    if not st.session_state.login:
        st.warning("Anda harus login untuk menambahkan data siaran.")
        switch_page("login")
        st.rerun()
    else:
        st.title("➕ Tambah Data Siaran")
        st.caption("Masukkan data siaran baru untuk memperkaya basis data komunitas KTVDI.")
        display_add_data_form()
        st.markdown("---")
        if st.button("⬅️ Kembali ke Beranda", key="back_from_add_data"):
            switch_page("beranda")
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

elif st.session_state.halaman == "report_data":
    display_report_page()

elif st.session_state.halaman == "admin":
    display_admin_dashboard()

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

elif st.session_state.halaman == "search":
    display_global_search()
elif st.session_state.halaman == "statistics":
    display_digital_statistics()
elif st.session_state.halaman == "notifications":
    display_notifications()
elif st.session_state.halaman == "map":
    display_broadcast_map()
