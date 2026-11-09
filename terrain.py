"""Model indikatif propagasi dan difraksi terrain, dipindahkan dari aplikasi KTVDI lama."""
import math
import re
import os
import tempfile

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
    import time
    # Tidak menggunakan cache persisten: seluruh data DEM hanya hidup selama
    # permintaan ini dan dihapus otomatis setelah raster berada di memori.
    import numpy as np
    import rasterio
    import elevation
    from rasterio.warp import reproject, Resampling
    from rasterio.transform import from_origin
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
        # Tidak menggunakan cache DEM persisten. Semua tile, VRT, dan GeoTIFF
        # hanya boleh berada di direktori sementara untuk permintaan ini.
        last_dem_error = None
        dem_grid = None
        dst_transform = from_origin(xmin, ymax, cell, cell)

        # Warp DEM langsung ke grid overlay final (n x n). Jalur lama membuat
        # raster proyeksi perantara, lalu menginterpolasinya lagi ke grid akhir.
        # Direct warp menghindari satu raster besar dan satu pass interpolasi.
        dem_download_seconds = 0.0
        dem_warp_seconds = 0.0
        for attempt in range(3):
            try:
                with tempfile.TemporaryDirectory(prefix="ktvdi_dem_") as dem_work_dir:
                    ephemeral_tile_dir = os.path.join(dem_work_dir, "tiles")
                    os.makedirs(ephemeral_tile_dir, exist_ok=True)
                    dem_path = os.path.join(dem_work_dir, "terrain.tif")

                    stage_started = time.perf_counter()
                    elevation.clip(
                        bounds=(west, south, east, north),
                        output=dem_path,
                        product=dem_product,
                        cache_dir=ephemeral_tile_dir,
                    )
                    dem_download_seconds += time.perf_counter() - stage_started

                    with rasterio.open(dem_path) as src:
                        if (src.width <= 0 or src.height <= 0 or
                                src.count < 1 or src.crs is None):
                            raise ValueError("Metadata GeoTIFF DEM tidak valid.")
                        dem_grid = np.full((n, n), np.nan, dtype=np.float32)
                        stage_started = time.perf_counter()
                        reproject(
                            source=rasterio.band(src, 1),
                            destination=dem_grid,
                            src_transform=src.transform,
                            src_crs=src.crs,
                            src_nodata=src.nodata,
                            dst_transform=dst_transform,
                            dst_crs=utm_crs,
                            dst_nodata=np.nan,
                            resampling=Resampling.bilinear,
                            num_threads=2,
                            init_dest_nodata=True,
                        )
                        dem_warp_seconds += time.perf_counter() - stage_started

                if not np.isfinite(dem_grid).any():
                    raise ValueError("GeoTIFF DEM tidak memiliki piksel elevasi valid pada area target.")
                last_dem_error = None
                break
            except Exception as dem_error:
                dem_grid = None
                last_dem_error = dem_error

        if last_dem_error is not None or dem_grid is None:
            raise RuntimeError(
                "Data DEM MAPZEN gagal diunduh atau diproyeksikan setelah 3 percobaan. "
                "Tidak ada cache persisten; file sementara setiap percobaan telah dibuang. "
                f"Detail: {last_dem_error}"
            ) from last_dem_error

        # Grid DEM sudah sama persis dengan grid overlay sehingga tidak perlu
        # map_coordinates kedua untuk membentuk dem_grid.
        valid = np.isfinite(dem_grid) & (dem_grid > -500)
        radial_km = np.sqrt((xx-tx_x)**2 + (yy-tx_y)**2) / 1000.0
        mask = valid & (radial_km <= terrain_radius_km)
        if not np.any(mask):
            raise ValueError("DEM tidak mencakup area prediksi atau seluruh piksel DEM kosong.")

        propagation_started = time.perf_counter()
        inv = ~dst_transform
        tx_col, tx_row = inv * (tx_x, tx_y)
        # scipy mengindeks pusat piksel pada bilangan bulat; affine raster
        # mengembalikan koordinat sudut piksel, sehingga kurangi 0.5.
        tx_ground = float(map_coordinates(
            dem_grid, [[tx_row - 0.5], [tx_col - 0.5]],
            order=1, mode="nearest", prefilter=False
        )[0])
        dx, dy = xx - tx_x, yy - tx_y
        distance = np.maximum(np.sqrt(dx*dx + dy*dy), 50.0)
        tx_abs = tx_ground + float(tx_height_used)
        rx_abs = dem_grid + float(rx_height_m)
        max_v = np.full(dem_grid.shape, -10.0, dtype="float32")
        wavelength = 299.792458 / float(freq)
        sample_fracs = np.linspace(0.04, 0.96, 24, dtype=np.float32)

        # Ambil 24 profil difraksi dalam satu operasi interpolasi per blok baris.
        # Ini mempertahankan jumlah sampel model, tetapi mengurangi pemanggilan
        # scipy dan membatasi penggunaan RAM dibanding membuat tensor 700x700 penuh.
        chunk_rows = 64
        frac_3d = sample_fracs[:, None, None]
        for row_start in range(0, n, chunk_rows):
            row_end = min(row_start + chunk_rows, n)
            dx_chunk = dx[row_start:row_end]
            dy_chunk = dy[row_start:row_end]
            distance_chunk = distance[row_start:row_end]
            rx_abs_chunk = rx_abs[row_start:row_end]

            sample_x = tx_x + frac_3d * dx_chunk[None, :, :]
            sample_y = tx_y + frac_3d * dy_chunk[None, :, :]
            coordinates = np.empty((2, len(sample_fracs), row_end-row_start, n), dtype=np.float32)
            coordinates[0] = (ymax - sample_y) / cell - 0.5
            coordinates[1] = (sample_x - xmin) / cell - 0.5
            terrain_samples = map_coordinates(
                dem_grid, coordinates, order=1, mode="nearest", prefilter=False
            )

            d1 = np.maximum(distance_chunk[None, :, :] * frac_3d, 1.0)
            d2 = np.maximum(distance_chunk[None, :, :] * (1.0-frac_3d), 1.0)
            earth_bulge = d1*d2 / (2.0*(4.0/3.0)*6371000.0)
            los_height = tx_abs + (rx_abs_chunk[None, :, :] - tx_abs) * frac_3d
            obstruction = terrain_samples + earth_bulge - los_height
            v = obstruction * np.sqrt(2.0*(d1+d2)/(wavelength*d1*d2))
            max_v[row_start:row_end] = np.max(v, axis=0).astype(np.float32, copy=False)

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
        # Nilai 0 menandakan tidak ada nilai coverage yang perlu divisualisasikan.
        # Biarkan transparan agar warna dasar peta tetap terlihat.
        predicted_pixels = np.isfinite(rx_dbm) & (rx_dbm != 0.0)
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
        propagation_seconds = time.perf_counter() - propagation_started
        predicted_values = rx_dbm[predicted_pixels]
        if predicted_values.size:
            percentile_values = np.percentile(predicted_values, [5, 95])
            min_dbm, max_dbm = float(percentile_values[0]), float(percentile_values[1])
        else:
            min_dbm = max_dbm = None
        west_ll, south_ll = from_utm.transform(xmin, tx_y-radius_m)
        east_ll, north_ll = from_utm.transform(tx_x+radius_m, ymax)
        outputs.append({
            "coverage_engine": "optimized-dem-mapzen-knife-edge-no-cache",
            "name": f"{tx.get('mux','MUX')} — {tx.get('wilayah','')}",
            "image": rgba,
            # Raster numerik float32 disimpan oleh handler ke Firebase (terkompresi).
            # PNG tetap dibuat saat diminta dan tidak disimpan permanen.
            "coverage_values": rx_dbm.astype("<f4", copy=False),
            "bounds": [[south_ll, west_ll], [north_ll, east_ll]],
            "min_dbm": min_dbm,
            "max_dbm": max_dbm,
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
            "raster_width": int(n), "raster_height": int(n),
            "dem_download_seconds": round(dem_download_seconds, 3),
            "dem_warp_seconds": round(dem_warp_seconds, 3),
            "propagation_seconds": round(propagation_seconds, 3),
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

