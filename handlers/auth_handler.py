from __future__ import annotations

import random
import re
from datetime import datetime
from typing import Any

from firebase_admin import db

from services.auth import hash_otp, hash_password, login, _send_otp


def _login_user(event: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    result = login(str(event.get("username", "")), str(event.get("password", "")))
    if result.get("ok"):
        session["auth"] = {
            key: result[key] for key in ("username", "nama", "points", "admin")
        }
    return result


def _request_registration(
    event: dict[str, Any], session: dict[str, Any], secrets: dict[str, Any] | None
) -> dict[str, Any]:
    if secrets is None:
        raise RuntimeError("Pengaturan email belum tersedia.")

    name = str(event.get("nama", "")).strip()
    email = str(event.get("email", "")).strip().lower()
    username = str(event.get("username", "")).strip()
    password = str(event.get("password", ""))

    if not all((name, email, username, password)):
        raise ValueError("Semua kolom wajib diisi.")
    if not re.fullmatch(r"[a-z0-9]+", username):
        raise ValueError("Username hanya boleh huruf kecil dan angka.")
    if len(password) < 6:
        raise ValueError("Password minimal 6 karakter.")

    users = db.reference("users").get() or {}
    if username in users:
        raise ValueError("Username sudah digunakan.")
    if any(
        str(user.get("email", "")).lower() == email
        for user in users.values()
        if isinstance(user, dict)
    ):
        raise ValueError("Email sudah terdaftar.")

    otp = f"{random.SystemRandom().randint(0, 999999):06d}"
    _send_otp(secrets, email, otp, "register")
    session["pending_register"] = {
        "nama": name,
        "email": email,
        "username": username,
        "password": hash_password(password),
        "otp_hash": hash_otp(otp),
        "expires": datetime.now().timestamp() + 600,
    }
    return {
        "ok": True,
        "message": "OTP pendaftaran dikirim ke email. Berlaku 10 menit.",
    }


def _verify_registration(
    event: dict[str, Any], session: dict[str, Any]
) -> dict[str, Any]:
    pending = session.get("pending_register") or {}
    if not pending or datetime.now().timestamp() > pending.get("expires", 0):
        raise ValueError(
            "Sesi OTP tidak ada atau sudah kedaluwarsa. Ulangi pendaftaran."
        )
    if hash_otp(str(event.get("otp", ""))) != pending["otp_hash"]:
        raise ValueError("Kode OTP salah.")

    username = pending["username"]
    db.reference(f"users/{username}").set(
        {
            "nama": pending["nama"],
            "email": pending["email"],
            "password": pending["password"],
            "points": 0,
        }
    )
    session.pop("pending_register", None)
    return {"ok": True, "message": "Akun berhasil dibuat. Silakan login."}


def _request_password_reset(
    event: dict[str, Any], session: dict[str, Any], secrets: dict[str, Any] | None
) -> dict[str, Any]:
    if secrets is None:
        raise RuntimeError("Pengaturan email belum tersedia.")

    email = str(event.get("email", "")).strip().lower()
    users = db.reference("users").get() or {}
    account = next(
        (
            (username, user)
            for username, user in users.items()
            if isinstance(user, dict)
            and str(user.get("email", "")).lower() == email
        ),
        None,
    )
    if account is None:
        raise ValueError("Email tidak ditemukan atau tidak terdaftar.")

    username, _user = account
    otp = f"{random.SystemRandom().randint(0, 999999):06d}"
    _send_otp(secrets, email, otp, "reset")
    session["pending_reset"] = {
        "username": username,
        "otp_hash": hash_otp(otp),
        "expires": datetime.now().timestamp() + 600,
    }
    return {
        "ok": True,
        "message": f"OTP dikirim. Username akun: {username}. Berlaku 10 menit.",
    }


def _reset_password(
    event: dict[str, Any], session: dict[str, Any]
) -> dict[str, Any]:
    pending = session.get("pending_reset") or {}
    if not pending or datetime.now().timestamp() > pending.get("expires", 0):
        raise ValueError("Sesi OTP tidak ada atau sudah kedaluwarsa.")
    if hash_otp(str(event.get("otp", ""))) != pending["otp_hash"]:
        raise ValueError("Kode OTP salah.")

    password = str(event.get("password", ""))
    if len(password) < 6:
        raise ValueError("Password minimal 6 karakter.")

    db.reference(f"users/{pending['username']}").update(
        {"password": hash_password(password)}
    )
    session.pop("pending_reset", None)
    return {"ok": True, "message": "Password berhasil direset. Silakan login."}


def handle_auth_handler(
    action: str,
    event: dict[str, Any],
    session: dict[str, Any],
    secrets: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Dispatch authentication events to their dedicated handlers."""
    handlers = {
        "login": lambda: _login_user(event, session),
        "register_request": lambda: _request_registration(event, session, secrets),
        "register_verify": lambda: _verify_registration(event, session),
        "forgot_request": lambda: _request_password_reset(event, session, secrets),
        "forgot_reset": lambda: _reset_password(event, session),
    }

    if action == "logout":
        session.pop("auth", None)
        return {"ok": True, "message": "Anda telah logout."}

    handler = handlers.get(action)
    return handler() if handler else None
