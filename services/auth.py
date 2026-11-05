from __future__ import annotations
import hashlib
import hmac
import re
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from typing import Any
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from firebase_admin import db

# Parameter Argon2id dipertahankan sama dengan implementasi sebelumnya.
_PASSWORD_HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=19_456,  # KiB (19 MiB)
    parallelism=1,
)

def hash_password(password: str) -> str:
    """Hash password baru menggunakan Argon2id."""
    return _PASSWORD_HASHER.hash(password)


def hash_otp(otp: str) -> str:
    """Hash OTP sementara; OTP bukan password dan hanya berlaku singkat."""
    return hashlib.sha256(otp.encode("utf-8")).hexdigest()


def verify_password_and_migrate(password: str, stored_hash: str) -> tuple[bool, str | None]:
    """Verifikasi Argon2id atau SHA-256 lama; kembalikan hash baru bila perlu."""
    if not isinstance(stored_hash, str) or not stored_hash:
        return False, None

    # Hash SHA-256 lama memiliki 64 karakter heksadesimal.
    if re.fullmatch(r"[a-fA-F0-9]{64}", stored_hash):
        legacy_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        if hmac.compare_digest(legacy_hash.lower(), stored_hash.lower()):
            return True, hash_password(password)
        return False, None

    try:
        valid = _PASSWORD_HASHER.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False, None

    replacement = hash_password(password) if _PASSWORD_HASHER.check_needs_rehash(stored_hash) else None
    return bool(valid), replacement


def login(username: str, password: str) -> dict[str, Any]:
    username = username.strip()
    users = db.reference("users").get() or {}
    user = users.get(username)
    if not username or not password or not isinstance(user, dict):
        return {"ok": False, "message": "Username atau password salah."}

    valid, replacement_hash = verify_password_and_migrate(
        password, user.get("password", "")
    )
    if not valid:
        return {"ok": False, "message": "Username atau password salah."}

    # Migrasi hash lama atau pembaruan parameter Argon2id dilakukan setelah
    # password terbukti benar. Password asli tidak pernah disimpan.
    if replacement_hash:
        db.reference(f"users/{username}").update({"password": replacement_hash})

    return {"ok": True, "username": username, "nama": user.get("nama", username),
            "points": user.get("points", 0),
            "admin": db.reference(f"admins/{username}").get() is True}


def _send_otp(secrets, email, otp, purpose):
    sender=secrets["email"]["sender"]; password=secrets["email"]["app_password"]
    subject="Kode OTP Pendaftaran KTVDI" if purpose=="register" else "Kode OTP Reset Password KTVDI"
    msg=MIMEText(f"Kode OTP KTVDI Anda: {otp}. Jangan bagikan kode ini kepada siapa pun.")
    msg["Subject"]=subject; msg["From"]=sender; msg["To"]=email
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as server:
        server.login(sender,password); server.sendmail(sender,email,msg.as_string())


# Persistent browser sessions: only a SHA-256 digest of the opaque token is stored.
# The raw token is returned once to the browser and is never written to Firebase.
import secrets as _secrets
from datetime import timezone as _timezone, timedelta as _timedelta

SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


def create_persistent_session(username: str) -> str:
    """Create a revocable seven-day session and return its opaque browser token."""
    token = _secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = int(datetime.now(_timezone.utc).timestamp())
    db.reference(f"auth_sessions/{token_hash}").set({
        "username": username,
        "created_at": now,
        "expires_at": now + SESSION_TTL_SECONDS,
        "revoked": False,
    })
    return token


def restore_persistent_session(token: str) -> dict[str, Any] | None:
    """Validate a browser token and return current account data, or None."""
    if not isinstance(token, str) or len(token) < 32 or len(token) > 256:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    ref = db.reference(f"auth_sessions/{token_hash}")
    record = ref.get()
    now = int(datetime.now(_timezone.utc).timestamp())
    if not isinstance(record, dict) or record.get("revoked") is True:
        return None
    if not isinstance(record.get("expires_at"), (int, float)) or now >= record["expires_at"]:
        ref.update({"revoked": True})
        return None

    username = str(record.get("username", "")).strip()
    if not username:
        ref.update({"revoked": True})
        return None
    user = db.reference(f"users/{username}").get()
    if not isinstance(user, dict):
        ref.update({"revoked": True})
        return None

    return {
        "username": username,
        "nama": user.get("nama", username),
        "points": user.get("points", 0),
        "admin": db.reference(f"admins/{username}").get() is True,
        "_session_id": token_hash,
    }


def revoke_persistent_session(session_id: str | None) -> None:
    """Revoke the current persistent session, if one is attached."""
    if isinstance(session_id, str) and re.fullmatch(r"[a-f0-9]{64}", session_id):
        db.reference(f"auth_sessions/{session_id}").update({"revoked": True})
