#!/usr/bin/env sh
# Memastikan blok ACL alat yang sudah terdaftar memakai "topic readwrite"
# pada hierarchy ppg/<DEVICE_ID>/.
#
# Dipakai untuk alat yang sudah punya password di broker: register-device.sh
# akan meminta password baru, script ini tidak menyentuh file password sama
# sekali. Jika blok target hilang, blok dibuat kembali. Tanpa argumen, semua
# blok alat yang masih ada pada file ACL ikut dinaikkan.
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
if [ -n "$TARGET" ]; then
  case "$TARGET" in
    PPG-?*) ;;
    *)
      echo "Device ID harus diawali PPG- dan memiliki suffix."
      exit 1
      ;;
  esac
  case "$TARGET" in
    *[!A-Za-z0-9_-]*)
      echo "Device ID hanya boleh memakai huruf, angka, _ atau -."
      exit 1
      ;;
  esac
fi

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

if [ -n "$TARGET" ] && ! grep -Fqx "# BEGIN DEVICE $TARGET" "$ACL_FILE"; then
  {
    printf "\n# BEGIN DEVICE %s\n" "$TARGET"
    printf "user %s\n" "$TARGET"
    printf "topic readwrite ppg/%s/raw\n" "$TARGET"
    printf "topic readwrite ppg/%s/metrics\n" "$TARGET"
    printf "topic readwrite ppg/%s/measurement/start\n" "$TARGET"
    printf "topic readwrite ppg/%s/measurement/result\n" "$TARGET"
    printf "topic readwrite ppg/%s/status\n" "$TARGET"
    printf "topic read ppg/%s/command\n" "$TARGET"
    printf "# END DEVICE %s\n" "$TARGET"
  } >> "$TEMP_ACL"
fi

mv "$TEMP_ACL" "$ACL_FILE"
chmod 644 "$ACL_FILE"
trap - EXIT

if [ -n "$TARGET" ]; then
  echo "ACL $TARGET dipastikan readwrite. Cadangan: $ACL_FILE.bak"
else
  echo "ACL seluruh alat dinaikkan menjadi readwrite. Cadangan: $ACL_FILE.bak"
fi
echo "Terapkan di broker: docker compose restart mosquitto"
