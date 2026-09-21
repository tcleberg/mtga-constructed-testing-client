from __future__ import annotations

import json
import os
import platform
import uuid
from pathlib import Path

from platformdirs import user_config_dir, user_log_dir


APP_NAME = "MTGA Constructed Testing"
APP_AUTHOR = "MTGA CTA"


def default_player_log_path() -> Path:
    home = Path.home()
    if platform.system() == "Darwin":
        return home / "Library/Logs/Wizards of the Coast/MTGA/Player.log"
    if platform.system() == "Windows":
        profile = os.environ.get("USERPROFILE", str(home))
        return Path(profile) / "AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"
    return home / ".local/share/Wizards of the Coast/MTGA/Player.log"


def client_config_dir() -> Path:
    path = Path(user_config_dir(APP_NAME, APP_AUTHOR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def client_log_dir() -> Path:
    path = Path(user_log_dir(APP_NAME, APP_AUTHOR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def legacy_config_dir() -> Path:
    return Path.home() / ".mtga_cta"


def machine_id() -> str:
    path = client_config_dir() / "machine_id"
    legacy = legacy_config_dir() / "machine_id"
    if not path.exists() and legacy.exists():
        path.write_text(legacy.read_text(encoding="utf-8").strip(), encoding="utf-8")
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = uuid.uuid4().hex
    path.write_text(value, encoding="utf-8")
    return value


def load_client_config() -> dict:
    path = client_config_dir() / "config.json"
    legacy = legacy_config_dir() / "config.json"
    source = path if path.exists() else legacy
    if not source.exists():
        return {}
    return json.loads(source.read_text(encoding="utf-8"))


def save_client_config(config: dict) -> None:
    safe = {key: value for key, value in config.items() if key != "token"}
    (client_config_dir() / "config.json").write_text(
        json.dumps(safe, indent=2, sort_keys=True),
        encoding="utf-8",
    )
