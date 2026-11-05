from __future__ import annotations
from datetime import datetime
from typing import Any
from firebase_admin import db

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


def get_latest_transmitter_update_timestamp() -> str | None:
    """Waktu perubahan terakhir pada titik pemancar atau informasi pemancarnya."""
    logs = db.reference("audit_logs").get() or {}
    relevant = {
        "add_broadcast", "edit_broadcast", "delete_broadcast", "restore_broadcast",
        "add_coordinates", "update_coordinates", "delete_coordinates",
        "update_transmitter_technical_data",
    }
    timestamps = [
        str(item.get("timestamp", "")).strip()
        for item in logs.values()
        if isinstance(item, dict)
        and item.get("action") in relevant
        and item.get("timestamp")
    ]
    if not timestamps:
        return None
    latest = max(timestamps)
    try:
        return datetime.strptime(latest[:19], "%Y-%m-%d %H:%M:%S").strftime("%d-%m-%Y %H:%M")
    except ValueError:
        return latest[:16]


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
    allowed={"add_broadcast","edit_broadcast","delete_broadcast","restore_broadcast",
             "approve_broadcast_edit_request","reject_broadcast_edit_request"}
    values=[v for v in logs.values() if isinstance(v,dict) and v.get("action") in allowed]
    values.sort(key=lambda x:x.get("timestamp",""),reverse=True)
    return values[:limit]
