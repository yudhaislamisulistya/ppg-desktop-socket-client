#!/usr/bin/env sh
# Menaikkan blok ACL alat yang sudah terdaftar dari "topic write" menjadi
# "topic readwrite" pada hierarchy ppg/<DEVICE_ID>/.
#
# Dipakai untuk alat yang sudah punya password di broker: register-device.sh
# akan meminta password baru, script ini tidak menyentuh file password sama
# sekali. Tanpa argumen, semua alat pada file ACL ikut dinaikkan.
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ACL_FILE="$ROOT_DIR/mosquitto/config/acl"

if [ ! -f "$ACL_FILE" ]; then
  echo "File ACL tidak ditemukan: $ACL_FILE"
  exit 1
fi

if [ "$#" -gt 1 ]; then
  echo "Penggunaan: $0 [PPG-DEVICE_ID]"
  exit 1
fi

TARGET=${1:-}
TEMP_ACL=$(mktemp)
trap 'rm -f "$TEMP_ACL"' EXIT

cp "$ACL_FILE" "$ACL_FILE.bak"

# Hanya baris di dalam blok "# BEGIN DEVICE ..." / "# END DEVICE ..." yang
# diubah, sehingga blok storage dan dashboard tetap read-only.
awk -v target="$TARGET" '
  /^# BEGIN DEVICE / {
    inside = 1
    device = $4
    selected = (target == "" || target == device)
    print
    next
  }
  /^# END DEVICE / {
    inside = 0
    selected = 0
    print
    next
  }
  inside && selected && $1 == "topic" && $2 == "write" && $3 != "" {
    printf "topic readwrite %s\n", $3
    changed++
    next
  }
  { print }
  END { if (changed > 0) printf "%d baris ACL dinaikkan.\n", changed > "/dev/stderr" }
' "$ACL_FILE" > "$TEMP_ACL"

mv "$TEMP_ACL" "$ACL_FILE"
chmod 644 "$ACL_FILE"
trap - EXIT

if [ -n "$TARGET" ]; then
  echo "ACL $TARGET dinaikkan menjadi readwrite. Cadangan: $ACL_FILE.bak"
else
  echo "ACL seluruh alat dinaikkan menjadi readwrite. Cadangan: $ACL_FILE.bak"
fi
echo "Terapkan di broker: docker compose restart mosquitto"
