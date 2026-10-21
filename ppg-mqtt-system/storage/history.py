"""Permintaan History melalui MQTT, dibatasi ACL perangkat di broker."""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime, timezone


LOGGER = logging.getLogger("ppg-history")
TOKEN = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")


def encode_response(payload):
    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value

    return json.dumps(clean(payload), ensure_ascii=False, allow_nan=False)


def handle_history_request(database, device_id, payload):
    if not isinstance(payload, dict):
        return None
    client_id, request_id = payload.get("client_id"), payload.get("request_id")
    if not all(isinstance(value, str) and TOKEN.fullmatch(value) for value in (client_id, request_id)):
        return None
    topic = f"ppg/{device_id}/history/response/{client_id}"
    response = {"request_id": request_id, "ok": False}
    try:
        if payload.get("device_id", device_id) != device_id:
            raise ValueError("Device ID tidak sesuai dengan topic.")
        action = payload.get("action")
        if action == "list":
            limit, offset = payload.get("limit", 20), payload.get("offset", 0)
            if type(limit) is not int or not 1 <= limit <= 100:
                raise ValueError("Limit History harus 1 sampai 100.")
            if type(offset) is not int or not 0 <= offset <= 1000000:
                raise ValueError("Offset History tidak valid.")
            rows = database.list_history(device_id, limit=limit + 1, offset=offset)
            response["data"] = {"measurements": rows[:limit], "has_more": len(rows) > limit,
                                "total": database.count_history(device_id)}
        elif action == "set_label":
            measurement_id = payload.get("measurement_id")
            if not isinstance(measurement_id, str) or not 1 <= len(measurement_id) <= 200:
                raise ValueError("ID rekaman tidak valid.")
            if "diabetes_label" not in payload:
                raise ValueError("diabetes_label wajib ada; gunakan null untuk belum diisi.")
            if payload["diabetes_label"] is not None and type(payload["diabetes_label"]) is not bool:
                raise ValueError("diabetes_label harus true, false, atau null.")
            row = database.update_diabetes_label(
                device_id=device_id, measurement_id=measurement_id,
                label=payload["diabetes_label"],
                updated_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            )
            if row is None:
                raise ValueError("Rekaman selesai tidak ditemukan pada perangkat ini.")
            response["data"] = row
        else:
            raise ValueError("Aksi History tidak valid.")
        response["ok"] = True
    except ValueError as error:
        response["error"] = str(error)
    except Exception:
        LOGGER.exception("Permintaan History gagal")
        response["error"] = "Penyimpanan History belum tersedia. Coba lagi."
    return topic, encode_response(response)
