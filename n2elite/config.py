"""Persisted user preferences for N2Elite-ng (offline, local JSON).

Stored at ~/.n2elite/config.json. Holds only UI preferences — never keys or
device data.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.path.expanduser("~")) / ".n2elite"
CONFIG_PATH = CONFIG_DIR / "config.json"
DEFAULT_CACHE_DIR = str(CONFIG_DIR / "images")

_DEFAULTS = {
    "show_images_auto": False,   # auto-fetch + show amiibo images on read
    "cache_dir": DEFAULT_CACHE_DIR,
}


class Config:
    def __init__(self) -> None:
        self.data = dict(_DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update({k: loaded[k] for k in _DEFAULTS if k in loaded})
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:
            pass

    @property
    def show_images_auto(self) -> bool:
        return bool(self.data.get("show_images_auto", False))

    @show_images_auto.setter
    def show_images_auto(self, value: bool) -> None:
        self.data["show_images_auto"] = bool(value)

    @property
    def cache_dir(self) -> str:
        return self.data.get("cache_dir") or DEFAULT_CACHE_DIR

    @cache_dir.setter
    def cache_dir(self, value: str) -> None:
        self.data["cache_dir"] = str(value)
