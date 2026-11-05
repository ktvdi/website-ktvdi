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


def handle_coordinate_handler(action: str, event: dict[str, Any], session: dict[str, Any], secrets=None):
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
    return None
