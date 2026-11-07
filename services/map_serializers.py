from __future__ import annotations

import math
from typing import Any


PUBLIC_DETAIL_FIELDS = (
    "siaran", "tx_height_m", "tx_power_w", "erp_w",
    "antenna_gain_dbd", "feeder_loss_db",
    "last_updated_date", "last_updated_time",
)
PUBLIC_MEASUREMENT_FIELDS = (
    "provinsi", "wilayah", "mux", "strength", "quality",
    "snr", "ber", "device_type", "antenna_type", "timestamp",
)


def has_map_private_access(session: dict[str, Any] | None) -> bool:
    """Koordinat presisi dan data kontributor hanya untuk sesi login valid."""
    identity = (session or {}).get("auth") or (session or {})
    return bool(identity.get("username"))


def _rounded_coordinate(value: Any) -> float | None:
    try:
        number = float(value)
        if math.isfinite(number):
            return round(number, 2)
    except (TypeError, ValueError):
        pass
    return None


def serialize_map_measurement(record: dict[str, Any], authenticated: bool) -> dict[str, Any]:
    if authenticated:
        return dict(record)
    public = {key: record[key] for key in PUBLIC_MEASUREMENT_FIELDS if key in record}
    for key in ("latitude", "longitude"):
        rounded = _rounded_coordinate(record.get(key))
        if rounded is not None:
            public[key] = rounded
    return public


def serialize_map_detail(detail: Any, authenticated: bool) -> dict[str, Any]:
    if not isinstance(detail, dict):
        return {}
    if authenticated:
        return dict(detail)
    return {key: detail[key] for key in PUBLIC_DETAIL_FIELDS if key in detail}


def serialize_transmitter_row(row: dict[str, Any], authenticated: bool) -> dict[str, Any]:
    if authenticated:
        return dict(row)
    public = {
        key: row[key]
        for key in ("provinsi", "wilayah", "mux", "siaran")
        if key in row
    }
    public["detail"] = serialize_map_detail(row.get("detail") or {}, False)
    for key in ("latitude", "longitude"):
        rounded = _rounded_coordinate(row.get(key))
        if rounded is not None:
            public[key] = rounded
    return public


def serialize_map_response(action: str, payload: dict[str, Any], authenticated: bool) -> dict[str, Any]:
    """Envelope API berbeda; payload tetap memakai serializer sesuai hak akses."""
    if authenticated:
        return {"ok": True, "action": action, "access": "authenticated",
                "authenticated_data": payload}
    return {"ok": True, "action": action, "access": "public",
            "public_data": payload}
