from __future__ import annotations

import json
import os
import platform
import re
import uuid
from pathlib import Path

from platformdirs import user_config_dir, user_log_dir


APP_NAME = "MTGA Constructed Testing"
APP_AUTHOR = "MTGA CTA"

# Steam store id for MTG Arena. Used as the preferred Proton prefix when
# several compatdata directories have a Player.log.
ARENA_STEAM_APP_ID = "2141910"
_WIZARDS = ("Wizards Of The Coast", "Wizards of the Coast")


def default_player_log_path() -> Path:
    """The log we will follow: an existing file from a known location, or
    the platform path Arena writes when it has not launched yet.
    """
    return resolve_player_log_path()


def resolve_player_log_path(configured: str | None = None) -> Path:
    """Honor an explicit path that exists; otherwise search common locations.

    `~` and `$HOME` are expanded. Quotes and a `file://` prefix from a
    paste are stripped. A configured path that does not exist yet is kept
    only when nothing discoverable is present, so a tester can point at a
    file Arena has not created. A stale default loses to a real Proton log.
    """
    cleaned = _clean_configured_path(configured)
    if cleaned is not None and cleaned.is_file():
        return cleaned
    found = discover_player_log_path()
    if found is not None and (cleaned is None or _is_generated_default(cleaned)):
        return found
    if cleaned is not None:
        return cleaned
    return found or _fallback_player_log_path()


def discover_player_log_path() -> Path | None:
    """Newest existing Player.log under the known Arena/Wine/Steam roots."""
    existing = [path for path in _candidate_player_log_paths() if path.is_file()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def _normalized(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _is_generated_default(path: Path) -> bool:
    """True when this is a stock guess, not a path the tester typed."""
    target = _normalized(path)
    defaults = [_fallback_player_log_path(), *_candidate_player_log_paths()]
    if any(_normalized(default) == target for default in defaults):
        return True
    posix = Path(os.path.normpath(str(path))).as_posix().lower()
    return posix.endswith("wizards of the coast/mtga/player.log")


def _clean_configured_path(configured: str | None) -> Path | None:
    text = (configured or "").strip().strip('"').strip("'")
    if text.startswith("file://"):
        text = text[7:]
    if not text:
        return None
    text = os.path.expandvars(text)
    if text.startswith("~"):
        # Path.expanduser() on Windows ignores HOME and uses USERPROFILE.
        # Path.home() is what discovery uses and what tests patch.
        rest = text[1:].lstrip("/\\")
        return Path.home() / rest if rest else Path.home()
    return Path(text)


def _fallback_player_log_path() -> Path:
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        return home / "Library/Logs/Wizards of the Coast/MTGA/Player.log"
    if system == "Windows":
        profile = os.environ.get("USERPROFILE", str(home))
        return Path(profile) / "AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"
    for root in _steam_roots(home):
        return (
            root
            / "steamapps"
            / "compatdata"
            / ARENA_STEAM_APP_ID
            / "pfx"
            / "drive_c/users/steamuser/AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"
        )
    return home / ".local/share/Wizards of the Coast/MTGA/Player.log"


def _candidate_player_log_paths() -> list[Path]:
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        return [home / "Library/Logs/Wizards of the Coast/MTGA/Player.log"]
    if system == "Windows":
        profile = os.environ.get("USERPROFILE", str(home))
        return [Path(profile) / "AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"]
    return _linux_player_log_candidates(home)


def _linux_player_log_candidates(home: Path) -> list[Path]:
    found: list[Path] = []
    for wizards in _WIZARDS:
        found.append(home / ".local/share" / wizards / "MTGA/Player.log")
    for root in _steam_roots(home):
        found.extend(_proton_player_logs(root / "steamapps" / "compatdata"))
    found.extend(_wine_player_logs(home / ".wine"))
    bottles = home / ".local/share/bottles/bottles"
    if bottles.is_dir():
        for prefix in bottles.iterdir():
            found.extend(_wine_player_logs(prefix))
    games = home / "Games"
    if games.is_dir():
        for child in games.iterdir():
            found.extend(_wine_player_logs(child))
            heroic = child / "Prefixes" if child.name == "Heroic" else child / "pfx"
            if heroic.is_dir():
                for prefix in heroic.iterdir():
                    found.extend(_wine_player_logs(prefix))
    return found


def _steam_roots(home: Path) -> list[Path]:
    declared = [
        os.environ.get("STEAM_DIR"),
        str(home / ".steam/steam"),
        str(home / ".steam/root"),
        str(home / ".local/share/Steam"),
        str(home / "Steam"),
        str(home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"),
        str(home / ".var/app/com.valvesoftware.Steam/data/Steam"),
        str(home / "snap/steam/common/.local/share/Steam"),
    ]
    roots: list[Path] = []
    seen: set[Path] = set()
    for raw in declared:
        if not raw:
            continue
        root = Path(os.path.expandvars(raw)).expanduser()
        if not root.is_dir():
            continue
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        roots.append(root)
        for library in _steam_libraries(root):
            resolved_library = library.resolve() if library.exists() else library
            if resolved_library in seen:
                continue
            seen.add(resolved_library)
            roots.append(library)
    return roots


def _steam_libraries(root: Path) -> list[Path]:
    for relative in ("steamapps/libraryfolders.vdf", "config/libraryfolders.vdf"):
        payload = root / relative
        if payload.is_file():
            return _library_paths_from_vdf(payload)
    return []


def _library_paths_from_vdf(path: Path) -> list[Path]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [Path(value) for value in re.findall(r'"path"\s+"([^"]+)"', text)]


def _proton_player_logs(compatdata: Path) -> list[Path]:
    if not compatdata.is_dir():
        return []
    found: list[Path] = []
    preferred = compatdata / ARENA_STEAM_APP_ID / "pfx"
    prefixes = [preferred] if preferred.is_dir() else []
    prefixes.extend(
        child / "pfx"
        for child in sorted(compatdata.iterdir())
        if child.name != ARENA_STEAM_APP_ID and (child / "pfx").is_dir()
    )
    for prefix in prefixes:
        found.extend(_wine_player_logs(prefix))
    return found


def _wine_player_logs(prefix: Path) -> list[Path]:
    found: list[Path] = []
    for wizards in _WIZARDS:
        found.extend(
            prefix.glob(f"drive_c/users/*/AppData/LocalLow/{wizards}/MTGA/Player.log")
        )
    return found


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
