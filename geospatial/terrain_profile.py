"""Terrain profile and geometric obstruction checks for a transmitter-receiver path."""
from __future__ import annotations

import math

import numpy as np

try:
    import streamlit as st
    _cache_data = st.cache_data(ttl=86400, max_entries=32, show_spinner=False)
except Exception:
    def _cache_data(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

from .dem_provider import fetch_big_demnas, get_local_dem_path, sample_opentopography

EARTH_RADIUS_M = 6371008.8
EFFECTIVE_EARTH_K = 4.0 / 3.0


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def interpolate_path(tx_lat, tx_lon, rx_lat, rx_lon, sample_spacing_m=30.0):
    distance = haversine_m(tx_lat, tx_lon, rx_lat, rx_lon)
    count = max(3, min(5000, int(math.ceil(distance / sample_spacing_m)) + 1))
    # Linear interpolation is adequate for short/medium paths in this initial profile engine.
    fractions = np.linspace(0.0, 1.0, count)
    lats = tx_lat + (rx_lat - tx_lat) * fractions
    lons = tx_lon + (rx_lon - tx_lon) * fractions
    return distance, fractions, lats, lons


def _bounds_for_path(lats, lons, padding_m=1000.0):
    mid_lat = float(np.mean(lats))
    pad_lat = padding_m / 110574.0
    pad_lon = padding_m / (111320.0 * max(0.15, math.cos(math.radians(mid_lat))))
    return (
        max(95.00001, float(np.min(lons)) - pad_lon),
        max(-10.99999, float(np.min(lats)) - pad_lat),
        min(140.99999, float(np.max(lons)) + pad_lon),
        min(5.99999, float(np.max(lats)) + pad_lat),
    )


def _sample_raster(path, lats, lons):
    import rasterio
    from rasterio.warp import transform
    with rasterio.open(path) as src:
        xs, ys = transform("EPSG:4326", src.crs, lons.tolist(), lats.tolist())
        vals = np.asarray([v[0] for v in src.sample(list(zip(xs, ys)))], dtype=float)
        nodata = src.nodata
        if nodata is not None:
            vals[np.isclose(vals, nodata)] = np.nan
        vals[~np.isfinite(vals)] = np.nan
    return vals


@_cache_data
def analyze_terrain_path(tx_lat, tx_lon, rx_lat, rx_lon, tx_antenna_m=30.0,
                         rx_antenna_m=3.0, frequency_mhz=600.0,
                         sample_spacing_m=30.0, resolution_m=30.0):
    """Return terrain samples, Fresnel clearance and geometric LOS status.

    Antenna heights are AGL. Terrain heights are DEM elevations. A 4/3 effective-earth
    radius is used for a first-order curvature correction. This is not a full ITU-R
    propagation or diffraction-loss implementation.
    """
    for name, value in (("tx_lat", tx_lat), ("tx_lon", tx_lon), ("rx_lat", rx_lat), ("rx_lon", rx_lon),
                        ("tx_antenna_m", tx_antenna_m), ("rx_antenna_m", rx_antenna_m),
                        ("frequency_mhz", frequency_mhz)):
        if not math.isfinite(float(value)):
            raise ValueError(f"{name} harus berupa angka hingga.")
    if not (95 <= tx_lon <= 141 and 95 <= rx_lon <= 141 and -11 <= tx_lat <= 6 and -11 <= rx_lat <= 6):
        raise ValueError("Koordinat lintasan berada di luar cakupan Indonesia.")
    if tx_antenna_m <= 0 or rx_antenna_m <= 0 or frequency_mhz <= 0:
        raise ValueError("Tinggi antena dan frekuensi harus lebih besar dari nol.")

    distance, fractions, lats, lons = interpolate_path(
        float(tx_lat), float(tx_lon), float(rx_lat), float(rx_lon), sample_spacing_m
    )
    if distance < 1.0:
        raise ValueError("Jarak pemancar dan penerima terlalu dekat untuk analisis profil lintasan.")
    bounds = _bounds_for_path(lats, lons)
    source = ""
    cache_hit = False
    elevations = None
    errors = []

    # Primary source: BIG DEMNAS (using an existing local cache whenever available).
    try:
        raster_path, source, cache_hit = fetch_big_demnas(bounds, resolution_m)
        elevations = _sample_raster(raster_path, lats, lons)
        if np.count_nonzero(np.isfinite(elevations)) < max(3, int(0.5 * len(elevations))):
            errors.append("DEMNAS BIG: terlalu banyak piksel NoData pada lintasan.")
            elevations = None
    except Exception as exc:
        errors.append(f"DEMNAS BIG: {exc}")

    # Alternate source 1: user-managed local GeoTIFF, useful for offline deployments.
    if elevations is None:
        local_path = get_local_dem_path()
        if local_path:
            try:
                elevations = _sample_raster(local_path, lats, lons)
                source = "Fallback DEM GeoTIFF lokal (KTVDI_DEM_PATH)"
                cache_hit = True
                if np.count_nonzero(np.isfinite(elevations)) < max(3, int(0.5 * len(elevations))):
                    errors.append("DEM lokal: terlalu banyak piksel NoData pada lintasan.")
                    elevations = None
            except Exception as exc:
                errors.append(f"DEM lokal: {exc}")

    # Alternate source 2: optional OpenTopography SRTM 30 m point sampling.
    if elevations is None:
        try:
            elevations = np.asarray(sample_opentopography(zip(lats.tolist(), lons.tolist())), dtype=float)
            source = "Fallback OpenTopography SRTM 30 m"
            cache_hit = False
        except Exception as exc:
            errors.append(f"Fallback OpenTopography: {exc}")
            raise RuntimeError("Data elevasi tidak tersedia. " + " | ".join(errors)) from exc

    valid = np.isfinite(elevations)
    if np.count_nonzero(valid) < max(3, int(0.5 * len(elevations))):
        raise RuntimeError("Terlalu banyak piksel NoData pada profil DEM; analisis dihentikan.")
    if not np.all(valid):
        elevations = np.interp(fractions, fractions[valid], elevations[valid])

    d1 = fractions * distance
    d2 = distance - d1
    curvature_bulge = d1 * d2 / (2.0 * EFFECTIVE_EARTH_K * EARTH_RADIUS_M)
    tx_level = elevations[0] + float(tx_antenna_m)
    rx_level = elevations[-1] + float(rx_antenna_m)
    direct_ray = tx_level + (rx_level - tx_level) * fractions
    apparent_terrain = elevations + curvature_bulge
    clearance = direct_ray - apparent_terrain
    wavelength = 299792458.0 / (float(frequency_mhz) * 1e6)
    fresnel_radius = np.sqrt(np.maximum(0.0, wavelength * d1 * d2 / distance))
    fresnel_clearance_ratio = np.divide(clearance, fresnel_radius, out=np.full_like(clearance, np.inf), where=fresnel_radius > 0)
    interior = slice(1, -1)
    min_clearance = float(np.min(clearance[interior]))
    min_fresnel_ratio = float(np.min(fresnel_clearance_ratio[interior]))
    return {
        "distance_km": distance / 1000.0,
        "sample_count": int(len(fractions)),
        "sample_spacing_m": distance / max(1, len(fractions) - 1),
        "distance_km_samples": (d1 / 1000.0).tolist(),
        "terrain_elevation_m": elevations.tolist(),
        "line_of_sight_m": direct_ray.tolist(),
        "terrain_with_curvature_m": apparent_terrain.tolist(),
        "clearance_m": clearance.tolist(),
        "fresnel_radius_m": fresnel_radius.tolist(),
        "minimum_clearance_m": min_clearance,
        "minimum_fresnel_clearance_ratio": min_fresnel_ratio,
        "geometric_los_clear": min_clearance >= 0.0,
        "first_fresnel_60pct_clear": min_fresnel_ratio >= 0.6,
        "dem_source": source,
        "cache_hit": bool(cache_hit),
        "resolution_m": float(resolution_m),
        "effective_earth_k": EFFECTIVE_EARTH_K,
        "frequency_mhz": float(frequency_mhz),
        "warning": "Pemeriksaan geometri lintasan; bukan prediksi field strength, difraksi, atau jaminan penerimaan DVB-T2.",
    }
