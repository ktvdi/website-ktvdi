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


def handle_report_admin_handler(action: str, event: dict[str, Any], session: dict[str, Any], secrets=None):
    if action=="submit_report":
                username=_require_auth(session); prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
                desc=str(event.get("description"," ")).strip(); category=str(event.get("category","Lainnya")); evidence=str(event.get("evidence_url","")).strip()
                if not desc: raise ValueError("Keterangan laporan wajib diisi.")
                if evidence and not evidence.startswith(("https://","http://")): raise ValueError("Tautan bukti harus berupa URL http/https.")
                user=db.reference(f"users/{username}").get() or {}
                db.reference("broadcast_reports").push().set({"provinsi":prov,"wilayah":area,"mux":mux,"category":category,"description":desc[:1500],"evidence_url":evidence,"reporter_username":username,"reporter_name":user.get("nama",username),"status":"Menunggu","admin_note":"","created_at":now_wib()})
                return {"ok":True,"message":"Laporan koreksi berhasil dikirim."}
    if action=="admin_report_update":
                username=_require_admin(session); rid=str(event.get("id","")); status=str(event.get("status","Menunggu"))
                if status not in REPORT_STATUSES: raise ValueError("Status laporan tidak valid.")
                ref=db.reference(f"broadcast_reports/{rid}"); before=ref.get()
                if not before: raise ValueError("Laporan tidak ditemukan.")
                updates={"status":status,"admin_note":str(event.get("admin_note",""))[:1500],"resolved_by":username,"resolved_at":now_wib()}; ref.update(updates)
                _audit("update_report_status",before.get("provinsi",""),before.get("wilayah",""),before.get("mux",""),username,before,updates)
                return {"ok":True,"message":"Status laporan diperbarui."}
    if action=="admin_restore":
                username=_require_admin(session); log_id=str(event.get("log_id","")); log=(db.reference(f"audit_logs/{log_id}").get() or {})
                after=log.get("before")
                if after is None: raise ValueError("Snapshot versi sebelumnya tidak tersedia pada log ini.")
                prov=_safe_key(log.get("provinsi"),"Provinsi"); area=_safe_key(log.get("wilayah"),"Wilayah"); mux=_safe_key(log.get("mux"),"MUX")
                ref=db.reference(f"siaran/{prov}/{area}/{mux}"); before=ref.get(); ref.set(after)
                _audit("restore_broadcast",prov,area,mux,username,before,after)
                return {"ok":True,"message":"Snapshot data berhasil dipulihkan."}
    if action=="load_admin":
                _require_admin(session); logs=db.reference("audit_logs").get() or {}; logs=[{"id":k,**v} for k,v in logs.items() if isinstance(v,dict)]; logs.sort(key=lambda x:x.get("timestamp",""),reverse=True)
                return {"ok":True,"reports":_all_reports(),"logs":logs}
    return None
