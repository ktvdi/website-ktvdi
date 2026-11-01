"""Hybrid DEM access: BIG DEMNAS first, local GeoTIFF cache, optional OpenTopography fallback.

The service is requested only for a small area around a propagation path; this module
never downloads a nationwide raster. Cache files are GeoTIFFs in KTVDI_DEM_CACHE.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
from typing import Iterable

import requests

BIG_DEMNAS_IMAGE_SERVER = (
    "https://geoservices.big.go.id/raster/rest/services/DEMNAS/DEM_Indonesia/ImageServer"
)
DEFAULT_CACHE_DIR = Path(os.getenv("KTVDI_DEM_CACHE", "/tmp/ktvdi_dem_cache"))
MAX_CACHE_FILES = int(os.getenv("KTVDI_DEM_MAX_FILES", "20"))
MAX_CACHE_BYTES = int(os.getenv("KTVDI_DEM_MAX_BYTES", str(250 * 1024 * 1024)))
DEFAULT_RESOLUTION_M = 30.0


def _validate_bounds(bounds):
    xmin, ymin, xmax, ymax = map(float, bounds)
    if not (95 <= xmin < xmax <= 141 and -11 <= ymin < ymax <= 6):
        raise ValueError("Batas DEM berada di luar cakupan wilayah Indonesia yang didukung.")
    return xmin, ymin, xmax, ymax


def _cache_path(bounds, resolution_m, source="big_demnas"):
    token = ",".join(f"{v:.5f}" for v in bounds) + f"|{resolution_m:.1f}|{source}"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
    return DEFAULT_CACHE_DIR / f"{source}_{digest}.tif"


def _dimensions(bounds, resolution_m):
    xmin, ymin, xmax, ymax = bounds
    mid_lat = (ymin + ymax) / 2.0
    width_m = (xmax - xmin) * 111320.0 * max(0.15, math.cos(math.radians(mid_lat)))
    height_m = (ymax - ymin) * 110574.0
    width = max(2, min(15000, int(math.ceil(width_m / resolution_m))))
    height = max(2, min(4100, int(math.ceil(height_m / resolution_m))))
    return width, height


def _prune_cache(cache_dir: Path, keep: Path | None = None):
    """Bound ephemeral Streamlit Cloud storage; retain newest files first."""
    try:
        files = sorted(cache_dir.glob("*.tif"), key=lambda item: item.stat().st_mtime, reverse=True)
        total = 0
        retained = 0
        for item in files:
            size = item.stat().st_size
            if item == keep or (retained < MAX_CACHE_FILES and total + size <= MAX_CACHE_BYTES):
                total += size
                retained += 1
            else:
                item.unlink(missing_ok=True)
    except OSError:
        pass


def fetch_big_demnas(bounds, resolution_m=DEFAULT_RESOLUTION_M, timeout=60):
    """Fetch a small 30 m (default) GeoTIFF window from BIG's DEMNAS ImageServer."""
    bounds = _validate_bounds(bounds)
    if not (5 <= float(resolution_m) <= 250):
        raise ValueError("Resolusi DEM harus berada pada rentang 5–250 meter.")
    cache_file = _cache_path(bounds, resolution_m)
    if cache_file.exists() and cache_file.stat().st_size > 1024:
        return str(cache_file), "Cache lokal DEMNAS BIG", True

    width, height = _dimensions(bounds, float(resolution_m))
    params = {
        "f": "image", "format": "tiff", "pixelType": "F32",
        "interpolation": "RSP_BilinearInterpolation",
        "bbox": ",".join(f"{v:.8f}" for v in bounds),
        "bboxSR": 4326, "imageSR": 4326, "size": f"{width},{height}",
    }
    response = requests.get(
        BIG_DEMNAS_IMAGE_SERVER + "/exportImage", params=params,
        timeout=timeout, headers={"User-Agent": "KTVDI-terrain-analysis/1.0"},
    )
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").lower()
    if "image" not in content_type and "tiff" not in content_type and not response.content[:4] in (b"II*\x00", b"MM\x00*"):
        raise RuntimeError("Layanan DEMNAS tidak mengembalikan raster TIFF yang valid.")
    if len(response.content) < 1024:
        raise RuntimeError("Raster DEMNAS yang diterima terlalu kecil atau kosong.")
    try:
        import rasterio
        from rasterio.io import MemoryFile
        with MemoryFile(response.content) as memfile:
            with memfile.open() as dataset:
                if dataset.count < 1 or dataset.width < 2 or dataset.height < 2:
                    raise RuntimeError("Raster DEMNAS tidak memiliki band elevasi yang valid.")
                if dataset.crs is None:
                    raise RuntimeError("Raster DEMNAS tidak memiliki informasi CRS.")
    except ImportError as exc:
        raise RuntimeError("Paket rasterio diperlukan untuk membaca DEM.") from exc

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = cache_file.with_suffix(".tmp")
    temp_file.write_bytes(response.content)
    temp_file.replace(cache_file)
    _prune_cache(cache_file.parent, keep=cache_file)
    return str(cache_file), "DEMNAS BIG (diunduh; cache sementara Cloud)", False


def sample_opentopography(points: Iterable[tuple[float, float]], timeout=45):
    """Optional point-sample fallback using OpenTopography SRTMGL1 (requires API key).

    Returns elevations in metres or raises an actionable error. The API key must be
    supplied as OPENTOPOGRAPHY_API_KEY; no credential is embedded in the source.
    """
    api_key = os.getenv("OPENTOPOGRAPHY_API_KEY", "").strip()
    if not api_key:
        try:
            import streamlit as st
            api_key = str(st.secrets.get("OPENTOPOGRAPHY_API_KEY", "")).strip()
        except Exception:
            api_key = ""
    if not api_key:
        raise RuntimeError("Fallback OpenTopography belum dikonfigurasi (OPENTOPOGRAPHY_API_KEY).")
    points = list(points)
    if not points:
        return []
    locations = "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in points)
    response = requests.get(
        "https://api.opentopography.org/v1/srtm30m",
        params={"locations": locations, "interpolation": "cubic", "API_Key": api_key},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results") or payload.get("data") or []
    elevations = []
    for item in results:
        value = item.get("elevation") if isinstance(item, dict) else None
        elevations.append(float(value) if value is not None else float("nan"))
    if len(elevations) != len(points):
        raise RuntimeError("Jumlah sampel elevasi fallback tidak sesuai dengan titik lintasan.")
    return elevations


def get_local_dem_path():
    """Optional pre-downloaded GeoTIFF path for offline/alternate local DEM use."""
    value = os.getenv("KTVDI_DEM_PATH", "").strip()
    if value and Path(value).is_file():
        return value
    return None
