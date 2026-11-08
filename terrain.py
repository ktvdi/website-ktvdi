"""Model indikatif propagasi dan difraksi terrain, dipindahkan dari aplikasi KTVDI lama."""
import math
import re
import os
import shutil
import tempfile
import threading
import time

# elevation.clip membangun cache MAPZEN bersama; serialisasi agar sesi
# Streamlit paralel tidak saling merusak file TIFF/VRT sementara.
_DEM_CACHE_LOCK = threading.RLock()

def _uhf_frequency_mhz(mux_name):
    """Perkiraan frekuensi tengah kanal UHF DVB-T2 (kanal 21 mulai 474 MHz, lebar 8 MHz)."""
    match = re.search(r"\bUHF\s*(\d{1,3})\b", str(mux_name), re.IGNORECASE)
    if not match:
        return None
    channel = int(match.group(1))
    if not 21 <= channel <= 48:
        return None
    return 474.0 + (channel - 21) * 8.0


def _haversine_km(lat1, lon1, lat2, lon2):
    """Jarak permukaan bumi dalam kilometer."""
    from math import radians, sin, cos, asin, sqrt
    radius_km = 6371.0088
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radius_km * asin(sqrt(min(1, a)))


def _estimate_max_range_km(freq_mhz, erp_watt, tx_height_m, rx_height_m,
                           rx_threshold_dbm=-90.0, extra_loss_db=4.0):
    """Estimasi jarak maksimum indikatif dari link budget dan radio horizon.

    ERP dikonversi ke EIRP (ERP + 2.15 dB). Jarak dibatasi oleh
    free-space link budget dan horizon radio efektif k=4/3. Ini batas
    perencanaan, bukan jaminan penerimaan DVB-T2.
    """
    import math
    eirp_dbm = 10.0 * math.log10(max(float(erp_watt), 0.001) * 1000.0) + 2.15
    allowable_fspl = eirp_dbm - float(rx_threshold_dbm) - float(extra_loss_db)
    fs_range_km = 10.0 ** ((allowable_fspl - 32.44 - 20.0 * math.log10(float(freq_mhz))) / 20.0)
    radio_horizon_km = 4.12 * (math.sqrt(max(float(tx_height_m), 0.1)) +
                               math.sqrt(max(float(rx_height_m), 0.1)))
    return max(1.0, min(fs_range_km, radio_horizon_km)), fs_range_km, radio_horizon_km


def _resolve_transmitter_technical_data(tx, fallback_erp_watt=1000.0,
                                        fallback_tx_height_m=30.0,
                                        fallback_antenna_gain_dbd=10.0,
                                        fallback_feeder_loss_db=2.0):
    """Pilih data teknis per pemancar; nilai asumsi hanya untuk field yang kosong.

    ERP aktual diprioritaskan. Jika hanya power output tersedia, ERP dihitung
    dari power output + gain antena - rugi feeder. Gain/rugi yang belum tercatat
    memakai nilai fallback dan ditandai sebagai asumsi.
    """
    detail = tx.get("detail") or {}

    def positive_number(value):
        try:
            number = float(value)
            return number if number > 0 else None
        except (TypeError, ValueError):
            return None

    def finite_number(value):
        try:
            number = float(value)
            return number if math.isfinite(number) else None
        except (TypeError, ValueError):
            return None

    actual_tx_height = positive_number(detail.get("tx_height_m"))
    actual_tx_power = positive_number(detail.get("tx_power_w"))
    actual_erp = positive_number(detail.get("erp_w"))
    actual_gain = finite_number(detail.get("antenna_gain_dbd"))
    actual_feeder_loss = finite_number(detail.get("feeder_loss_db"))

    used_tx_height = actual_tx_height if actual_tx_height is not None else float(fallback_tx_height_m)
    tx_height_source = "data pemancar" if actual_tx_height is not None else "asumsi"

    assumption_notes = []
    if actual_erp is not None:
        used_erp = actual_erp
        erp_source = "ERP aktual tersimpan"
        used_gain = actual_gain
        used_feeder_loss = actual_feeder_loss
    elif actual_tx_power is not None:
        used_gain = actual_gain if actual_gain is not None else float(fallback_antenna_gain_dbd)
        used_feeder_loss = (actual_feeder_loss if actual_feeder_loss is not None
                            else float(fallback_feeder_loss_db))
        used_erp = actual_tx_power * (10.0 ** ((used_gain - used_feeder_loss) / 10.0))
        if actual_gain is None:
            assumption_notes.append(
                f"gain antena memakai asumsi {used_gain:g} dBd"
            )
        if actual_feeder_loss is None:
            assumption_notes.append(
                f"rugi feeder memakai asumsi {used_feeder_loss:g} dB"
            )
        if assumption_notes:
            erp_source = "ERP estimasi dari Power Output; sebagian parameter diasumsikan"
        else:
            erp_source = "ERP estimasi dari Power Output dan data antena aktual"
    else:
        used_erp = float(fallback_erp_watt)
        used_gain = actual_gain
        used_feeder_loss = actual_feeder_loss
        erp_source = "ERP fallback/asumsi karena Power Output dan ERP aktual tidak tersedia"
        assumption_notes.append(f"ERP fallback {used_erp:g} W digunakan")

    if actual_tx_height is None:
        assumption_notes.append(
            f"tinggi TX memakai asumsi {used_tx_height:g} m"
        )

    return {
        "erp_watt": used_erp,
        "tx_height_m": used_tx_height,
        "tx_power_w": actual_tx_power,
        "antenna_gain_dbd": used_gain,
        "feeder_loss_db": used_feeder_loss,
        "erp_source": erp_source,
        "tx_height_source": tx_height_source,
        "assumption_notes": assumption_notes,
        "prediction_data_status": (
            "Estimasi dengan asumsi teknis" if assumption_notes
            else "Parameter daya dan tinggi TX tersedia; model propagasi tetap berupa estimasi"
        ),
        "technical_reference": detail.get("technical_data_reference", ""),
        "technical_updated_at": detail.get("technical_data_updated_at", ""),
    }


def _terrain_dem_coverage(located, center_lat, center_lon,
                          erp_watt=1000.0, tx_height_m=30.0, rx_height_m=10.0,
                          rx_threshold_dbm=-90.0, extra_loss_db=4.0,
                          fallback_antenna_gain_dbd=10.0, fallback_feeder_loss_db=2.0,
                          max_transmitters=1):
    """Prediksi terrain sampai jarak maksimum hasil asumsi link budget.

    DEM MAPZEN digunakan untuk profil elevasi dan difraksi knife-edge.
    Resolusi raster adaptif agar area yang lebih luas tetap dapat diproses
    pada Streamlit Community Cloud. Model ini indikatif, bukan ITU-R P.1812
    atau Longley-Rice.
    """
    import os
    import tempfile
    import numpy as np
    import rasterio
    import elevation
    from rasterio.warp import calculate_default_transform, reproject, Resampling
    from pyproj import CRS, Transformer
    from scipy.ndimage import map_coordinates

    tx_list = [t for t in located if _uhf_frequency_mhz(t.get("mux", ""))]
    if max_transmitters is not None:
        tx_list = tx_list[:int(max_transmitters)]
    if not tx_list:
        raise ValueError("Tidak ada pemancar dengan kanal UHF 21–48 dan koordinat valid.")

    outputs = []
    for tx in tx_list:
        freq = _uhf_frequency_mhz(tx.get("mux", ""))
        technical = _resolve_transmitter_technical_data(
            tx, fallback_erp_watt=erp_watt, fallback_tx_height_m=tx_height_m,
            fallback_antenna_gain_dbd=fallback_antenna_gain_dbd,
            fallback_feeder_loss_db=fallback_feeder_loss_db
        )
        erp_used = technical["erp_watt"]
        tx_height_used = technical["tx_height_m"]
        max_range_km, fs_range_km, horizon_km = _estimate_max_range_km(
            freq, erp_used, tx_height_used, rx_height_m, rx_threshold_dbm, extra_loss_db
        )
        tx_lat, tx_lon = float(tx["latitude"]), float(tx["longitude"])
        utm_zone = int((tx_lon + 180) // 6) + 1
        utm_epsg = (32700 if tx_lat < 0 else 32600) + utm_zone
        utm_crs = CRS.from_epsg(utm_epsg)
        to_utm = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
        from_utm = Transformer.from_crs(utm_crs, "EPSG:4326", always_xy=True)
        tx_x, tx_y = to_utm.transform(tx_lon, tx_lat)
        # Area terrain dibuat konsisten untuk setiap pemancar: diameter 200 km
        # (radius 100 km). Saat ini overlay hanya dihitung untuk pemancar terpilih.
        # Area di luar ambang RX tetap transparan pada overlay.
        terrain_radius_km = 100.0
        radius_m = terrain_radius_km * 1000.0

        # Batasi jumlah piksel, bukan jarak geografis. Untuk diameter 200 km,
        # resolusi raster menyesuaikan agar tetap layak di Streamlit Community Cloud.
        target_max_side = 700
        cell = max(30.0, (2.0 * radius_m) / target_max_side)
        n = int(np.ceil((2.0 * radius_m) / cell))
        xmin, ymax = tx_x - radius_m, tx_y + radius_m
        xs = xmin + (np.arange(n) + 0.5) * cell
        ys = ymax - (np.arange(n) + 0.5) * cell
        xx, yy = np.meshgrid(xs, ys)
        corners = [from_utm.transform(xmin, tx_y-radius_m),
                   from_utm.transform(xmin, tx_y+radius_m),
                   from_utm.transform(tx_x+radius_m, tx_y-radius_m),
                   from_utm.transform(tx_x+radius_m, ymax)]
        west = min(v[0] for v in corners) - 0.01
        east = max(v[0] for v in corners) + 0.01
        south = min(v[1] for v in corners) - 0.01
        north = max(v[1] for v in corners) + 0.01

        dem_product = "MAPZEN"
        # Cache v3 sengaja dipisahkan dari cache lama yang pada log produksi
        # berisi tile TIFF rusak dan VRT yang gagal dibuat.
        dem_cache_dir = os.path.join(tempfile.gettempdir(), "ktvdi_elevation_cache_v3")
        os.makedirs(dem_cache_dir, exist_ok=True)
        cache_key = (f"ktvdi_{dem_product.lower()}_terrain_d200km_{round(tx_lat,3)}_"
                     f"{round(tx_lon,3)}_{int(round(cell))}m_cachev3.tif")
        dem_path = os.path.join(tempfile.gettempdir(), cache_key)

        def _clip_and_validate_dem():
            elevation.clip(
                bounds=(west, south, east, north),
                output=dem_path,
                product=dem_product,
                cache_dir=dem_cache_dir,
            )
            # Validasi seluruh blok TIFF, bukan hanya sampel kecil. TIFF yang
            # rusak di bagian lain bisa lolos sampel lalu gagal saat reproject.
            valid_pixels = 0
            with rasterio.open(dem_path) as check_src:
                if (check_src.width <= 0 or check_src.height <= 0 or
                        check_src.count < 1 or check_src.crs is None):
                    raise ValueError("Metadata GeoTIFF DEM tidak valid.")
                for _, window in check_src.block_windows(1):
                    block = check_src.read(1, window=window, masked=True)
                    valid_pixels += int(block.count())
                if valid_pixels == 0:
                    raise ValueError("GeoTIFF DEM tidak memiliki piksel elevasi valid.")

        def _purge_dem_cache():
            # Hapus output clip dan seluruh cache produk, termasuk cache tile,
            # spool unduhan, serta MAPZEN.vrt yang mungkin setengah terbentuk.
            try:
                if os.path.exists(dem_path):
                    os.remove(dem_path)
            except OSError:
                pass
            shutil.rmtree(os.path.join(dem_cache_dir, dem_product), ignore_errors=True)
            os.makedirs(dem_cache_dir, exist_ok=True)

        # elevation.clip tidak aman dijalankan bersamaan pada cache yang sama.
        # Kunci juga mencakup pemulihan sehingga sesi lain tidak membaca cache
        # ketika tile/VRT sedang dihapus dan dibangun ulang.
        with _DEM_CACHE_LOCK:
            last_dem_error = None
            for attempt in range(3):
                try:
                    if not os.path.exists(dem_path) or os.path.getsize(dem_path) < 1000:
                        _clip_and_validate_dem()
                    else:
                        # Cache hasil clip yang sudah ada tetap divalidasi penuh.
                        with rasterio.open(dem_path) as check_src:
                            if (check_src.width <= 0 or check_src.height <= 0 or
                                    check_src.count < 1 or check_src.crs is None):
                                raise ValueError("Metadata GeoTIFF DEM tidak valid.")
                            valid_pixels = 0
                            for _, window in check_src.block_windows(1):
                                block = check_src.read(1, window=window, masked=True)
                                valid_pixels += int(block.count())
                            if valid_pixels == 0:
                                raise ValueError("GeoTIFF DEM tidak memiliki piksel elevasi valid.")
                    last_dem_error = None
                    break
                except Exception as dem_error:
                    last_dem_error = dem_error
                    _purge_dem_cache()
                    if attempt < 2:
                        # Beri waktu singkat untuk unduhan ulang setelah kegagalan jaringan.
                        time.sleep(1.5 * (attempt + 1))
            if last_dem_error is not None:
                raise RuntimeError(
                    "Data DEM MAPZEN gagal dibaca setelah 3 percobaan. "
                    "Cache tile/VRT sudah dibersihkan dan dicoba ulang. "
                    f"Detail: {last_dem_error}"
                ) from last_dem_error

        with rasterio.open(dem_path) as src:
            dst_transform, width, height = calculate_default_transform(
                src.crs, utm_crs, src.width, src.height, *src.bounds,
                resolution=cell
            )
            dem = np.full((height, width), np.nan, dtype="float32")
            reproject(source=rasterio.band(src, 1), destination=dem,
                      src_transform=src.transform, src_crs=src.crs,
                      src_nodata=src.nodata, dst_transform=dst_transform,
                      dst_crs=utm_crs, resampling=Resampling.bilinear,
                      dst_nodata=np.nan)

        inv = ~dst_transform
        col, row = inv * (xx, yy)
        dem_grid = map_coordinates(dem, [row, col], order=1, mode="nearest")
        valid = np.isfinite(dem_grid) & (dem_grid > -500)
        radial_km = np.sqrt((xx-tx_x)**2 + (yy-tx_y)**2) / 1000.0
        mask = valid & (radial_km <= terrain_radius_km)
        if not np.any(mask):
            raise ValueError("DEM tidak mencakup area prediksi atau seluruh piksel DEM kosong.")

        tx_row, tx_col = inv * (tx_x, tx_y)
        tx_ground = float(map_coordinates(dem, [[tx_row], [tx_col]],
                                          order=1, mode="nearest")[0])
        dx, dy = xx - tx_x, yy - tx_y
        distance = np.maximum(np.sqrt(dx*dx + dy*dy), 50.0)
        tx_abs = tx_ground + float(tx_height_used)
        rx_abs = dem_grid + float(rx_height_m)
        max_v = np.full(dem_grid.shape, -10.0, dtype="float32")
        wavelength = 299.792458 / float(freq)
        sample_fracs = np.linspace(0.04, 0.96, 24, dtype="float32")
        for frac in sample_fracs:
            sx, sy = tx_x + dx*frac, tx_y + dy*frac
            scol, srow = inv * (sx, sy)
            terrain = map_coordinates(dem, [srow.ravel(), scol.ravel()],
                                      order=1, mode="nearest").reshape(dem_grid.shape)
            d1 = np.maximum(distance * frac, 1.0)
            d2 = np.maximum(distance * (1.0-frac), 1.0)
            earth_bulge = d1*d2 / (2.0*(4.0/3.0)*6371000.0)
            los_height = tx_abs + (rx_abs-tx_abs)*frac
            obstruction = terrain + earth_bulge - los_height
            v = obstruction * np.sqrt(2.0*(d1+d2)/(wavelength*d1*d2))
            max_v = np.maximum(max_v, v.astype("float32"))

        v_formula = np.maximum(max_v, -0.78)
        knife_edge_loss = 6.9 + 20.0*np.log10(
            np.sqrt((v_formula-0.1)**2 + 1.0) + v_formula - 0.1
        )
        diffraction = np.where(max_v <= -0.78, 0.0, knife_edge_loss)
        eirp_dbm = 10.0*np.log10(max(float(erp_used), 0.001)*1000.0) + 2.15
        path_loss = 32.44 + 20.0*np.log10(float(freq)) + 20.0*np.log10(distance/1000.0)
        rx_dbm = eirp_dbm - path_loss - diffraction - float(extra_loss_db)
        # Pertahankan estimasi daya terima untuk SEMUA piksel DEM valid di
        # dalam radius 100 km. Jangan menghapus piksel di bawah ambang RX:
        # piksel tersebut tetap perlu divisualisasikan sebagai sinyal lemah
        # (merah), bukan dibuat transparan sehingga peta tampak kosong.
        rx_dbm = np.where(mask, rx_dbm, np.nan)

        # Klasifikasi warna berdasarkan margin daya terima terhadap ambang RX.
        # Merah juga mencakup piksel di bawah ambang (belum memenuhi penerimaan).
        # Kuning/hijau/biru menunjukkan margin positif yang makin besar.
        margin_db = rx_dbm - float(rx_threshold_dbm)
        predicted_pixels = np.isfinite(rx_dbm)
        accepted_pixels = predicted_pixels & (rx_dbm >= float(rx_threshold_dbm))
        rgba = np.zeros((*rx_dbm.shape, 4), dtype=np.uint8)
        color_bins = [
            (margin_db < 6.0, (235, 35, 35)),       # Lemah
            ((margin_db >= 6.0) & (margin_db < 15.0), (255, 220, 0)),  # Sedang
            ((margin_db >= 15.0) & (margin_db < 25.0), (20, 180, 65)), # Kuat
            (margin_db >= 25.0, (25, 105, 235)),    # Sangat kuat
        ]
        for condition, rgb in color_bins:
            selected = predicted_pixels & condition
            rgba[selected, 0] = rgb[0]
            rgba[selected, 1] = rgb[1]
            rgba[selected, 2] = rgb[2]
        rgba[..., 3] = np.where(predicted_pixels, 220, 0).astype("uint8")
        west_ll, south_ll = from_utm.transform(xmin, tx_y-radius_m)
        east_ll, north_ll = from_utm.transform(tx_x+radius_m, ymax)
        outputs.append({
            "name": f"{tx.get('mux','MUX')} — {tx.get('wilayah','')}",
            "image": rgba, "bounds": [[south_ll, west_ll], [north_ll, east_ll]],
            "min_dbm": float(np.nanpercentile(rx_dbm, 5)) if np.any(predicted_pixels) else None,
            "max_dbm": float(np.nanpercentile(rx_dbm, 95)) if np.any(predicted_pixels) else None,
            "frequency": freq, "max_range_km": max_range_km,
            "terrain_radius_km": terrain_radius_km,
            "terrain_diameter_km": 2.0 * terrain_radius_km,
            "center_lat": float(tx_lat), "center_lon": float(tx_lon),
            # valid_pixel_count tetap berarti piksel yang memenuhi ambang RX
            # agar pesan status backend tidak mengartikan semua prediksi sebagai penerimaan.
            "valid_pixel_count": int(np.count_nonzero(accepted_pixels)),
            "predicted_pixel_count": int(np.count_nonzero(predicted_pixels)),
            "fs_range_km": fs_range_km, "radio_horizon_km": horizon_km,
            "raster_resolution_m": cell, "rx_threshold_dbm": float(rx_threshold_dbm),
            "erp_used_w": float(erp_used), "tx_height_used_m": float(tx_height_used),
            "tx_power_w": technical.get("tx_power_w"),
            "erp_source": technical.get("erp_source"),
            "tx_height_source": technical.get("tx_height_source"),
            "assumption_notes": technical.get("assumption_notes", []),
            "prediction_data_status": technical.get("prediction_data_status", ""),
            "technical_reference": technical.get("technical_reference", ""),
            "technical_updated_at": technical.get("technical_updated_at", "")
        })
    return outputs

