from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import collect_submodules


root = Path(SPECPATH).parents[1]
name = "MTGA Constructed Testing"
version = os.environ.get("APP_VERSION", "0.2.0")
hidden = collect_submodules("keyring.backends")
runtime_hook = root / "build/default_server.py"
runtime_hook.parent.mkdir(parents=True, exist_ok=True)
runtime_hook.write_text(
    "import os\n"
    f"os.environ.setdefault('CTA_DEFAULT_SERVER_URL', {os.environ.get('CTA_DEFAULT_SERVER_URL', '')!r})\n",
    encoding="utf-8",
)

analysis = Analysis(
    [str(root / "src/cta_client/desktop/app.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[(str(root / "LICENSE"), "."), (str(root / "NOTICE"), ".")],
    hiddenimports=hidden,
    runtime_hooks=[str(runtime_hook)],
    excludes=["cta_server", "numpy", "scipy", "pytest"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
)
bundle = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name=name,
)

if sys.platform == "darwin":
    app = BUNDLE(
        bundle,
        name=f"{name}.app",
        bundle_identifier="com.mtga-cta.client",
        info_plist={
            "CFBundleDisplayName": name,
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "LSMinimumSystemVersion": "12.0",
            "LSUIElement": False,
            "NSHighResolutionCapable": True,
        },
    )
