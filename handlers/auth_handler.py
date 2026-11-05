from __future__ import annotations
import base64
import math
import random
import re
from datetime import datetime
from io import BytesIO
from typing import Any

from PIL import Image
from firebase_admin import db
from pytz import timezone

from services.core import now_wib, _safe_key, _audit, _require_auth, _require_admin, WIB
from services.auth import hash_password, hash_otp, login, _send_otp
from services.broadcasts import get_all_broadcast_rows, get_stats, search_broadcasts, get_recent_changes
from services.community import _public_user, _all_reports, _all_users_public, _profile, _comments

REPORT_STATUSES = ["Menunggu", "Sedang ditinjau", "Selesai", "Ditolak"]


def handle_auth_handler(action: str, event: dict[str, Any], session: dict[str, Any], secrets=None):
    if action=="login":
                result=login(str(event.get("username","")),str(event.get("password","")))
                if result.get("ok"): session["auth"]={k:result[k] for k in ("username","nama","points","admin")}
                return result
    if action=="logout": session.pop("auth",None); return {"ok":True,"message":"Anda telah logout."}
    if action=="register_request":
                if secrets is None: raise RuntimeError("Pengaturan email belum tersedia.")
                name=str(event.get("nama"," ")).strip(); email=str(event.get("email"," ")).strip().lower(); user=str(event.get("username"," ")).strip(); pw=str(event.get("password",""))
                if not all([name,email,user,pw]): raise ValueError("Semua kolom wajib diisi.")
                if not re.fullmatch(r"[a-z0-9]+",user): raise ValueError("Username hanya boleh huruf kecil dan angka.")
                if len(pw)<6: raise ValueError("Password minimal 6 karakter.")
                users=db.reference("users").get() or {}
                if user in users: raise ValueError("Username sudah digunakan.")
                if any(str(v.get("email"," ")).lower()==email for v in users.values() if isinstance(v,dict)): raise ValueError("Email sudah terdaftar.")
                otp=f"{random.SystemRandom().randint(0,999999):06d}"
                _send_otp(secrets,email,otp,"register")
                session["pending_register"]={"nama":name,"email":email,"username":user,"password":hash_password(pw),"otp_hash":hash_otp(otp),"expires":datetime.now().timestamp()+600}
                return {"ok":True,"message":"OTP pendaftaran dikirim ke email. Berlaku 10 menit."}
    if action=="register_verify":
                pending=session.get("pending_register") or {}
                if not pending or datetime.now().timestamp()>pending.get("expires",0): raise ValueError("Sesi OTP tidak ada atau sudah kedaluwarsa. Ulangi pendaftaran.")
                if hash_otp(str(event.get("otp","")))!=pending["otp_hash"]: raise ValueError("Kode OTP salah.")
                username=pending["username"]
                db.reference(f"users/{username}").set({"nama":pending["nama"],"email":pending["email"],"password":pending["password"],"points":0})
                session.pop("pending_register",None)
                return {"ok":True,"message":"Akun berhasil dibuat. Silakan login."}
    if action=="forgot_request":
                if secrets is None: raise RuntimeError("Pengaturan email belum tersedia.")
                email=str(event.get("email"," ")).strip().lower(); users=db.reference("users").get() or {}
                found=next(((u,v) for u,v in users.items() if str(v.get("email"," ")).lower()==email),None)
                if not found: raise ValueError("Email tidak ditemukan atau tidak terdaftar.")
                otp=f"{random.SystemRandom().randint(0,999999):06d}"; _send_otp(secrets,email,otp,"reset")
                session["pending_reset"]={"username":found[0],"otp_hash":hash_otp(otp),"expires":datetime.now().timestamp()+600}
                return {"ok":True,"message":f"OTP dikirim. Username akun: {found[0]}. Berlaku 10 menit."}
    if action=="forgot_reset":
                pending=session.get("pending_reset") or {}
                if not pending or datetime.now().timestamp()>pending.get("expires",0): raise ValueError("Sesi OTP tidak ada atau sudah kedaluwarsa.")
                if hash_otp(str(event.get("otp","")))!=pending["otp_hash"]: raise ValueError("Kode OTP salah.")
                pw=str(event.get("password",""))
                if len(pw)<6: raise ValueError("Password minimal 6 karakter.")
                db.reference(f"users/{pending['username']}").update({"password":hash_password(pw)})
                session.pop("pending_reset",None)
                return {"ok":True,"message":"Password berhasil direset. Silakan login."}
    return None
