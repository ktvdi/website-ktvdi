"""Orkestrasi event frontend KTVDI dan facade kompatibilitas layanan.

Fungsi layanan dipisahkan ke paket ``services`` berdasarkan tanggung jawab.
Modul ini mempertahankan ``handle_event`` sebagai titik masuk yang dipakai app.py.
"""
from __future__ import annotations

import math
import random
import re
from datetime import datetime
from typing import Any

from firebase_admin import db
from pytz import timezone

from services.core import (
    DB_URL, WIB, now_wib, initialize_firebase, _safe_key, _audit,
    _require_auth, _require_admin,
)
from services.auth import (
    _PASSWORD_HASHER, hash_password, hash_otp,
    verify_password_and_migrate, login, _send_otp,
)
from services.broadcasts import (
    get_all_broadcast_rows, get_latest_transmitter_update_timestamp,
    get_stats, search_broadcasts, get_recent_changes,
)
from services.map_serializers import has_map_private_access, serialize_transmitter_row
from services.community import (
    _public_user, _all_reports, _all_users_public, _profile, _comments,
)

REPORT_STATUSES = ["Menunggu", "Sedang ditinjau", "Selesai", "Ditolak"]

def handle_event(event: dict[str, Any], session: dict[str, Any], secrets=None) -> dict[str, Any]:
    """Dispatch event frontend ke handler fitur dengan otorisasi di sisi server."""
    action = event.get("action")
    try:
        # Kebijakan akses terpusat untuk seluruh endpoint Peta Pemancar.
        # Hanya endpoint baca yang tercantum eksplisit di sini yang boleh anonim.
        map_public_reads = {
            "load_measurements", "load_details", "calculate_terrain",
            "search", "refresh",
        }
        map_authenticated = {
            "submit_measurement",
            "load_point_requests", "submit_point_change_request",
            "approve_point_change_request", "reject_point_change_request",
            "save_coordinates", "delete_coordinates",
            "load_broadcast_edit_requests", "submit_broadcast_edit_request",
            "approve_broadcast_edit_request", "reject_broadcast_edit_request",
            "add_broadcast", "edit_broadcast", "delete_broadcast",
        }
        admin_only = {"save_technical", "load_admin", "admin_report_update", "admin_restore"}

        if action in map_authenticated:
            _require_auth(session)
        if action in admin_only:
            _require_admin(session)
        from handlers.auth_handler import handle_auth_handler
        from handlers.broadcast_handler import handle_broadcast_handler
        from handlers.coordinate_handler import handle_coordinate_handler
        from handlers.measurement_handler import handle_measurement_handler
        from handlers.community_handler import handle_community_handler
        from handlers.report_admin_handler import handle_report_admin_handler

        handlers = (
            handle_auth_handler,
            handle_broadcast_handler,
            handle_coordinate_handler,
            handle_measurement_handler,
            handle_community_handler,
            handle_report_admin_handler,
        )
        for handler in handlers:
            result = handler(action, event, session, secrets)
            if result is not None:
                return result
        authenticated = has_map_private_access(session)
        if action == "search":
            results = search_broadcasts(str(event.get("query", "")))
            return {"ok": True, "results": [serialize_transmitter_row(row, authenticated) for row in results]}
        if action in ("refresh", None):
            rows = [serialize_transmitter_row(row, authenticated) for row in get_all_broadcast_rows()]
            return {"ok": True, "stats": get_stats(), "rows": rows, "changes": get_recent_changes()}
        return {"ok": False, "message": "Aksi tidak dikenal."}
    except Exception as exc:
        return {"ok": False, "message": str(exc) if isinstance(exc, (ValueError, PermissionError, RuntimeError)) else "Terjadi kesalahan layanan. Periksa konfigurasi dan log server."}
