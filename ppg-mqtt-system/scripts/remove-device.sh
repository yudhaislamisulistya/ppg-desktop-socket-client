#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Penggunaan: $0 PPG-DEVICE_ID"
  exit 1
fi

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CONFIG_DIR="$ROOT_DIR/mosquitto/config"
PASSWORD_FILE="$CONFIG_DIR/passwords"
ACL_FILE="$CONFIG_DIR/acl"
IMAGE="eclipse-mosquitto:2.1.2-alpine"

if [ ! -f "$PASSWORD_FILE" ]; then
  echo "File password belum dibuat."
  exit 1
fi

docker run --rm \
  --user 0:0 \
  -v "$CONFIG_DIR:/mosquitto/config" \
  "$IMAGE" \
  mosquitto_passwd -D /mosquitto/config/passwords "$1"

docker run --rm \
  --user 0:0 \
  -v "$CONFIG_DIR:/mosquitto/config" \
  "$IMAGE" \
  sh -c "chown mosquitto:mosquitto /mosquitto/config/passwords && chmod 600 /mosquitto/config/passwords"

BEGIN_MARKER="# BEGIN DEVICE $1"
END_MARKER="# END DEVICE $1"
TEMP_ACL=$(mktemp)
trap 'rm -f "$TEMP_ACL"' EXIT

awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
  $0 == begin { skipping = 1; next }
  $0 == end { skipping = 0; next }
  !skipping { print }
' "$ACL_FILE" > "$TEMP_ACL"

mv "$TEMP_ACL" "$ACL_FILE"
chmod 644 "$ACL_FILE"
trap - EXIT

echo "Perangkat $1 dihapus."
echo "Restart broker bila broker sedang berjalan: docker compose restart mosquitto"
