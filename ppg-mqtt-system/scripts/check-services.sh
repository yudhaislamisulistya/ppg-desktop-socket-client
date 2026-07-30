#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

required_services="postgres mosquitto provisioner storage frontend"
running_services=$(docker compose ps --status running --services)

for service in $required_services; do
  if ! printf '%s\n' "$running_services" | grep -qx "$service"; then
    echo "GAGAL: service $service tidak running."
    docker compose ps -a
    exit 1
  fi
done

docker compose exec -T mosquitto sh -c \
  "nc -z 127.0.0.1 1883 && nc -z 127.0.0.1 9001"

docker compose exec -T frontend sh -c \
  "wget -qO- http://127.0.0.1/ | grep -q 'PPG Monitor'"

docker compose exec -T provisioner python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"

docker compose exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT to_regclass('\''public.measurements'\'');"' \
  | tr -d '[:space:]' \
  | grep -qx "measurements"

echo "OK: PostgreSQL sehat dan tabel measurements tersedia."
echo "OK: mosquitto TCP 1883 aktif."
echo "OK: mosquitto WebSocket 9001 aktif."
echo "OK: provisioner registrasi aktif."
echo "OK: storage running."
echo "OK: frontend PPG tersedia."
