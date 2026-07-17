#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

required_services="mosquitto storage frontend"
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
  "wget -qO- http://127.0.0.1/ | grep -q 'PPG Realtime Dashboard'"

echo "OK: mosquitto TCP 1883 aktif."
echo "OK: mosquitto WebSocket 9001 aktif."
echo "OK: storage running."
echo "OK: frontend PPG tersedia."
