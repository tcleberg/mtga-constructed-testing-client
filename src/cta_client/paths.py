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
from __future__ import annotations

import json
import os
import platform
import uuid
from collections.abc import MutableMapping
from pathlib import Path

import keyring
from platformdirs import PlatformDirs

APP_NAME = "MTGA Constructed Testing Assistant"
APP_AUTHOR = "CTA"
KEYRING_SERVICE = "mtga-constructed-testing-client"
TOKEN_KEY = "session-token"


def app_dirs() -> PlatformDirs:
    return PlatformDirs(APP_NAME, APP_AUTHOR)


def default_player_log_path() -> Path:
    system = platform.system()
    home = Path.home()
    if system == "Darwin":
        return home / "Library/Logs/Wizards of the Coast/MTGA/Player.log"
    if system == "Windows":
        local_low = os.environ.get("USERPROFILE", str(home))
        return Path(local_low) / "AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"
    return home / ".local/share/Wizards of the Coast/MTGA/Player.log"


def client_config_dir() -> Path:
    path = Path(app_dirs().user_config_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def client_log_dir() -> Path:
    path = Path(app_dirs().user_log_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def queue_dir() -> Path:
    path = Path(app_dirs().user_data_dir) / "queue"
    path.mkdir(parents=True, exist_ok=True)
    return path


def machine_id(config_dir: Path | None = None) -> str:
    path = (config_dir or client_config_dir()) / "machine_id"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = uuid.uuid4().hex
    path.write_text(value, encoding="utf-8")
    return value


def load_client_config(
    config_dir: Path | None = None,
    keyring_backend: object = keyring,
) -> dict:
    path = (config_dir or client_config_dir()) / "config.json"
    if not path.exists():
        return {}
    config = json.loads(path.read_text(encoding="utf-8"))
    token = config.pop("token", None)
    if token:
        keyring_backend.set_password(KEYRING_SERVICE, TOKEN_KEY, token)
        save_client_config(config, config_dir=config_dir)
    stored = keyring_backend.get_password(KEYRING_SERVICE, TOKEN_KEY)
    if stored:
        config["token"] = stored
    return config


def save_client_config(
    config: MutableMapping,
    config_dir: Path | None = None,
    keyring_backend: object = keyring,
) -> None:
    directory = config_dir or client_config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    clean = dict(config)
    token = clean.pop("token", None)
    if token:
        keyring_backend.set_password(KEYRING_SERVICE, TOKEN_KEY, str(token))
    path = directory / "config.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(clean, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def remove_token(keyring_backend: object = keyring) -> None:
    try:
        keyring_backend.delete_password(KEYRING_SERVICE, TOKEN_KEY)
    except keyring.errors.PasswordDeleteError:
        return
