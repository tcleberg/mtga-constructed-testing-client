from __future__ import annotations

import platform
import plistlib
import subprocess
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_ID = "com.mtga-cta.client"


def command() -> str:
    return f'"{Path(sys.executable).resolve()}" --background'


def enabled() -> bool:
    if platform.system() == "Windows":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, "MTGA Constructed Testing")
            return True
        except FileNotFoundError:
            return False
    if platform.system() == "Darwin":
        return _launch_agent().exists()
    return False


def set_enabled(value: bool) -> None:
    if platform.system() == "Windows":
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if value:
                winreg.SetValueEx(key, "MTGA Constructed Testing", 0, winreg.REG_SZ, command())
            else:
                try:
                    winreg.DeleteValue(key, "MTGA Constructed Testing")
                except FileNotFoundError:
                    pass
        return
    if platform.system() == "Darwin":
        path = _launch_agent()
        if value:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                plistlib.dumps(
                    {
                        "Label": APP_ID,
                        "ProgramArguments": [str(Path(sys.executable).resolve()), "--background"],
                        "RunAtLoad": True,
                    }
                )
            )
            subprocess.run(["launchctl", "bootstrap", f"gui/{__import__('os').getuid()}", str(path)], check=False)
        elif path.exists():
            subprocess.run(["launchctl", "bootout", f"gui/{__import__('os').getuid()}", str(path)], check=False)
            path.unlink()


def _launch_agent() -> Path:
    return Path.home() / "Library/LaunchAgents" / f"{APP_ID}.plist"
