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


def handle_broadcast_handler(action: str, event: dict[str, Any], session: dict[str, Any], secrets=None):
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
    return None
