from pathlib import Path

from cta_client.paths import (
    ARENA_STEAM_APP_ID,
    default_player_log_path,
    discover_player_log_path,
    resolve_player_log_path,
)


def _linux(monkeypatch, home: Path) -> None:
    monkeypatch.setattr("cta_client.paths.platform.system", lambda: "Linux")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("STEAM_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))


def _proton_log(home: Path, app_id: str = ARENA_STEAM_APP_ID) -> Path:
    path = (
        home
        / ".steam/steam/steamapps/compatdata"
        / app_id
        / "pfx/drive_c/users/steamuser/AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("unity", encoding="utf-8")
    return path


def test_linux_discovers_proton_player_log(tmp_path, monkeypatch):
    _linux(monkeypatch, tmp_path)
    log = _proton_log(tmp_path)
    assert discover_player_log_path() == log
    assert default_player_log_path() == log


def test_linux_prefers_newer_log(tmp_path, monkeypatch):
    _linux(monkeypatch, tmp_path)
    older = _proton_log(tmp_path)
    newer = (
        tmp_path
        / ".wine/drive_c/users/tester/AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"
    )
    newer.parent.mkdir(parents=True)
    newer.write_text("wine", encoding="utf-8")
    older.touch()
    newer.touch()
    # Make wine newer after proton exists.
    import time

    time.sleep(0.02)
    newer.write_text("wine2", encoding="utf-8")
    assert discover_player_log_path() == newer


def test_linux_flatpak_steam(tmp_path, monkeypatch):
    _linux(monkeypatch, tmp_path)
    log = (
        tmp_path
        / ".var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata"
        / ARENA_STEAM_APP_ID
        / "pfx/drive_c/users/steamuser/AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"
    )
    log.parent.mkdir(parents=True)
    log.write_text("flatpak", encoding="utf-8")
    assert discover_player_log_path() == log


def test_stale_xdg_default_loses_to_proton(tmp_path, monkeypatch):
    _linux(monkeypatch, tmp_path)
    log = _proton_log(tmp_path)
    stale = tmp_path / ".local/share/Wizards of the Coast/MTGA/Player.log"
    assert resolve_player_log_path(str(stale)) == log


def test_explicit_missing_path_is_kept(tmp_path, monkeypatch):
    _linux(monkeypatch, tmp_path)
    _proton_log(tmp_path)
    custom = tmp_path / "custom" / "Player.log"
    assert resolve_player_log_path(str(custom)) == custom


def test_existing_configured_path_wins(tmp_path, monkeypatch):
    _linux(monkeypatch, tmp_path)
    _proton_log(tmp_path)
    chosen = tmp_path / "override.log"
    chosen.write_text("mine", encoding="utf-8")
    assert resolve_player_log_path(str(chosen)) == chosen


def test_expands_tilde_and_strips_quotes(tmp_path, monkeypatch):
    _linux(monkeypatch, tmp_path)
    log = tmp_path / "Player.log"
    log.write_text("x", encoding="utf-8")
    assert resolve_player_log_path(f'"{log}"') == log
    assert resolve_player_log_path(f"file://{log}") == log
    assert resolve_player_log_path("~/Player.log") == log


def test_linux_fallback_is_proton_when_steam_exists(tmp_path, monkeypatch):
    _linux(monkeypatch, tmp_path)
    (tmp_path / ".steam/steam").mkdir(parents=True)
    path = default_player_log_path()
    assert ARENA_STEAM_APP_ID in str(path)
    assert path.name == "Player.log"
