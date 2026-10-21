#!/usr/bin/env python3
"""Tambahkan izin History tanpa mengubah password atau aturan ACL lama."""

import os
import re
import shutil
import tempfile
from pathlib import Path


def upgrade_history_acl(content):
    lines = content.splitlines()
    output = []
    for index, line in enumerate(lines):
        output.append(line)
        if not line.startswith("user "):
            continue
        username = line[5:].strip()
        if username == "storage":
            required = ["topic read ppg/+/history/request", "topic write ppg/+/history/response/#"]
        elif re.fullmatch(r"PPG-[A-Za-z0-9_-]+", username):
            required = [f"topic write ppg/{username}/history/request",
                        f"topic read ppg/{username}/history/response/#"]
        else:
            continue
        end = next((i for i in range(index + 1, len(lines)) if lines[i].startswith("user ")), len(lines))
        existing = set(lines[index + 1:end])
        output.extend(rule for rule in required if rule not in existing)
    return "\n".join(output) + "\n"


def main():
    path = Path(__file__).resolve().parents[1] / "mosquitto/config/acl"
    original = path.read_text(encoding="utf-8")
    updated = upgrade_history_acl(original)
    if original == updated:
        print("ACL History sudah sesuai; tidak ada perubahan.")
        return
    backup = path.with_name("acl.history.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    metadata = path.stat()
    descriptor, name = tempfile.mkstemp(dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(updated)
        os.chown(temporary, metadata.st_uid, metadata.st_gid)
        os.chmod(temporary, metadata.st_mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    print("ACL History diperbarui; password dan ACL lama dipertahankan.")


if __name__ == "__main__":
    main()
