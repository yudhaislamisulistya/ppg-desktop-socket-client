#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Penggunaan: $0 PPG-DEVICE_ID"
  exit 1
fi

DEVICE_ID=$1
case "$DEVICE_ID" in
  PPG-?*) ;;
  *)
    echo "Device ID harus diawali PPG- dan memiliki suffix."
    exit 1
    ;;
esac
case "$DEVICE_ID" in
  *[!A-Za-z0-9_-]*)
    echo "Device ID hanya boleh memakai huruf, angka, _ atau -."
    exit 1
    ;;
esac

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CONFIG_DIR="$ROOT_DIR/mosquitto/config"
PASSWORD_FILE="$CONFIG_DIR/passwords"
ACL_FILE="$CONFIG_DIR/acl"
IMAGE="eclipse-mosquitto:2.1.2-alpine"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker tidak ditemukan."
  exit 1
fi

if [ ! -f "$PASSWORD_FILE" ]; then
  echo "Jalankan scripts/init-broker-users.sh terlebih dahulu."
  exit 1
fi

docker run --rm -it \
  --user 0:0 \
  -v "$CONFIG_DIR:/mosquitto/config" \
  "$IMAGE" \
  mosquitto_passwd /mosquitto/config/passwords "$DEVICE_ID"

docker run --rm \
  --user 0:0 \
  -v "$CONFIG_DIR:/mosquitto/config" \
  "$IMAGE" \
  sh -c "chown mosquitto:mosquitto /mosquitto/config/passwords && chmod 600 /mosquitto/config/passwords"

BEGIN_MARKER="# BEGIN DEVICE $DEVICE_ID"
END_MARKER="# END DEVICE $DEVICE_ID"
TEMP_ACL=$(mktemp)
trap 'rm -f "$TEMP_ACL"' EXIT

awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
  $0 == begin { skipping = 1; next }
  $0 == end { skipping = 0; next }
  !skipping { print }
' "$ACL_FILE" > "$TEMP_ACL"

{
  printf "\n%s\n" "$BEGIN_MARKER"
  printf "user %s\n" "$DEVICE_ID"
  printf "topic write ppg/%s/raw\n" "$DEVICE_ID"
  printf "topic write ppg/%s/metrics\n" "$DEVICE_ID"
  printf "topic write ppg/%s/measurement/start\n" "$DEVICE_ID"
  printf "topic write ppg/%s/measurement/result\n" "$DEVICE_ID"
  printf "topic write ppg/%s/status\n" "$DEVICE_ID"
  printf "topic read ppg/%s/command\n" "$DEVICE_ID"
  printf "%s\n" "$END_MARKER"
} >> "$TEMP_ACL"

mv "$TEMP_ACL" "$ACL_FILE"
chmod 644 "$ACL_FILE"
trap - EXIT

echo "Perangkat $DEVICE_ID terdaftar."
echo "Restart broker bila broker sedang berjalan: docker compose restart mosquitto"
