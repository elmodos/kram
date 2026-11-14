"""Tray update checker: a short-lived check (check.py) and a tray icon that runs only while upgrades exist (tray.py).

Both run as systemd user services (data/systemd/); neither imports Qt. The check writes its result to STATE_FILE,
the tray watches that file.
"""
import configparser
import json
import os
from pathlib import Path

TRAY_UNIT = "kram-tray.service"
STALE_DAYS_DEFAULT = 7


def state_file() -> Path:
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return cache / "kram" / "update-check.json"


def read_state() -> dict:
    try:
        return json.loads(state_file().read_text())
    except (OSError, ValueError):
        return {}


def write_state(state: dict) -> None:
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(path)  # atomic: the tray never reads half a file


def stale_days() -> int:
    """Kram's setting (QSettings INI, ~/.config/kram/kram.conf), read without Qt."""
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "kram" / "kram.conf"
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(config, encoding="utf-8")
        return max(1, parser.getint("update_checker", "stale_days", fallback=STALE_DAYS_DEFAULT))
    except (configparser.Error, ValueError):
        return STALE_DAYS_DEFAULT
