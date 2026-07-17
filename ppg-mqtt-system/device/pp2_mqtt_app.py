#!/usr/bin/env python3
"""Compatibility launcher; MQTT sekarang terintegrasi langsung di pp2.py."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import tkinter as tk


DEFAULT_PP2_SOURCE = Path(__file__).resolve().parents[2] / "ppg-desktop" / "pp2.py"
PP2_SOURCE = Path(os.getenv("PP2_SOURCE", DEFAULT_PP2_SOURCE)).expanduser().resolve()


def load_pp2_module(path: Path) -> ModuleType:
    if not path.exists():
        raise FileNotFoundError(
            f"pp2.py tidak ditemukan di {path}. Atur environment PP2_SOURCE."
        )

    spec = importlib.util.spec_from_file_location("pp2_integrated", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Gagal memuat module dari {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    pp2 = load_pp2_module(PP2_SOURCE)
    root = tk.Tk()
    app = pp2.ArduinoPlotApp(root)
    app.run()


if __name__ == "__main__":
    main()
