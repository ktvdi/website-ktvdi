from __future__ import annotations
import base64
import math
import random
import re
import json
import hashlib
import time
from collections import OrderedDict
from threading import RLock
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
from services.map_serializers import (has_map_private_access, serialize_map_measurement, serialize_map_detail, serialize_map_response)

REPORT_STATUSES = ["Menunggu", "Sedang ditinjau", "Selesai", "Ditolak"]


# Prediksi dihitung ulang pada setiap permintaan; tidak menyimpan hasil terrain
# dalam cache proses, sesuai pilihan tanpa cache.

def _cached_terrain_layer(tx_for_calc, lat, lon, fallback_erp, fallback_tx, sim_rx, sim_threshold, sim_loss):
    from terrain import _terrain_dem_coverage
    from PIL import Image
    import base64
    from io import BytesIO

    layers = _terrain_dem_coverage(
        [{**tx_for_calc, "latitude": lat, "longitude": lon}], lat, lon,
        erp_watt=fallback_erp, tx_height_m=fallback_tx, rx_height_m=sim_rx,
        rx_threshold_dbm=sim_threshold, extra_loss_db=sim_loss, max_transmitters=1,
    )
    if not layers:
        raise ValueError("Tidak ada hasil prediksi terrain.")
    layer = layers[0]
    image_array = layer.get("image")
    bounds = layer.get("bounds")
    if image_array is None or getattr(image_array, "ndim", 0) != 3 or image_array.shape[2] != 4:
        raise RuntimeError("Raster coverage tidak menghasilkan gambar RGBA yang valid.")
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 2 or any(
        not isinstance(point, (list, tuple)) or len(point) != 2
        for point in bounds
    ):
        raise RuntimeError("Batas geografis coverage tidak valid.")
    if not (bounds[0][0] < bounds[1][0] and bounds[0][1] < bounds[1][1]):
        raise RuntimeError("Batas geografis coverage tidak memiliki rentang yang valid.")
    # Tetap kirim PNG untuk piksel yang diprediksi lemah; hanya area tanpa
    # data DEM yang transparan. Kode lama menampilkan RGBA melalui Folium.
    if not bool((image_array[..., 3] > 0).any()):
        raise RuntimeError(
            "Raster DEM tidak menghasilkan piksel visual. Periksa data elevasi "
            "dan koordinat pemancar; tidak membuat coverage pengganti."
        )
    image = Image.fromarray(image_array.astype("uint8", copy=False), mode="RGBA")
    buf = BytesIO()
    image.save(buf, format="PNG", optimize=True)
    layer_data = {k: v for k, v in layer.items() if k != "image"}
    layer_data["coverage_engine"] = "legacy-dem-mapzen-knife-edge-no-cache-v1"
    layer_data["image_data_uri"] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    return layer_data


def handle_measurement_handler(action: str, event: dict[str, Any], session: dict[str, Any], secrets=None):
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
                row=dict(rows[0])
                try: lat=float(row.get("latitude")); lon=float(row.get("longitude"))
                except (TypeError,ValueError): raise ValueError("Pemancar belum memiliki koordinat valid.")
                # Overlay terrain memiliki bounds geografis. Untuk pengunjung anonim,
                # hitung dari koordinat publik yang dibulatkan agar bounds raster tidak
                # membocorkan koordinat presisi yang sengaja disembunyikan di peta.
                if not has_map_private_access(session):
                    lat=round(lat, 2); lon=round(lon, 2)
                    row["latitude"], row["longitude"] = lat, lon
                from terrain import _uhf_frequency_mhz
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
                layer_data = _cached_terrain_layer(
                    tx_for_calc, lat, lon, fallback_erp, fallback_tx,
                    sim_rx, sim_threshold, sim_loss,
                )
                valid_pixels = int(layer_data.get("valid_pixel_count", 0) or 0)
                predicted_pixels = int(layer_data.get("predicted_pixel_count", 0) or 0)
                min_dbm = layer_data.get("min_dbm")
                max_dbm = layer_data.get("max_dbm")
                threshold_dbm = layer_data.get("rx_threshold_dbm", sim_threshold)
                if valid_pixels > 0:
                    result_message = (
                        f"Overlay prediksi berdiameter 200 km diproses. "
                        f"{predicted_pixels:,} piksel dihitung; {valid_pixels:,} piksel "
                        f"memenuhi ambang {float(threshold_dbm):g} dBm. "
                        "Hasil bersifat indikatif, bukan jaminan penerimaan siaran."
                    )
                elif predicted_pixels > 0:
                    signal_range = ""
                    if min_dbm is not None and max_dbm is not None:
                        signal_range = (
                            f" Rentang estimasi daya terima {float(min_dbm):.1f} "
                            f"hingga {float(max_dbm):.1f} dBm."
                        )
                    result_message = (
                        f"Overlay sinyal lemah tetap diproses: {predicted_pixels:,} piksel "
                        f"memiliki estimasi sinyal, tetapi belum ada yang memenuhi "
                        f"ambang penerimaan {float(threshold_dbm):g} dBm. "
                        "Piksel di bawah ambang seharusnya tampak merah pada peta."
                        f"{signal_range} Hasil bersifat indikatif."
                    )
                else:
                    result_message = (
                        "Perhitungan DEM selesai, tetapi tidak menghasilkan piksel "
                        "prediksi yang dapat digambar di dalam area 200 km. "
                        "Ini bukan bukti bahwa wilayah pasti tidak terjangkau; "
                        "perlu pemeriksaan data DEM dan koordinat pemancar."
                    )
                layer_data["coverage_diagnostics"] = {
                    "predicted_pixel_count": predicted_pixels,
                    "accepted_pixel_count": valid_pixels,
                    "rx_threshold_dbm": threshold_dbm,
                    "min_dbm": min_dbm,
                    "max_dbm": max_dbm,
                }
                return {"ok":True,"action":action,"terrain":layer_data,"message":result_message}
    if action=="load_measurements":
                authenticated=has_map_private_access(session)
                raw=db.reference("signal_measurements").get() or {}; records=[]
                for p,areas in raw.items():
                    for a,muxes in (areas or {}).items():
                        for m,items in (muxes or {}).items():
                            for mid,item in (items or {}).items():
                                if not isinstance(item,dict):
                                    continue
                                record={"id":mid,"provinsi":p,"wilayah":a,"mux":m,**item}
                                records.append(serialize_map_measurement(record,authenticated))
                records.sort(key=lambda x:x.get("timestamp",""),reverse=True)
                limit=500 if authenticated else 100
                return serialize_map_response(action,{"measurements":records[:limit]},authenticated)
    if action=="load_details":
                prov=_safe_key(event.get("provinsi"),"Provinsi"); area=_safe_key(event.get("wilayah"),"Wilayah"); mux=_safe_key(event.get("mux"),"MUX")
                authenticated=has_map_private_access(session)
                raw=db.reference(f"signal_measurements/{prov}/{area}/{mux}").get() or {}
                measurements=[]
                for key,value in raw.items():
                    if isinstance(value,dict):
                        record={"id":key,"provinsi":prov,"wilayah":area,"mux":mux,**value}
                        measurements.append(serialize_map_measurement(record,authenticated))
                measurements.sort(key=lambda x:x.get("timestamp",""),reverse=True)
                comments=_comments(prov,area,mux)
                detail=serialize_map_detail(db.reference(f"siaran/{prov}/{area}/{mux}").get() or {},authenticated)
                payload={"comments":comments,"detail":detail,"measurements":measurements[:500]}
                return serialize_map_response(action,payload,authenticated)
    return None
