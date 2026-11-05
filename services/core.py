from __future__ import annotations
from datetime import datetime
from firebase_admin import credentials, db
import firebase_admin
from pytz import timezone

DB_URL = "https://website-ktvdi-default-rtdb.firebaseio.com/"
WIB = timezone("Asia/Jakarta")

def now_wib(fmt="%Y-%m-%d %H:%M:%S WIB"):
    return datetime.now(WIB).strftime(fmt)


def initialize_firebase(secrets) -> None:
    if not firebase_admin._apps:
        cred = credentials.Certificate(dict(secrets["FIREBASE"]))
        firebase_admin.initialize_app(cred, {"databaseURL": DB_URL})


def _safe_key(value: str, label: str) -> str:
    value = str(value or "").strip()
    if not value or any(c in value for c in ".#$[]/"):
        raise ValueError(f"{label} tidak valid.")
    return value


def _audit(action, prov, wilayah, mux, username, before=None, after=None):
    user=db.reference(f"users/{username}").get() or {}
    db.reference("audit_logs").push().set({"action":action,"provinsi":prov,"wilayah":wilayah,"mux":mux,
        "username":username,"nama":user.get("nama",username),"timestamp":now_wib(),"before":before,"after":after})


def _require_auth(session):
    auth=session.get("auth")
    if not auth or not auth.get("username"): raise PermissionError("Silakan login terlebih dahulu.")
    return auth["username"]


def _require_admin(session):
    username=_require_auth(session)
    if db.reference(f"admins/{username}").get() is not True: raise PermissionError("Akses khusus admin.")
    return username
