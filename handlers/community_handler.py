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


def handle_community_handler(action: str, event: dict[str, Any], session: dict[str, Any], secrets=None):
    if action=="save_profile":
                username=_require_auth(session); keys=("provinsi","wilayah","tv_brand","stb_brand","antenna_brand")
                db.reference(f"users/{username}").update({k:str(event.get(k,"")).strip() for k in keys})
                return {"ok":True,"message":"Profil berhasil diperbarui."}
    if action=="add_comment":
                username=_require_auth(session); prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX"); body=str(event.get("text"," ")).strip()
                if not body or len(body)>1500: raise ValueError("Komentar wajib diisi (maksimal 1.500 karakter).")
                userref=db.reference(f"users/{username}"); u=userref.get() or {}; stamp=now_wib()
                db.reference(f"siaran/{prov}/{area}/{mux}/comments").push().set({"username":username,"nama_pengguna":u.get("nama",username),"timestamp":stamp,"text":body})
                userref.update({"points":int(u.get("points",0))+1}); db.reference("app_metadata/last_leaderboard_update_timestamp").set(stamp[:19])
                return {"ok":True,"message":"Komentar terkirim. Anda mendapat 1 poin."}
    if action=="load_community":
                users=_all_users_public(); users.sort(key=lambda x:int(x.get("points",0) or 0),reverse=True)
                return {"ok":True,"users":users,"leaderboard":users,"profile":_profile(session['auth']['username']) if session.get('auth') else None}
    if action=="load_user_profile":
                username=str(event.get("username","")); users=db.reference("users").get() or {}
                if username not in users: raise ValueError("Profil pengguna tidak ditemukan.")
                return {"ok":True,"user_profile":_public_user(username,users[username])}
    if action=="chat":
                _require_auth(session)
                if not secrets or not secrets.get("GEMINI",{}).get("api_key"): raise RuntimeError("API Gemini belum dikonfigurasi di Secrets.")
                import google.generativeai as genai
                genai.configure(api_key=secrets["GEMINI"]["api_key"])
                model=genai.GenerativeModel("gemini-2.5-flash")
                prompt=("Anda adalah Chatbot AI KTVDI untuk website Komunitas TV Digital Indonesia. "
                    "Jawab ramah, informatif, ringkas, dan dalam bahasa Indonesia formal. "
                    "Bantu tentang fitur aplikasi (login, daftar, tambah/edit data, poin, leaderboard, profil, komentar) "
                    "serta TV digital Indonesia seperti DVB-T2, MUX, UHF, antena, dan STB. "
                    "Jangan mengarang data siaran atau informasi real-time; arahkan ke sumber resmi bila perlu. "
                    "Tambah data memberi 10 poin, edit memberi 5 poin, komentar memberi 1 poin. "
                    "Format wilayah: Nama Provinsi-Angka; format MUX: UHF XX - Nama MUX.\n\n"
                    +str(event.get("message",""))[:4000])
                response=model.generate_content(prompt)
                return {"ok":True,"reply":response.text}
    return None
