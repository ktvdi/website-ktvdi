from __future__ import annotations

from typing import Any

from firebase_admin import db

from services.auth import _send_otp, hash_otp, hash_password, login
from services.broadcasts import (
    get_all_broadcast_rows,
    get_recent_changes,
    get_stats,
    search_broadcasts,
)
from services.community import (
    _all_reports,
    _all_users_public,
    _comments,
    _profile,
    _public_user,
)
from services.core import (
    WIB,
    _audit,
    _require_admin,
    _require_auth,
    _safe_key,
    now_wib,
)

REPORT_STATUSES = ["Menunggu", "Sedang ditinjau", "Selesai", "Ditolak"]


def _save_profile(event: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    username = _require_auth(session)
    profile_fields = ("provinsi", "wilayah", "tv_brand", "stb_brand", "antenna_brand")
    profile = {
        field: str(event.get(field, "")).strip() for field in profile_fields
    }
    db.reference(f"users/{username}").update(profile)
    return {"ok": True, "message": "Profil berhasil diperbarui."}


def _add_comment(event: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    username = _require_auth(session)
    province = _safe_key(event.get("provinsi"), "Provinsi")
    area = _safe_key(event.get("wilayah"), "Wilayah")
    mux = _safe_key(event.get("mux"), "MUX")
    comment_text = str(event.get("text", "")).strip()

    if not comment_text or len(comment_text) > 1500:
        raise ValueError("Komentar wajib diisi (maksimal 1.500 karakter).")

    user_ref = db.reference(f"users/{username}")
    user = user_ref.get() or {}
    timestamp = now_wib()
    comment = {
        "username": username,
        "nama_pengguna": user.get("nama", username),
        "timestamp": timestamp,
        "text": comment_text,
    }
    db.reference(f"siaran/{province}/{area}/{mux}/comments").push().set(comment)
    user_ref.update({"points": int(user.get("points", 0)) + 1})
    db.reference("app_metadata/last_leaderboard_update_timestamp").set(
        timestamp[:19]
    )
    return {"ok": True, "message": "Komentar terkirim. Anda mendapat 1 poin."}


def _load_community(session: dict[str, Any]) -> dict[str, Any]:
    users = _all_users_public()
    users.sort(key=lambda user: int(user.get("points", 0) or 0), reverse=True)
    username = session.get("auth", {}).get("username")
    profile = _profile(username) if username else None
    return {
        "ok": True,
        "users": users,
        "leaderboard": users,
        "profile": profile,
    }


def _load_user_profile(event: dict[str, Any]) -> dict[str, Any]:
    username = str(event.get("username", ""))
    users = db.reference("users").get() or {}
    if username not in users:
        raise ValueError("Profil pengguna tidak ditemukan.")
    return {"ok": True, "user_profile": _public_user(username, users[username])}


def _chat(event: dict[str, Any], session: dict[str, Any], secrets: dict[str, Any] | None):
    _require_auth(session)
    api_key = (secrets or {}).get("GEMINI", {}).get("api_key")
    if not api_key:
        raise RuntimeError("API Gemini belum dikonfigurasi di Secrets.")

    import google.generativeai as genai

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    prompt = (
        "Anda adalah Chatbot AI KTVDI untuk website Komunitas TV Digital Indonesia. "
        "Jawab ramah, informatif, ringkas, dan dalam bahasa Indonesia formal. "
        "Bantu tentang fitur aplikasi (login, daftar, tambah/edit data, poin, "
        "leaderboard, profil, komentar) serta TV digital Indonesia seperti DVB-T2, "
        "MUX, UHF, antena, dan STB. Jangan mengarang data siaran atau informasi "
        "real-time; arahkan ke sumber resmi bila perlu. Tambah data memberi 10 poin, "
        "edit memberi 5 poin, komentar memberi 1 poin. Format wilayah: "
        "Nama Provinsi-Angka; format MUX: UHF XX - Nama MUX.\n\n"
        + str(event.get("message", ""))[:4000]
    )
    response = model.generate_content(prompt)
    return {"ok": True, "reply": response.text}


def handle_community_handler(
    action: str,
    event: dict[str, Any],
    session: dict[str, Any],
    secrets: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Dispatch community events to their dedicated handlers."""
    handlers = {
        "save_profile": lambda: _save_profile(event, session),
        "add_comment": lambda: _add_comment(event, session),
        "load_community": lambda: _load_community(session),
        "load_user_profile": lambda: _load_user_profile(event),
        "chat": lambda: _chat(event, session, secrets),
    }
    handler = handlers.get(action)
    return handler() if handler else None
