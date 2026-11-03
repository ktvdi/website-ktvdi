"""Layanan backend KTVDI. Seluruh akses Firebase dan rahasia hanya di sisi Python."""
from __future__ import annotations
import hashlib
import math, random, re, smtplib
from datetime import datetime
from email.mime.text import MIMEText
from typing import Any
import firebase_admin
from firebase_admin import credentials, db
from pytz import timezone

DB_URL = "https://website-ktvdi-default-rtdb.firebaseio.com/"
WIB = timezone("Asia/Jakarta")
REPORT_STATUSES = ["Menunggu", "Sedang ditinjau", "Selesai", "Ditolak"]


def now_wib(fmt="%Y-%m-%d %H:%M:%S WIB"):
    return datetime.now(WIB).strftime(fmt)


def initialize_firebase(secrets) -> None:
    if not firebase_admin._apps:
        cred = credentials.Certificate(dict(secrets["FIREBASE"]))
        firebase_admin.initialize_app(cred, {"databaseURL": DB_URL})


def hash_password(password: str) -> str:
    # SHA-256 dipertahankan untuk kompatibilitas akun lama.
    return hashlib.sha256(password.encode()).hexdigest()


def _safe_key(value: str, label: str) -> str:
    value = str(value or "").strip()
    if not value or any(c in value for c in ".#$[]/"):
        raise ValueError(f"{label} tidak valid.")
    return value


def get_all_broadcast_rows() -> list[dict[str, Any]]:
    data = db.reference("siaran").get() or {}
    rows = []
    for prov, areas in data.items():
        for wilayah, muxes in (areas or {}).items():
            for mux, details in (muxes or {}).items():
                details = {"siaran": details} if isinstance(details, list) else (details or {})
                rows.append({"provinsi": str(prov), "wilayah": str(wilayah), "mux": str(mux),
                    "siaran": details.get("siaran", []) or [], "detail": details,
                    "latitude": details.get("latitude"), "longitude": details.get("longitude")})
    return rows


def get_stats() -> dict[str, int]:
    rows = get_all_broadcast_rows()
    return {"provinsi": len({r['provinsi'] for r in rows}),
            "wilayah": len({(r['provinsi'], r['wilayah']) for r in rows}),
            "mux": len(rows),
            "kanal": len({str(c).strip().casefold() for r in rows for c in r['siaran'] if str(c).strip()})}


def search_broadcasts(query: str) -> list[dict[str, Any]]:
    q = query.strip().casefold()
    if not q: return []
    out=[]
    for row in get_all_broadcast_rows():
        hay = " ".join([row['provinsi'],row['wilayah'],row['mux']," ".join(map(str,row['siaran']))]).casefold()
        if q in hay: out.append(row)
    return out


def get_recent_changes(limit=50):
    logs=db.reference("audit_logs").get() or {}
    allowed={"add_broadcast","edit_broadcast","delete_broadcast","restore_broadcast"}
    values=[v for v in logs.values() if isinstance(v,dict) and v.get("action") in allowed]
    values.sort(key=lambda x:x.get("timestamp",""),reverse=True)
    return values[:limit]


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


def login(username: str, password: str) -> dict[str, Any]:
    username=username.strip(); users=db.reference("users").get() or {}; user=users.get(username)
    if not username or not password or not user or user.get("password") != hash_password(password):
        return {"ok":False,"message":"Username atau password salah."}
    return {"ok":True,"username":username,"nama":user.get("nama",username),"points":user.get("points",0),
            "admin":db.reference(f"admins/{username}").get() is True}


def _send_otp(secrets, email, otp, purpose):
    sender=secrets["email"]["sender"]; password=secrets["email"]["app_password"]
    subject="Kode OTP Pendaftaran KTVDI" if purpose=="register" else "Kode OTP Reset Password KTVDI"
    msg=MIMEText(f"Kode OTP KTVDI Anda: {otp}. Jangan bagikan kode ini kepada siapa pun.")
    msg["Subject"]=subject; msg["From"]=sender; msg["To"]=email
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as server:
        server.login(sender,password); server.sendmail(sender,email,msg.as_string())


def _public_user(username, user):
    return {"username":username,"nama":user.get("nama",username),"points":user.get("points",0),
        **{k:user.get(k,"") for k in ("provinsi","wilayah","tv_brand","stb_brand","antenna_brand")}}


def _all_reports():
    data=db.reference("broadcast_reports").get() or {}
    return [{"id":k,**v} for k,v in data.items() if isinstance(v,dict)]


def _all_users_public():
    users=db.reference("users").get() or {}
    return [_public_user(k,v) for k,v in users.items() if isinstance(v,dict)]


def _profile(username):
    data=db.reference(f"users/{username}").get() or {}
    return _public_user(username,data)


def _comments(prov, area, mux):
    data=db.reference(f"siaran/{prov}/{area}/{mux}/comments").get() or {}
    return [{"id":k,**v} for k,v in sorted(data.items(),key=lambda kv:kv[1].get("timestamp",""),reverse=True) if isinstance(v,dict)]


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
            session["pending_register"]={"nama":name,"email":email,"username":user,"password":hash_password(pw),"otp_hash":hash_password(otp),"expires":datetime.now().timestamp()+600}
            return {"ok":True,"message":"OTP pendaftaran dikirim ke email. Berlaku 10 menit."}
        if action=="register_verify":
            pending=session.get("pending_register") or {}
            if not pending or datetime.now().timestamp()>pending.get("expires",0): raise ValueError("Sesi OTP tidak ada atau sudah kedaluwarsa. Ulangi pendaftaran.")
            if hash_password(str(event.get("otp","")))!=pending["otp_hash"]: raise ValueError("Kode OTP salah.")
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
            session["pending_reset"]={"username":found[0],"otp_hash":hash_password(otp),"expires":datetime.now().timestamp()+600}
            return {"ok":True,"message":f"OTP dikirim. Username akun: {found[0]}. Berlaku 10 menit."}
        if action=="forgot_reset":
            pending=session.get("pending_reset") or {}
            if not pending or datetime.now().timestamp()>pending.get("expires",0): raise ValueError("Sesi OTP tidak ada atau sudah kedaluwarsa.")
            if hash_password(str(event.get("otp","")))!=pending["otp_hash"]: raise ValueError("Kode OTP salah.")
            pw=str(event.get("password",""))
            if len(pw)<6: raise ValueError("Password minimal 6 karakter.")
            db.reference(f"users/{pending['username']}").update({"password":hash_password(pw)})
            session.pop("pending_reset",None)
            return {"ok":True,"message":"Password berhasil direset. Silakan login."}
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
            data={"siaran":channels,"last_updated_by_username":username,"last_updated_by_name":udata.get("nama",username),"last_updated_date":now_wib("%d-%m-%Y"),"last_updated_time":now_wib("%H:%M:%S WIB")}
            db.reference(path).set(data); _audit("add_broadcast",prov,area,mux,username,None,data)
            user.update({"points":int(udata.get("points",0))+10}); db.reference("app_metadata/last_leaderboard_update_timestamp").set(stamp[:19])
            return {"ok":True,"message":"Data siaran berhasil ditambahkan. Anda mendapat 10 poin."}
        if action in ("edit_broadcast","delete_broadcast"):
            username=_require_auth(session); prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
            ref=db.reference(f"siaran/{prov}/{area}/{mux}"); before=ref.get()
            if not before: raise ValueError("Data MUX tidak ditemukan.")
            owner = before.get("last_updated_by_username") if isinstance(before,dict) else None
            admin = db.reference(f"admins/{username}").get() is True
            if action=="edit_broadcast":
                if owner and owner != username and not admin: raise PermissionError("Anda hanya dapat mengedit data yang Anda tambahkan, kecuali admin.")
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
            username=_require_auth(session); prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
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
        if action=="save_coordinates":
            username=_require_auth(session); prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
            try: lat=float(event.get("latitude")); lon=float(event.get("longitude"))
            except (TypeError,ValueError): raise ValueError("Koordinat harus berupa angka.")
            if not (-11<=lat<=6 and 95<=lon<=141): raise ValueError("Koordinat berada di luar rentang wilayah Indonesia.")
            ref=db.reference(f"siaran/{prov}/{area}/{mux}"); before=ref.get() or {}
            if not before: raise ValueError("Data MUX tidak ditemukan.")
            has=before.get("latitude") is not None and before.get("longitude") is not None
            admin=db.reference(f"admins/{username}").get() is True
            if has and not admin: raise PermissionError("Koordinat yang sudah ada hanya dapat diubah admin.")
            after={**before,"latitude":lat,"longitude":lon}; ref.set(after)
            _audit("update_coordinates" if has else "add_coordinates",prov,area,mux,username,before,after)
            return {"ok":True,"message":"Koordinat pemancar berhasil disimpan."}
        if action=="delete_coordinates":
            username=_require_admin(session); prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
            ref=db.reference(f"siaran/{prov}/{area}/{mux}"); before=ref.get() or {}
            after={k:v for k,v in before.items() if k not in ("latitude","longitude")}; ref.set(after)
            _audit("delete_coordinates",prov,area,mux,username,before,after)
            return {"ok":True,"message":"Titik koordinat dihapus; data siaran tetap tersimpan."}
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
