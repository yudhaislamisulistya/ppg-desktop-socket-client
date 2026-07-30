#!/bin/sh
set -eu

APP_NAME="PPG-Glucometer"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
DEVICE_DIR="$PROJECT_DIR/ppg-mqtt-system/device"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"
PYTHON="$VENV_DIR/bin/python"
DIST_ROOT="$SCRIPT_DIR/dist"
APP_DIR="$DIST_ROOT/$APP_NAME"
BUILD_ROOT="$SCRIPT_DIR/build"

if [ "$(uname -s)" != "Linux" ]; then
    echo "Build harus dijalankan langsung di Raspberry Pi OS."
    exit 1
fi

case "$(uname -m)" in
    aarch64|armv6l|armv7l) ;;
    *)
        echo "Arsitektur ini bukan Raspberry Pi. Jalankan build langsung di alat."
        exit 1
        ;;
esac

if [ "$(id -u)" -eq 0 ]; then
    echo "Jangan gunakan sudo. Jalankan script sebagai user Desktop Raspberry Pi."
    exit 1
fi

if [ ! -f "$DEVICE_DIR/mqtt_flow.py" ]; then
    echo "Tidak menemukan $DEVICE_DIR/mqtt_flow.py."
    echo "Pertahankan struktur ppg-desktop dan ppg-mqtt-system dalam satu project."
    exit 1
fi

if [ ! -x "$PYTHON" ]; then
    echo "Membuat virtual environment di $VENV_DIR ..."
    if ! python3 -m venv "$VENV_DIR"; then
        echo "Gagal membuat venv. Jalankan: sudo apt install python3-venv"
        exit 1
    fi
fi

if ! "$PYTHON" -c "import tkinter" >/dev/null 2>&1; then
    echo "Tkinter belum tersedia. Jalankan: sudo apt install python3-tk"
    exit 1
fi

echo "Memasang dependency build ..."
"$PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt" pyinstaller

mkdir -p "$BUILD_ROOT"

echo "Membuat aplikasi $APP_NAME ..."
"$PYTHON" -m PyInstaller \
    --noconfirm \
    --clean \
    --onedir \
    --windowed \
    --name "$APP_NAME" \
    --paths "$DEVICE_DIR" \
    --hidden-import mqtt_flow \
    --distpath "$DIST_ROOT" \
    --workpath "$BUILD_ROOT/work" \
    --specpath "$BUILD_ROOT" \
    "$SCRIPT_DIR/pp2.py"

APPLICATIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPLICATIONS_DIR"

write_launcher() {
    launcher_path=$1
    {
        printf '%s\n' "[Desktop Entry]"
        printf '%s\n' "Type=Application"
        printf '%s\n' "Name=PPG Glucometer"
        printf '%s\n' "Comment=Aplikasi pengukuran PPG Glucometer"
        printf '%s\n' "Exec=\"$APP_DIR/$APP_NAME\""
        printf '%s\n' "Path=$APP_DIR"
        printf '%s\n' "Icon=utilities-system-monitor"
        printf '%s\n' "Terminal=false"
        printf '%s\n' "Categories=Utility;"
        printf '%s\n' "StartupNotify=true"
    } > "$launcher_path"
    chmod +x "$launcher_path"
}

write_launcher "$APPLICATIONS_DIR/ppg-glucometer.desktop"

DESKTOP_DIR=""
if command -v xdg-user-dir >/dev/null 2>&1; then
    DESKTOP_DIR=$(xdg-user-dir DESKTOP 2>/dev/null || true)
fi
if [ -z "$DESKTOP_DIR" ]; then
    DESKTOP_DIR="$HOME/Desktop"
fi
if [ -d "$DESKTOP_DIR" ]; then
    write_launcher "$DESKTOP_DIR/PPG-Glucometer.desktop"
    if command -v gio >/dev/null 2>&1; then
        gio set "$DESKTOP_DIR/PPG-Glucometer.desktop" metadata::trusted true \
            >/dev/null 2>&1 || true
    fi
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi

echo
echo "Selesai."
echo "Aplikasi : $APP_DIR/$APP_NAME"
echo "Menu     : PPG Glucometer"
if [ -d "$DESKTOP_DIR" ]; then
    echo "Desktop  : $DESKTOP_DIR/PPG-Glucometer.desktop"
fi
