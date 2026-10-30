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


def display_broadcast_map():
    if st.button("⬅️ Kembali ke Beranda", key="back_broadcast_map"):
        switch_page("beranda"); st.rerun()
    st.header("🗺️ Peta Pemancar TV Digital")
    st.write("Klik penanda untuk melihat nama wilayah layanan dan nama MUX. Untuk menambahkan atau mengubah titik, pilih MUX lalu geser peta sampai tanda bidik di tengah tepat berada di lokasi pemancar.")
    rows = get_all_broadcast_rows()
    located = []
    for r in rows:
        try:
            lat, lon = float(r["latitude"]), float(r["longitude"])
            if -11 <= lat <= 6 and 95 <= lon <= 141:
                located.append({**r, "latitude": lat, "longitude": lon})
        except (TypeError, ValueError, KeyError):
            pass

    try:
        import folium
        from streamlit_folium import st_folium
        import html

        if located:
            center_lat = sum(r["latitude"] for r in located) / len(located)
            center_lon = sum(r["longitude"] for r in located) / len(located)
            zoom = 6
        else:
            center_lat, center_lon, zoom = -2.5, 118.0, 5

        logged_in = bool(st.session_state.get("login"))
        admin_can_edit = logged_in and is_admin()
        selected_idx = None
        labels = [f"{r.get('provinsi', '')} / {r.get('wilayah', '')} / {r.get('mux', '')}" for r in rows]
        if admin_can_edit:
            selected_idx = st.selectbox(
                "Pilih MUX yang akan ditambahkan atau dipindahkan",
                range(len(rows)), format_func=lambda i: labels[i], key="map_mux_to_position"
            )
            selected_row = rows[selected_idx]
            try:
                center_lat = float(selected_row.get("latitude", center_lat))
                center_lon = float(selected_row.get("longitude", center_lon))
            except (TypeError, ValueError):
                pass
            st.info("Mode admin: geser peta hingga tanda bidik berada di lokasi pemancar, lalu simpan. Admin juga dapat menghapus titik lokasi yang sudah tersimpan.")
        elif not logged_in:
            st.caption("Login sebagai admin diperlukan untuk menambahkan, memindahkan, atau menghapus titik pemancar.")
        else:
            st.caption("Hanya admin yang dapat menambahkan, memindahkan, atau menghapus titik pemancar.")

        fmap = folium.Map(location=[center_lat, center_lon], zoom_start=zoom, control_scale=True)
        for r in located:
            mux = html.escape(str(r.get("mux", "")))
            wilayah = html.escape(str(r.get("wilayah", "")))
            popup_html = f"""<div style='font-family:Arial,sans-serif;min-width:180px'>
                <b>Wilayah Layanan:</b> {wilayah}<br>
                <b>Nama MUX:</b> {mux}
            </div>"""
            folium.Marker(
                location=[r["latitude"], r["longitude"]],
                tooltip="Klik untuk melihat wilayah layanan dan MUX",
                popup=folium.Popup(popup_html, max_width=260),
                icon=folium.Icon(color="red", icon="broadcast-tower", prefix="fa")
            ).add_to(fmap)

        if admin_can_edit:
            # Fixed crosshair stays in the center of the map viewport while the map is panned.
            crosshair = """<div style="position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:9999;pointer-events:none;color:#1769aa;font-size:30px;font-weight:bold;text-shadow:0 0 3px white,0 0 5px white">⊕</div>"""
            fmap.get_root().html.add_child(folium.Element(crosshair))

        map_result = st_folium(
            fmap, width=None, height=560, use_container_width=True,
            key="digital_transmitter_map", returned_objects=["center", "zoom"]
        )
        st.caption(f"Menampilkan {len(located)} titik pemancar dengan koordinat tersimpan. Klik penanda untuk melihat nama wilayah layanan dan nama MUX.")

        if admin_can_edit:
            current_center = (map_result or {}).get("center") or {"lat": center_lat, "lng": center_lon}
            try:
                target_lat = float(current_center.get("lat", center_lat))
                target_lon = float(current_center.get("lng", center_lon))
            except (TypeError, ValueError, AttributeError):
                target_lat, target_lon = center_lat, center_lon
            st.write(f"**Lokasi bidik:** {target_lat:.6f}, {target_lon:.6f}")
            if st.button("💾 Simpan lokasi bidik untuk MUX ini", key="save_map_center_point"):
                if not (-11 <= target_lat <= 6 and 95 <= target_lon <= 141):
                    st.error("Titik berada di luar rentang wilayah Indonesia. Geser peta ke lokasi di Indonesia.")
                else:
                    r = rows[selected_idx]
                    ref = db.reference(f"siaran/{r['provinsi']}/{r['wilayah']}/{r['mux']}")
                    before = ref.get()
                    if isinstance(before, list):
                        before = {"siaran": before}
                    updated = {**(before or {}), "latitude": target_lat, "longitude": target_lon}
                    ref.set(updated)
                    write_audit_log("update_coordinates", r["provinsi"], r["wilayah"], r["mux"], before=before, after=updated)
                    st.success(f"Lokasi untuk {r['mux']} — {r['wilayah']} berhasil disimpan.")
                    st.rerun()

            has_saved_location = bool(selected_row.get("latitude") is not None and selected_row.get("longitude") is not None)
            confirm_delete = st.checkbox(
                f"Saya yakin ingin menghapus titik peta untuk {selected_row.get('mux', 'MUX')} — {selected_row.get('wilayah', '')}",
                key="confirm_delete_transmitter_location",
                disabled=not has_saved_location,
            )
            if st.button("🗑️ Hapus titik pemancar dari peta", key="delete_transmitter_location", disabled=(not has_saved_location or not confirm_delete)):
                r = rows[selected_idx]
                ref = db.reference(f"siaran/{r['provinsi']}/{r['wilayah']}/{r['mux']}")
                before = ref.get()
                if isinstance(before, list):
                    before = {"siaran": before}
                if not isinstance(before, dict):
                    before = {}
                updated = {k: v for k, v in before.items() if k not in {"latitude", "longitude"}}
                ref.set(updated)
                write_audit_log("delete_coordinates", r["provinsi"], r["wilayah"], r["mux"], before=before, after=updated)
                st.success(f"Titik pemancar {r['mux']} — {r['wilayah']} berhasil dihapus dari peta. Data siaran tetap tersimpan.")
                st.rerun()
    except ImportError:
        st.warning("Peta interaktif memerlukan paket `folium` dan `streamlit-folium`. Pasang dengan: `pip install folium streamlit-folium`.")
        if located:
            st.dataframe(pd.DataFrame([{"Nama MUX": r.get("mux", ""), "Wilayah Layanan": r.get("wilayah", ""), "Latitude": r["latitude"], "Longitude": r["longitude"]} for r in located]), use_container_width=True, hide_index=True)


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
        if st.sidebar.button("🚩 Laporkan Kesalahan Data"):
            switch_page("report_data")
            st.rerun()
        if st.sidebar.button("🔔 Notifikasi Siaran"):
            switch_page("notifications")
            st.rerun()
        if st.sidebar.button("🗺️ Peta Pemancar"):
            switch_page("map")
            st.rerun()
        if is_admin() and st.sidebar.button("🛠️ Dashboard Admin"):
            switch_page("admin")
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

st.title("🇮🇩 KOMUNITAS TV DIGITAL INDONESIA 🇮🇩")
display_sidebar()

if st.session_state.halaman == "beranda":
    st.header("📺 Data Siaran TV Digital di Indonesia")
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
