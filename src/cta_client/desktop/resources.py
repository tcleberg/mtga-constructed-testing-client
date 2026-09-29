"""Application icon files for the window, tray, and Linux launcher."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon

from cta_client.paths import APP_ID, APP_NAME


def _icon_dirs() -> list[Path]:
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        exe_dir = Path(sys.executable).resolve().parent
        dirs.extend((meipass, exe_dir, exe_dir / "_internal"))
    dirs.append(Path(__file__).resolve().parent)
    seen: set[Path] = set()
    unique: list[Path] = []
    for folder in dirs:
        resolved = folder.resolve() if folder.exists() else folder
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(folder)
    return unique


def icon_file(*names: str) -> Path | None:
    """First existing icon among the packaging and freeze locations."""
    wanted = names or ("icon.png", "icon.svg")
    for folder in _icon_dirs():
        for name in wanted:
            path = folder / name
            if path.is_file():
                return path
    return None


def application_icon() -> QIcon:
    path = icon_file("icon.png", "icon.svg")
    return QIcon(str(path)) if path is not None else QIcon()


def install_linux_launcher() -> None:
    """Publish the icon and a .desktop file so Linux uses it in the dock.

    Launching the extracted binary does not go through a packaged .desktop,
    which is why a frozen Qt app otherwise keeps the Python icon even when
    the window is told to use ours.
    """
    if sys.platform != "linux":
        return
    png = icon_file("icon.png")
    if png is None:
        return
    apps = Path.home() / ".local/share/applications"
    icons = Path.home() / ".local/share/icons/hicolor/256x256/apps"
    apps.mkdir(parents=True, exist_ok=True)
    icons.mkdir(parents=True, exist_ok=True)
    dest = icons / f"{APP_ID}.png"
    dest.write_bytes(png.read_bytes())
    exe = Path(sys.executable).resolve()
    (apps / f"{APP_ID}.desktop").write_text(
        _desktop_entry(command=f'"{exe}"', icon=APP_ID),
        encoding="utf-8",
    )


def desktop_entry(*, command: str, icon: str) -> str:
    return _desktop_entry(command=command, icon=icon)


def _desktop_entry(*, command: str, icon: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Upload Arena match telemetry to your testing group\n"
        f"Exec={command}\n"
        f"Icon={icon}\n"
        f"StartupWMClass={APP_NAME}\n"
        "Terminal=false\n"
        "Categories=Game;\n"
        "X-GNOME-UsesNotifications=true\n"
    )
