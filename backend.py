"""Orkestrasi event frontend KTVDI dan facade kompatibilitas layanan.

Fungsi layanan dipisahkan ke paket ``services`` berdasarkan tanggung jawab.
Modul ini mempertahankan ``handle_event`` sebagai titik masuk yang dipakai app.py.
"""
from __future__ import annotations

import math
import random
import re
from datetime import datetime
from typing import Any

from firebase_admin import db
from pytz import timezone

from services.core import (
    DB_URL, WIB, now_wib, initialize_firebase, _safe_key, _audit,
    _require_auth, _require_admin,
)
from services.auth import (
    _PASSWORD_HASHER, hash_password, hash_otp,
    verify_password_and_migrate, login, _send_otp,
)
from services.broadcasts import (
    get_all_broadcast_rows, get_latest_transmitter_update_timestamp,
    get_stats, search_broadcasts, get_recent_changes,
)
from services.community import (
    _public_user, _all_reports, _all_users_public, _profile, _comments,
)

REPORT_STATUSES = ["Menunggu", "Sedang ditinjau", "Selesai", "Ditolak"]

def handle_event(event: dict[str, Any], session: dict[str, Any], secrets=None) -> dict[str, Any]:
    """Aksi dari frontend. Otorisasi dan validasi selalu dilakukan ulang di server."""
    action=event.get("action")
    try:
        if action=="login":
            result=login(str(event.get("username","")),str(event.get("password","")))
            if result.get("ok"): session["auth"]={k:result[k] for k in ("username","nama","points","admin")}
            return result
        if action=="logout": session.pop("auth",None); return {"ok":True,"message":"Anda telah logout."}
        if action=="search": return {"ok":True,"results":search_broadcasts(str(event.get("query","")))}
        if action in ("refresh",None): return {"ok":True,"stats":get_stats(),"rows":get_all_broadcast_rows(),"changes":get_recent_changes()}
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
        if action=="load_broadcast_edit_requests":
            username=_require_auth(session)
            is_admin=db.reference(f"admins/{username}").get() is True
            tree=db.reference("broadcast_edit_requests").get() or {}
            visible=[]
            for prov, areas in (tree.items() if isinstance(tree,dict) else []):
                if not isinstance(areas,dict): continue
                for area, muxes in areas.items():
                    if not isinstance(muxes,dict): continue
                    for mux, requests in muxes.items():
                        if not isinstance(requests,dict): continue
                        record=db.reference(f"siaran/{prov}/{area}/{mux}").get() or {}
                        owner=(record.get("created_by_username") or record.get("last_updated_by_username")) if isinstance(record,dict) else None
                        for requester, req in requests.items():
                            if not isinstance(req,dict) or req.get("status") not in ("Menunggu","Disetujui","Ditolak"): continue
                            if is_admin or requester==username or (owner and owner==username):
                                visible.append({"provinsi":prov,"wilayah":area,"mux":mux,"requester":requester,**req,
                                    "can_review":bool(is_admin or (owner and owner==username))})
            visible.sort(key=lambda x:(x.get("status")!="Menunggu",x.get("requested_at","")),reverse=False)
            return {"ok":True,"broadcast_edit_requests":visible}
        if action=="submit_broadcast_edit_request":
            username=_require_auth(session)
            prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
            reason=str(event.get("reason","")).strip()
            if len(reason)<10: raise ValueError("Alasan perubahan minimal 10 karakter.")
            if len(reason)>1000: raise ValueError("Alasan terlalu panjang (maksimal 1.000 karakter).")
            raw=event.get("siaran",[])
            channels=raw if isinstance(raw,list) else str(raw).split(",")
            channels=sorted({str(x).strip() for x in channels if str(x).strip()})
            if not channels: raise ValueError("Usulan daftar kanal tidak boleh kosong.")
            if len(channels)>100: raise ValueError("Maksimal 100 kanal dalam satu permohonan.")
            if any(not re.fullmatch(r"^[a-zA-Z0-9\s&()_.,'-]+$",c) for c in channels):
                raise ValueError("Nama kanal mengandung karakter yang tidak diizinkan.")
            record=db.reference(f"siaran/{prov}/{area}/{mux}").get()
            if not record: raise ValueError("Data MUX tidak ditemukan.")
            owner=(record.get("created_by_username") or record.get("last_updated_by_username")) if isinstance(record,dict) else None
            is_admin=db.reference(f"admins/{username}").get() is True
            if is_admin or owner==username: raise ValueError("Anda sudah memiliki hak edit langsung untuk data ini.")
            user=db.reference(f"users/{username}").get() or {}
            req_ref=db.reference(f"broadcast_edit_requests/{prov}/{area}/{mux}/{username}")
            previous=req_ref.get() or {}
            if previous.get("status")=="Menunggu": raise ValueError("Permohonan Anda untuk MUX ini masih menunggu persetujuan.")
            req={"requester_name":user.get("nama",username),"reason":reason,"proposed_channels":channels,
                 "current_channels":record.get("siaran",[]) if isinstance(record,dict) else [],
                 "status":"Menunggu","requested_at":now_wib(),
                 "owner_username":owner or ""}
            req_ref.set(req)
            _audit("submit_broadcast_edit_request",prov,area,mux,username,{"siaran":req["current_channels"]},req)
            return {"ok":True,"message":"Permohonan perubahan kanal dikirim kepada admin/penginput data."}
        if action in ("approve_broadcast_edit_request","reject_broadcast_edit_request"):
            username=_require_auth(session)
            prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
            requester=_safe_key(event.get("requester"),"Username")
            ref=db.reference(f"siaran/{prov}/{area}/{mux}"); record=ref.get()
            if not record: raise ValueError("Data MUX tidak ditemukan.")
            owner=(record.get("created_by_username") or record.get("last_updated_by_username")) if isinstance(record,dict) else None
            is_admin=db.reference(f"admins/{username}").get() is True
            if not is_admin and owner!=username: raise PermissionError("Hanya admin atau penginput asli yang dapat memproses permohonan.")
            req_ref=db.reference(f"broadcast_edit_requests/{prov}/{area}/{mux}/{requester}")
            req=req_ref.get() or {}
            if req.get("status")!="Menunggu": raise ValueError("Permohonan sudah diproses atau tidak ditemukan.")
            before=record
            if action=="approve_broadcast_edit_request":
                channels=req.get("proposed_channels") or []
                if not isinstance(channels,list) or not channels: raise ValueError("Usulan kanal tidak valid.")
                if (record.get("siaran",[]) if isinstance(record,dict) else []) != req.get("current_channels",[]):
                    raise ValueError("Daftar kanal telah berubah sejak permohonan dibuat. Tinjau ulang sebelum menyetujui.")
                if any(not isinstance(c,str) or not c.strip() or not re.fullmatch(r"^[a-zA-Z0-9\s&()_.,'-]+$",c) for c in channels):
                    raise ValueError("Usulan berisi nama kanal yang tidak valid.")
                after={**record,"siaran":channels,"last_updated_by_username":username,
                    "last_updated_by_name":(db.reference(f"users/{username}").get() or {}).get("nama",username),
                    "last_updated_date":now_wib("%d-%m-%Y"),"last_updated_time":now_wib("%H:%M:%S WIB")}
                ref.set(after)
                req.update({"status":"Disetujui","reviewed_by_username":username,"reviewed_at":now_wib(),
                    "applied_at":now_wib()})
                _audit("approve_broadcast_edit_request",prov,area,mux,username,before,after)
            else:
                req.update({"status":"Ditolak","reviewed_by_username":username,"reviewed_at":now_wib()})
                _audit("reject_broadcast_edit_request",prov,area,mux,username,req,None)
            req_ref.set(req)
            return {"ok":True,"message":"Permohonan perubahan kanal "+("disetujui dan langsung diterapkan." if action=="approve_broadcast_edit_request" else "ditolak.")}
        if action=="add_broadcast":
            username=_require_auth(session); prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
            channels=sorted({x.strip() for x in str(event.get("siaran","")).split(",") if x.strip()})
            area=re.sub(r"\s*-\s*","-",area)
            if not re.fullmatch(r"^[a-zA-Z\s]+-\d+$",area): raise ValueError("Format wilayah harus seperti 'Jawa Barat-1'.")
            if area.rsplit("-",1)[0].strip().casefold()!=prov.casefold(): raise ValueError("Nama provinsi pada wilayah harus sama dengan provinsi yang dipilih.")
            if not re.fullmatch(r"UHF\s+\d{1,3}\s*-\s*.+",mux,re.I): raise ValueError("Format MUX harus seperti 'UHF 27 - Nama MUX'.")
            if not channels: raise ValueError("Daftar kanal tidak boleh kosong.")
            if any(not re.fullmatch(r"^[a-zA-Z0-9\s&()_.,'-]+$",c) for c in channels): raise ValueError("Nama kanal mengandung karakter yang tidak diizinkan.")
            path=f"siaran/{prov}/{area}/{mux}"; before=db.reference(path).get()
            if before: raise ValueError("Data MUX tersebut sudah ada. Gunakan fitur edit.")
            user=db.reference(f"users/{username}"); udata=user.get() or {}; stamp=now_wib()
            data={"siaran":channels,"created_by_username":username,"last_updated_by_username":username,"last_updated_by_name":udata.get("nama",username),"last_updated_date":now_wib("%d-%m-%Y"),"last_updated_time":now_wib("%H:%M:%S WIB")}
            db.reference(path).set(data); _audit("add_broadcast",prov,area,mux,username,None,data)
            user.update({"points":int(udata.get("points",0))+10}); db.reference("app_metadata/last_leaderboard_update_timestamp").set(stamp[:19])
            return {"ok":True,"message":"Data siaran berhasil ditambahkan. Anda mendapat 10 poin."}
        if action in ("edit_broadcast","delete_broadcast"):
            username=_require_auth(session); prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
            ref=db.reference(f"siaran/{prov}/{area}/{mux}"); before=ref.get()
            if not before: raise ValueError("Data MUX tidak ditemukan.")
            # created_by_username adalah pemilik tetap. Untuk data lama, gunakan
            # last_updated_by_username sebagai fallback. Data tanpa identitas
            # pemilik hanya boleh dikelola admin.
            owner = None
            if isinstance(before, dict):
                owner = before.get("created_by_username") or before.get("last_updated_by_username")
            admin = db.reference(f"admins/{username}").get() is True
            if not admin and (not owner or owner != username):
                verb = "mengedit" if action == "edit_broadcast" else "menghapus"
                raise PermissionError(f"Anda hanya dapat {verb} data yang Anda tambahkan. Data tanpa pemilik hanya dapat dikelola admin.")
            if action=="edit_broadcast":
                channels=sorted({x.strip() for x in str(event.get("siaran","")).split(",") if x.strip()})
                if not channels: raise ValueError("Daftar kanal tidak boleh kosong.")
                new_area=_safe_key(event.get("new_wilayah",area),"Wilayah baru"); new_mux=_safe_key(event.get("new_mux",mux),"MUX baru")
                new_area=re.sub(r"\s*-\s*","-",new_area)
                if not re.fullmatch(r"^[a-zA-Z\s]+-\d+$",new_area): raise ValueError("Format wilayah harus seperti 'Jawa Barat-1'.")
                if new_area.rsplit("-",1)[0].strip().casefold()!=prov.casefold(): raise ValueError("Nama provinsi pada wilayah harus sama dengan provinsi yang dipilih.")
                if not re.fullmatch(r"UHF\s+\d{1,3}\s*-\s*.+",new_mux,re.I): raise ValueError("Format MUX harus seperti 'UHF 27 - Nama MUX'.")
                if any(not re.fullmatch(r"^[a-zA-Z0-9\s&()_.,'-]+$",c) for c in channels): raise ValueError("Nama kanal mengandung karakter yang tidak diizinkan.")
                user=db.reference(f"users/{username}").get() or {}; after={**(before if isinstance(before,dict) else {}),"siaran":channels,"last_updated_by_username":username,"last_updated_by_name":user.get("nama",username),"last_updated_date":now_wib("%d-%m-%Y"),"last_updated_time":now_wib("%H:%M:%S WIB")}
                new_ref=db.reference(f"siaran/{prov}/{new_area}/{new_mux}")
                if (new_area,new_mux)!=(area,mux):
                    if new_ref.get(): raise ValueError("Tujuan wilayah/MUX sudah digunakan.")
                    new_ref.set(after); ref.delete()
                else: ref.set(after)
                _audit("edit_broadcast",prov,area,mux,username,before,{"new_wilayah":new_area,"new_mux":new_mux,"data":after})
                userref=db.reference(f"users/{username}"); userref.update({"points":int(user.get("points",0))+5})
                db.reference("app_metadata/last_leaderboard_update_timestamp").set(now_wib("%Y-%m-%d %H:%M:%S"))
            else:
                if owner and owner != username and not admin: raise PermissionError("Anda hanya dapat menghapus data yang Anda tambahkan, kecuali admin.")
                ref.delete(); _audit("delete_broadcast",prov,area,mux,username,before,None)
            return {"ok":True,"message":"Perubahan data berhasil disimpan."}
        if action=="save_technical":
            # Parameter teknis memengaruhi estimasi cakupan; perubahan harus
            # diverifikasi dan hanya dapat dilakukan oleh admin.
            username=_require_admin(session); prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
            ref=db.reference(f"siaran/{prov}/{area}/{mux}"); before=ref.get() or {}
            if not before: raise ValueError("Data MUX tidak ditemukan.")
            parsed={}
            for key in ("tx_height_m","tx_power_w","erp_w","antenna_gain_dbd","feeder_loss_db"):
                raw=str(event.get(key," ")).strip()
                if not raw: continue
                try: val=float(raw.replace(",","."))
                except ValueError: raise ValueError(f"Nilai {key} harus berupa angka.")
                if not __import__("math").isfinite(val): raise ValueError(f"Nilai {key} tidak valid.")
                if key in ("tx_height_m","tx_power_w","erp_w") and val<=0: raise ValueError(f"{key} harus lebih besar dari 0.")
                if key=="feeder_loss_db" and val<0: raise ValueError("Rugi feeder tidak boleh negatif.")
                if key=="antenna_gain_dbd" and not -10<=val<=30: raise ValueError("Gain antena harus -10 hingga 30 dBd.")
                parsed[key]=val
            if not parsed and not str(event.get("technical_data_reference"," ")).strip(): raise ValueError("Isi minimal satu parameter atau referensi.")
            after={**before,**parsed,"technical_data_updated_at":now_wib(),"technical_data_updated_by":username}
            if str(event.get("technical_data_reference"," ")).strip(): after["technical_data_reference"]=str(event["technical_data_reference"]).strip()[:500]
            ref.set(after); _audit("update_transmitter_technical_data",prov,area,mux,username,before,after)
            return {"ok":True,"message":"Data teknis pemancar berhasil disimpan."}
        if action=="load_point_requests":
            username=_require_auth(session)
            is_admin=db.reference(f"admins/{username}").get() is True
            tree=db.reference("point_change_requests").get() or {}
            visible=[]
            for prov, areas in (tree.items() if isinstance(tree,dict) else []):
                if not isinstance(areas,dict): continue
                for area, muxes in areas.items():
                    if not isinstance(muxes,dict): continue
                    for mux, requests in muxes.items():
                        if not isinstance(requests,dict): continue
                        point=(db.reference(f"siaran/{prov}/{area}/{mux}").get() or {})
                        point_owner=point.get("point_added_by_username") if isinstance(point,dict) else None
                        for requester, req in requests.items():
                            if not isinstance(req,dict): continue
                            if req.get("status") not in ("Menunggu","Disetujui"): continue
                            if req.get("status")=="Disetujui" and requester!=username: continue
                            if is_admin or requester==username or (point_owner and point_owner==username):
                                visible.append({"provinsi":prov,"wilayah":area,"mux":mux,
                                    "requester":requester,**req,
                                    "approval_scope":"admin" if not point_owner else "admin_atau_pembuat"})
            return {"ok":True,"point_requests":visible}
        if action=="submit_point_change_request":
            username=_require_auth(session)
            prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
            reason=str(event.get("reason","")).strip()
            if len(reason)<10: raise ValueError("Jelaskan alasan perubahan minimal 10 karakter.")
            if len(reason)>1000: raise ValueError("Alasan terlalu panjang (maksimal 1.000 karakter).")
            point=db.reference(f"siaran/{prov}/{area}/{mux}").get() or {}
            if not point or point.get("latitude") is None or point.get("longitude") is None:
                raise ValueError("Titik pemancar belum tersedia. Gunakan fitur tambah titik.")
            if point.get("point_added_by_username")==username:
                raise ValueError("Anda adalah pembuat titik ini dan dapat mengubahnya langsung.")
            admin=db.reference(f"admins/{username}").get() is True
            if admin: raise ValueError("Admin dapat mengubah titik secara langsung.")
            user=db.reference(f"users/{username}").get() or {}
            req_ref=db.reference(f"point_change_requests/{prov}/{area}/{mux}/{username}")
            old=req_ref.get() or {}
            if old.get("status")=="Menunggu":
                raise ValueError("Permohonan Anda untuk titik ini masih menunggu persetujuan.")
            req={"requester_name":user.get("nama",username),"reason":reason,
                 "status":"Menunggu","requested_at":now_wib(),
                 "point_added_by_username":point.get("point_added_by_username",""),
                 "point_added_by_name":point.get("point_added_by_name","")}
            req_ref.set(req)
            _audit("submit_point_change_request",prov,area,mux,username,{},req)
            return {"ok":True,"message":"Permohonan perubahan titik dikirim. Perubahan baru dapat disimpan setelah disetujui admin dan/atau pembuat titik."}
        if action in ("approve_point_change_request","reject_point_change_request"):
            username=_require_auth(session)
            prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
            requester=_safe_key(event.get("requester"),"Username")
            ref=db.reference(f"siaran/{prov}/{area}/{mux}"); point=ref.get() or {}
            if not point: raise ValueError("Data pemancar tidak ditemukan.")
            req_ref=db.reference(f"point_change_requests/{prov}/{area}/{mux}/{requester}")
            req=req_ref.get() or {}
            if req.get("status")!="Menunggu": raise ValueError("Permohonan sudah diproses atau tidak ditemukan.")
            admin=db.reference(f"admins/{username}").get() is True
            point_owner=point.get("point_added_by_username") if isinstance(point,dict) else None
            if not admin and (not point_owner or point_owner!=username):
                raise PermissionError("Hanya admin atau pembuat titik yang dapat memutuskan permohonan ini. Untuk titik tanpa identitas pembuat, hanya admin.")
            status="Disetujui" if action=="approve_point_change_request" else "Ditolak"
            req.update({"status":status,"reviewed_by_username":username,
                        "reviewed_by_name":(db.reference(f"users/{username}").get() or {}).get("nama",username),
                        "reviewed_at":now_wib()})
            req_ref.set(req)
            _audit(action,prov,area,mux,username,{"requester":requester},{"status":status})
            return {"ok":True,"message":f"Permohonan perubahan titik {status.lower()}."}

        if action=="save_coordinates":
            # Hak kelola titik pemancar terpisah dari kepemilikan data MUX.
            # Pembuat titik (point_added_by_username) dan admin dapat mengubahnya.
            username=_require_auth(session); prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
            try: lat=float(event.get("latitude")); lon=float(event.get("longitude"))
            except (TypeError,ValueError): raise ValueError("Koordinat harus berupa angka.")
            if not (-11<=lat<=6 and 95<=lon<=141): raise ValueError("Koordinat berada di luar rentang wilayah Indonesia.")
            ref=db.reference(f"siaran/{prov}/{area}/{mux}"); before=ref.get() or {}
            if not before: raise ValueError("Data MUX tidak ditemukan.")
            has=before.get("latitude") is not None and before.get("longitude") is not None
            admin=db.reference(f"admins/{username}").get() is True
            point_owner=before.get("point_added_by_username") if isinstance(before,dict) else None
            approved_request_ref=db.reference(f"point_change_requests/{prov}/{area}/{mux}/{username}")
            approved_request=approved_request_ref.get() or {}
            has_approval=approved_request.get("status")=="Disetujui"
            if has and not admin and point_owner != username and not has_approval:
                if point_owner:
                    raise PermissionError("Anda perlu mengajukan permohonan dan menunggu persetujuan admin dan/atau pembuat titik sebelum mengubah koordinat.")
                raise PermissionError("Titik lama belum memiliki identitas pembuat. Ajukan permohonan; hanya admin yang dapat menyetujuinya.")
            user=db.reference(f"users/{username}").get() or {}
            after={**before,"latitude":lat,"longitude":lon,
                   "point_last_updated_by_username":username,
                   "point_last_updated_by_name":user.get("nama",username),
                   "point_last_updated_at":now_wib()}
            if not has:
                after.update({"point_added_by_username":username,
                              "point_added_by_name":user.get("nama",username),
                              "point_added_at":now_wib()})
            ref.set(after)
            if has and has_approval and point_owner != username and not admin:
                approved_request.update({"status":"Selesai","completed_at":now_wib()})
                approved_request_ref.set(approved_request)
            _audit("update_coordinates" if has else "add_coordinates",prov,area,mux,username,before,after)
            return {"ok":True,"message":"Titik pemancar berhasil disimpan. Hak pengelola titik tercatat terpisah dari pemilik data MUX."}
        if action=="delete_coordinates":
            username=_require_auth(session); prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
            ref=db.reference(f"siaran/{prov}/{area}/{mux}"); before=ref.get() or {}
            if not before or before.get("latitude") is None or before.get("longitude") is None:
                raise ValueError("Titik koordinat tidak ditemukan.")
            admin=db.reference(f"admins/{username}").get() is True
            point_owner=before.get("point_added_by_username") if isinstance(before,dict) else None
            if not admin and point_owner != username:
                if point_owner:
                    raise PermissionError("Hanya admin atau pengguna yang menambahkan titik ini yang dapat menghapusnya. Pemilik data MUX tidak otomatis memiliki hak atas titik pemancar.")
                raise PermissionError("Titik lama belum memiliki catatan pembuat. Hanya admin yang dapat menghapusnya.")
            point_keys=("latitude","longitude","point_added_by_username","point_added_by_name","point_added_at","point_last_updated_by_username","point_last_updated_by_name","point_last_updated_at")
            after={k:v for k,v in before.items() if k not in point_keys}; ref.set(after)
            _audit("delete_coordinates",prov,area,mux,username,before,after)
            return {"ok":True,"message":"Titik pemancar dihapus; data MUX dan kanal siaran tetap tersimpan."}
        if action=="submit_measurement":
            username=_require_auth(session); prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
            try: lat=float(event.get("latitude")); lon=float(event.get("longitude")); strength=int(event.get("strength")); quality=int(event.get("quality"))
            except (TypeError,ValueError): raise ValueError("Koordinat, strength, dan quality harus valid.")
            if not (-11<=lat<=6 and 95<=lon<=141): raise ValueError("Koordinat laporan tidak valid untuk Indonesia.")
            if not (0<=strength<=100 and 0<=quality<=100): raise ValueError("Strength dan quality harus 0–100%.")
            def optional_num(k,lo,hi):
                raw=str(event.get(k," ")).strip()
                if not raw:return None
                try:v=float(raw.replace(",","."))
                except ValueError:raise ValueError(f"{k.upper()} harus berupa angka.")
                if not lo<=v<=hi:raise ValueError(f"{k.upper()} di luar rentang yang diizinkan.")
                return v
            snr=optional_num("snr",-10,60); ber=optional_num("ber",0,1)
            u=db.reference(f"users/{username}").get() or {}; stamp=now_wib()
            measurement={"username":username,"display_name":u.get("nama",username),"latitude":lat,"longitude":lon,"strength":strength,"quality":quality,"snr":snr,"ber":ber,"antenna_type":str(event.get("antenna_type","Tidak tahu")),"device_type":str(event.get("device_type","Lainnya")),"notes":str(event.get("notes",""))[:250],"timestamp":stamp,"created_at":datetime.now(WIB).isoformat()}
            db.reference(f"signal_measurements/{prov}/{area}/{mux}").push().set(measurement)
            return {"ok":True,"message":"Hasil pengukuran sinyal berhasil dikirim."}
        if action=="calculate_terrain":
            # Prediksi terrain adalah informasi publik seperti pada aplikasi lama;
            # login hanya diperlukan untuk aksi tulis (data teknis/laporan).
            prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
            rows=[r for r in get_all_broadcast_rows() if r["provinsi"]==prov and r["wilayah"]==area and r["mux"]==mux]
            if not rows: raise ValueError("Data pemancar tidak ditemukan.")
            row=rows[0]
            try: lat=float(row.get("latitude")); lon=float(row.get("longitude"))
            except (TypeError,ValueError): raise ValueError("Pemancar belum memiliki koordinat valid.")
            from terrain import _terrain_dem_coverage, _uhf_frequency_mhz
            if not _uhf_frequency_mhz(mux): raise ValueError("Prediksi terrain memerlukan kanal UHF 21–48.")
            # Tanpa parameter simulasi, gunakan data teknis pemancar yang tersimpan.
            # Nilai fallback hanya dipakai oleh model bila data teknis belum tersedia.
            # Jika form simulasi dikirim, semua override hanya berlaku untuk hitungan ini
            # dan tidak pernah ditulis ke Firebase.
            simulation_keys=("erp_w","tx_height_m","rx_height_m","rx_threshold_dbm","extra_loss_db")
            is_simulation=any(k in event and str(event.get(k,"")).strip()!="" for k in simulation_keys)
            def sim_number(name, default, minimum, maximum):
                raw=event.get(name, default)
                try: value=float(raw)
                except (TypeError,ValueError): raise ValueError(f"Nilai {name} harus berupa angka.")
                if not math.isfinite(value) or value<minimum or value>maximum:
                    raise ValueError(f"Nilai {name} di luar batas yang diizinkan.")
                return value
            sim_rx=sim_number("rx_height_m",10,1,300)
            sim_threshold=sim_number("rx_threshold_dbm",-90,-130,-30)
            sim_loss=sim_number("extra_loss_db",4,0,60)
            if is_simulation:
                sim_erp=sim_number("erp_w",1000,0.1,10000000)
                sim_tx=sim_number("tx_height_m",30,1,1000)
                tx_for_calc={**row,"detail":{**(row.get("detail") or {}),"erp_w":sim_erp,"tx_height_m":sim_tx}}
                fallback_erp=sim_erp
                fallback_tx=sim_tx
            else:
                tx_for_calc=row
                fallback_erp=1000.0
                fallback_tx=30.0
            layers=_terrain_dem_coverage([{**tx_for_calc,"latitude":lat,"longitude":lon}],lat,lon,
                erp_watt=fallback_erp,tx_height_m=fallback_tx,rx_height_m=sim_rx,
                rx_threshold_dbm=sim_threshold,extra_loss_db=sim_loss,max_transmitters=1)
            if not layers: raise ValueError("Tidak ada hasil prediksi terrain.")
            from io import BytesIO
            import base64
            from PIL import Image
            layer=layers[0]; image=Image.fromarray(layer["image"],mode="RGBA"); buf=BytesIO(); image.save(buf,format="PNG",optimize=True)
            layer_data={k:v for k,v in layer.items() if k!="image"}
            layer_data["image_data_uri"]="data:image/png;base64,"+base64.b64encode(buf.getvalue()).decode("ascii")
            return {"ok":True,"terrain":layer_data,"message":"Prediksi terrain selesai. Hasil bersifat indikatif, bukan jaminan penerimaan sinyal."}
        if action=="load_measurements":
            raw=db.reference("signal_measurements").get() or {}; records=[]
            for p,areas in raw.items():
                for a,muxes in (areas or {}).items():
                    for m,items in (muxes or {}).items():
                        for mid,item in (items or {}).items():
                            if isinstance(item,dict): records.append({"id":mid,"provinsi":p,"wilayah":a,"mux":m,**item})
            records.sort(key=lambda x:x.get("timestamp",""),reverse=True)
            return {"ok":True,"measurements":records[:500]}
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
        if action=="load_details":
            prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
            raw=db.reference(f"signal_measurements/{prov}/{area}/{mux}").get() or {}
            measurements=[{"id":k,"provinsi":prov,"wilayah":area,"mux":mux,**v} for k,v in raw.items() if isinstance(v,dict)]
            measurements.sort(key=lambda x:x.get("timestamp",""),reverse=True)
            return {"ok":True,"comments":_comments(prov,area,mux),"detail":(db.reference(f"siaran/{prov}/{area}/{mux}").get() or {}),"measurements":measurements[:500]}
        if action=="load_community":
            users=_all_users_public(); users.sort(key=lambda x:int(x.get("points",0) or 0),reverse=True)
            return {"ok":True,"users":users,"leaderboard":users,"profile":_profile(session['auth']['username']) if session.get('auth') else None}
        if action=="load_user_profile":
            username=str(event.get("username","")); users=db.reference("users").get() or {}
            if username not in users: raise ValueError("Profil pengguna tidak ditemukan.")
            return {"ok":True,"user_profile":_public_user(username,users[username])}
        if action=="load_admin":
            _require_admin(session); logs=db.reference("audit_logs").get() or {}; logs=[{"id":k,**v} for k,v in logs.items() if isinstance(v,dict)]; logs.sort(key=lambda x:x.get("timestamp",""),reverse=True)
            return {"ok":True,"reports":_all_reports(),"logs":logs}
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
        return {"ok":False,"message":"Aksi tidak dikenal."}
    except Exception as exc:
        return {"ok":False,"message":str(exc) if isinstance(exc,(ValueError,PermissionError,RuntimeError)) else "Terjadi kesalahan layanan. Periksa konfigurasi dan log server."}
