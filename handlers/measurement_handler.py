from __future__ import annotations
import base64
import math
import random
import re
import json
import hashlib
import time
import zlib
import numpy as np
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



# Cache hasil numerik permanen di Firebase Realtime Database.
# PNG tidak pernah disimpan; gambar dibentuk ulang dari raster float32.
COVERAGE_CACHE_ALGORITHM_VERSION = "ktvdi-coverage-raster-v1"
COVERAGE_CACHE_ROOT = "coverage_results"
COVERAGE_CHUNK_CHARS = 200_000


def _coverage_parameter_hash(row, lat, lon, erp, tx_height, rx_height, threshold, extra_loss):
    payload = {
        "algorithm_version": COVERAGE_CACHE_ALGORITHM_VERSION,
        "dem_product": "MAPZEN",
        "radius_km": 100.0,
        "grid_max_side": 700,
        "transmitter": row,
        "center_lat": float(lat),
        "center_lon": float(lon),
        "erp_w": float(erp),
        "tx_height_m": float(tx_height),
        "rx_height_m": float(rx_height),
        "rx_threshold_dbm": float(threshold),
        "extra_loss_db": float(extra_loss),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, allow_nan=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _coverage_png_data_uri(values, threshold_dbm):
    """Bangun PNG palet terindeks; warna dan alpha coverage tetap persis."""
    values = np.asarray(values, dtype=np.float32)
    predicted = np.isfinite(values) & (values != 0.0)
    margin = values - float(threshold_dbm)

    # Indeks 0 khusus No Data (transparan); indeks 1-4 adalah kelas warna
    # yang sama persis dengan renderer RGBA sebelumnya.
    indexed = np.zeros(values.shape, dtype=np.uint8)
    indexed[predicted & (margin < 6.0)] = 1
    indexed[predicted & (margin >= 6.0) & (margin < 15.0)] = 2
    indexed[predicted & (margin >= 15.0) & (margin < 25.0)] = 3
    indexed[predicted & (margin >= 25.0)] = 4

    palette = [
        0, 0, 0,          # 0: No Data (alpha 0)
        235, 35, 35,      # 1: lemah
        255, 220, 0,      # 2: cukup
        20, 180, 65,      # 3: baik
        25, 105, 235,     # 4: sangat baik
    ]
    palette.extend([0] * (768 - len(palette)))

    image = Image.fromarray(indexed, mode="P")
    image.putpalette(palette)
    # Alpha 220 untuk semua kelas coverage, 0 untuk No Data.
    transparency = bytes([0, 220, 220, 220, 220])

    buf = BytesIO()
    started = time.perf_counter()
    image.save(
        buf,
        format="PNG",
        optimize=False,
        compress_level=6,
        transparency=transparency,
    )
    png_bytes = buf.getvalue()
    data_uri = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    return data_uri, len(png_bytes), time.perf_counter() - started


def _save_coverage_result(cache_key, layer_data, coverage_values):
    values = np.asarray(coverage_values, dtype="<f4", order="C")
    compressed = zlib.compress(values.tobytes(order="C"), level=6)
    encoded = base64.b64encode(compressed).decode("ascii")
    chunks = {
        str(index): encoded[start:start + COVERAGE_CHUNK_CHARS]
        for index, start in enumerate(range(0, len(encoded), COVERAGE_CHUNK_CHARS))
    }
    metadata = dict(layer_data)
    metadata.pop("image_data_uri", None)
    metadata.pop("png_size_bytes", None)
    metadata.pop("png_encode_seconds", None)
    record = {
        "status": "completed",
        "algorithm_version": COVERAGE_CACHE_ALGORITHM_VERSION,
        "raster_encoding": "zlib-base64-float32-le",
        "raster_width": int(values.shape[1]),
        "raster_height": int(values.shape[0]),
        "raster_chunk_count": len(chunks),
        "raster_chunks": chunks,
        "metadata": metadata,
        "created_at": int(time.time()),
        "compressed_bytes": len(compressed),
        "uncompressed_bytes": int(values.nbytes),
    }
    db.reference(f"{COVERAGE_CACHE_ROOT}/{cache_key}").set(record)
    return len(compressed)


def _load_coverage_result(cache_key):
    record = db.reference(f"{COVERAGE_CACHE_ROOT}/{cache_key}").get()
    if not isinstance(record, dict) or record.get("status") != "completed":
        return None
    if record.get("algorithm_version") != COVERAGE_CACHE_ALGORITHM_VERSION:
        return None
    if record.get("raster_encoding") != "zlib-base64-float32-le":
        return None
    width = int(record.get("raster_width", 0))
    height = int(record.get("raster_height", 0))
    count = int(record.get("raster_chunk_count", 0))
    chunks = record.get("raster_chunks")
    metadata = record.get("metadata")
    if (width <= 0 or height <= 0 or width > 2000 or height > 2000 or
            width * height > 4_000_000 or count <= 0 or count > 100 or
            not isinstance(chunks, dict) or not isinstance(metadata, dict)):
        return None
    try:
        encoded = "".join(chunks[str(index)] for index in range(count))
        raw = zlib.decompress(base64.b64decode(encoded, validate=True))
        expected_bytes = width * height * np.dtype("<f4").itemsize
        if len(raw) != expected_bytes:
            return None
        values = np.frombuffer(raw, dtype="<f4").reshape((height, width)).copy()
    except (KeyError, ValueError, TypeError, zlib.error):
        return None
    return metadata, values, record.get("created_at")

def _calculate_terrain_layer(tx_for_calc, lat, lon, fallback_erp, fallback_tx, sim_rx, sim_threshold, sim_loss):
    from terrain import _terrain_dem_coverage
    from PIL import Image
    import base64
    import time
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
    coverage_values = layer.get("coverage_values")
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
    if coverage_values is None or np.asarray(coverage_values).shape != image_array.shape[:2]:
        raise RuntimeError("Raster numerik coverage tidak tersedia atau dimensinya tidak sesuai.")
    threshold = float(layer.get("rx_threshold_dbm", -90.0))
    image_data_uri, png_size_bytes, png_encode_seconds = _coverage_png_data_uri(coverage_values, threshold)
    layer_data = {k: v for k, v in layer.items() if k not in ("image", "coverage_values")}
    layer_data["coverage_engine"] = "optimized-dem-mapzen-knife-edge-firebase-raster"
    layer_data["png_size_bytes"] = png_size_bytes
    layer_data["png_encode_seconds"] = round(png_encode_seconds, 3)
    layer_data["image_data_uri"] = image_data_uri

    return layer_data, np.asarray(coverage_values, dtype="<f4")


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
                cache_key = _coverage_parameter_hash(
                    tx_for_calc, lat, lon, fallback_erp, fallback_tx,
                    sim_rx, sim_threshold, sim_loss,
                )
                cache_lookup_started = time.perf_counter()
                cached = None
                try:
                    cached = _load_coverage_result(cache_key)
                except Exception:
                    # Firebase cache tidak boleh membuat fitur prediksi gagal.
                    cached = None
                cache_lookup_seconds = time.perf_counter() - cache_lookup_started
                cache_hit = cached is not None
                if cache_hit:
                    layer_data, coverage_values, cache_created_at = cached
                    png_started = time.perf_counter()
                    image_data_uri, png_size_bytes, png_encode_seconds = _coverage_png_data_uri(
                        coverage_values, float(layer_data.get("rx_threshold_dbm", sim_threshold))
                    )
                    layer_data = dict(layer_data)
                    layer_data["image_data_uri"] = image_data_uri
                    layer_data["png_size_bytes"] = png_size_bytes
                    layer_data["png_encode_seconds"] = round(png_encode_seconds, 3)
                    layer_data["cache_hit"] = True
                    layer_data["cache_lookup_seconds"] = round(cache_lookup_seconds, 3)
                    layer_data["cache_created_at"] = cache_created_at
                    layer_data["dem_download_seconds"] = 0.0
                    layer_data["dem_warp_seconds"] = 0.0
                    layer_data["propagation_seconds"] = 0.0
                else:
                    layer_data, coverage_values = _calculate_terrain_layer(
                        tx_for_calc, lat, lon, fallback_erp, fallback_tx,
                        sim_rx, sim_threshold, sim_loss,
                    )
                    layer_data["cache_hit"] = False
                    layer_data["cache_lookup_seconds"] = round(cache_lookup_seconds, 3)
                    cache_write_started = time.perf_counter()
                    try:
                        compressed_bytes = _save_coverage_result(cache_key, layer_data, coverage_values)
                        layer_data["cache_saved"] = True
                        layer_data["cache_compressed_bytes"] = compressed_bytes
                    except Exception as cache_error:
                        # Tetap tampilkan hasil walaupun Firebase gagal menyimpan cache.
                        layer_data["cache_saved"] = False
                        layer_data["cache_write_error"] = str(cache_error)[:240]
                    layer_data["cache_write_seconds"] = round(time.perf_counter() - cache_write_started, 3)
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
                    "cache_hit": cache_hit,
                    "cache_key": cache_key,
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
