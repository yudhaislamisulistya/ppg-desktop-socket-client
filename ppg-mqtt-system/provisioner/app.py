#!/usr/bin/env python3
"""API kecil untuk mendaftarkan akun alat ke password file dan ACL Mosquitto."""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import stat
import subprocess
import tempfile
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
LOGGER = logging.getLogger("ppg-provisioner")

CONFIG_DIR = Path(os.getenv("MOSQUITTO_CONFIG_DIR", "/mosquitto/config"))
PASSWORD_FILE = CONFIG_DIR / "passwords"
ACL_FILE = CONFIG_DIR / "acl"
DEVICE_PATTERN = re.compile(r"PPG-[A-Za-z0-9_-]+\Z")
MAX_BODY_BYTES = 4096
REGISTRATION_LIMIT = 20
REGISTRATION_WINDOW_SECONDS = 60
registration_lock = threading.Lock()
registration_attempts: deque[float] = deque()
rate_limit_lock = threading.Lock()


def validate_registration(payload: Any) -> tuple[str, str, str]:
    if not isinstance(payload, dict):
        raise ValueError("Body JSON harus berupa object.")

    device_id = payload.get("device_id")
    username = payload.get("mqtt_username")
    password = payload.get("mqtt_password")
    if not all(isinstance(value, str) for value in (device_id, username, password)):
        raise ValueError("device_id, mqtt_username, dan mqtt_password wajib diisi.")

    device_id = device_id.strip()
    username = username.strip()
    if not DEVICE_PATTERN.fullmatch(device_id):
        raise ValueError(
            "Device ID harus diawali PPG- dan hanya berisi huruf, angka, _ atau -."
        )
    if username != device_id:
        raise ValueError("Untuk akun alat, mqtt_username harus sama dengan device_id.")
    if len(password) < 12:
        raise ValueError("MQTT password minimal 12 karakter.")
    return device_id, username, password


def render_device_acl(content: str, device_id: str) -> str:
    begin = f"# BEGIN DEVICE {device_id}"
    end = f"# END DEVICE {device_id}"
    output: list[str] = []
    skipping = False

    for line in content.splitlines():
        if line == begin:
            skipping = True
            continue
        if line == end:
            if not skipping:
                raise ValueError(f"ACL memiliki marker akhir tanpa awal untuk {device_id}.")
            skipping = False
            continue
        if not skipping:
            output.append(line)

    if skipping:
        raise ValueError(f"ACL memiliki blok tidak lengkap untuk {device_id}.")

    block = [
        begin,
        f"user {device_id}",
        f"topic readwrite ppg/{device_id}/raw",
        f"topic readwrite ppg/{device_id}/metrics",
        f"topic readwrite ppg/{device_id}/measurement/start",
        f"topic readwrite ppg/{device_id}/measurement/result",
        f"topic readwrite ppg/{device_id}/status",
        f"topic read ppg/{device_id}/command",
        end,
    ]
    return "\n".join(output).rstrip() + "\n\n" + "\n".join(block) + "\n"


def replace_preserving_access(path: Path, content: str) -> None:
    metadata = path.stat()
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.chown(temporary_path, metadata.st_uid, metadata.st_gid)
        os.chmod(temporary_path, stat.S_IMODE(metadata.st_mode))
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def update_password(username: str, password: str) -> None:
    metadata = PASSWORD_FILE.stat()
    completed = subprocess.run(
        ["mosquitto_passwd", "-b", str(PASSWORD_FILE), username, password],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip() or "mosquitto_passwd gagal memperbarui akun."
        )
    os.chown(PASSWORD_FILE, metadata.st_uid, metadata.st_gid)
    os.chmod(PASSWORD_FILE, stat.S_IMODE(metadata.st_mode))


def password_user_exists(username: str) -> bool:
    return any(
        line.partition(":")[0] == username
        for line in PASSWORD_FILE.read_text(encoding="utf-8").splitlines()
    )


def registration_rate_allowed() -> bool:
    now = time.monotonic()
    cutoff = now - REGISTRATION_WINDOW_SECONDS
    with rate_limit_lock:
        while registration_attempts and registration_attempts[0] < cutoff:
            registration_attempts.popleft()
        if len(registration_attempts) >= REGISTRATION_LIMIT:
            return False
        registration_attempts.append(now)
        return True


def register_device(device_id: str, username: str, password: str) -> str:
    if not PASSWORD_FILE.is_file() or not ACL_FILE.is_file():
        raise FileNotFoundError(
            "Password file/ACL belum tersedia; jalankan init-broker-users.sh."
        )

    with registration_lock:
        already_registered = password_user_exists(username)
        if not already_registered:
            update_password(username, password)
        acl_content = ACL_FILE.read_text(encoding="utf-8")
        replace_preserving_access(
            ACL_FILE,
            render_device_acl(acl_content, device_id),
        )
        # Container provisioner bergabung ke PID namespace service Mosquitto.
        os.kill(1, signal.SIGHUP)
        return "already_registered" if already_registered else "registered"


class RegistrationHandler(BaseHTTPRequestHandler):
    registration_enabled = True
    server_version = "PPGProvisioner/1.0"
    sys_version = ""

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(200, {"status": "ok"})
        else:
            self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/api/devices/register":
            self.send_json(404, {"error": "not_found"})
            return

        if not self.registration_enabled:
            self.send_json(403, {"error": "registration_disabled"})
            return
        if not registration_rate_allowed():
            self.send_json(429, {"error": "registration_rate_limited"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length < 2 or content_length > MAX_BODY_BYTES:
                self.send_json(413, {"error": "invalid_body_size"})
                return
            payload = json.loads(self.rfile.read(content_length))
            device_id, username, password = validate_registration(payload)
            status = register_device(device_id, username, password)
        except json.JSONDecodeError:
            self.send_json(400, {"error": "invalid_json"})
            return
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
            return
        except FileNotFoundError as error:
            self.send_json(503, {"error": str(error)})
            return
        except Exception:
            LOGGER.exception("Registrasi gagal")
            self.send_json(500, {"error": "registration_failed"})
            return

        LOGGER.info("Perangkat %s: %s", device_id, status)
        self.send_json(
            200 if status == "already_registered" else 201,
            {"status": status, "device_id": device_id},
        )

    def log_message(self, message: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.client_address[0], message % args)


def main() -> None:
    RegistrationHandler.registration_enabled = (
        os.getenv("ALLOW_DEVICE_REGISTRATION", "true").lower()
        in {"1", "true", "yes"}
    )
    address = os.getenv("LISTEN_ADDRESS", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    LOGGER.info(
        "Provisioner aktif pada %s:%s; registration=%s",
        address,
        port,
        RegistrationHandler.registration_enabled,
    )
    ThreadingHTTPServer((address, port), RegistrationHandler).serve_forever()


if __name__ == "__main__":
    main()
