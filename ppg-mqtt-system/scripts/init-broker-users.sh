#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CONFIG_DIR="$ROOT_DIR/mosquitto/config"
ENV_FILE="$ROOT_DIR/.env"
IMAGE="eclipse-mosquitto:2.1.2-alpine"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker tidak ditemukan."
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "Salin .env.example menjadi .env lalu isi STORAGE_PASSWORD."
  exit 1
fi

set -a
. "$ENV_FILE"
set +a

if [ -z "${STORAGE_PASSWORD:-}" ]; then
  echo "STORAGE_PASSWORD belum diisi di .env."
  exit 1
fi

mkdir -p "$CONFIG_DIR"

if [ -f "$CONFIG_DIR/passwords" ]; then
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    -v "$CONFIG_DIR:/mosquitto/config" \
    "$IMAGE" \
    mosquitto_passwd -b /mosquitto/config/passwords storage "$STORAGE_PASSWORD"
else
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    -v "$CONFIG_DIR:/mosquitto/config" \
    "$IMAGE" \
    mosquitto_passwd -b -c /mosquitto/config/passwords storage "$STORAGE_PASSWORD"
fi

echo "Buat atau perbarui password akun dashboard:"
docker run --rm -it \
  --user "$(id -u):$(id -g)" \
  -v "$CONFIG_DIR:/mosquitto/config" \
  "$IMAGE" \
  mosquitto_passwd /mosquitto/config/passwords dashboard

chmod 600 "$CONFIG_DIR/passwords"
echo "Akun storage dan dashboard siap."
