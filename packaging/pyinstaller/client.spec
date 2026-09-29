from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import collect_submodules


root = Path(SPECPATH).parents[1]
name = "MTGA Constructed Testing"
def _package_version() -> str:
    if os.environ.get("APP_VERSION"):
        return os.environ["APP_VERSION"]
    import tomllib
    with (root / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


version = _package_version()
hidden = collect_submodules("keyring.backends")

# Signing is done here rather than over the finished bundle because a
# frozen app is hundreds of nested dylibs that have to be signed
# innermost-first. PyInstaller walks them in that order, and adds the
# hardened runtime and a secure timestamp that notarization requires.
# Empty means ad-hoc, which is what local and unsigned CI builds get.
signing_identity = os.environ.get("APPLE_SIGNING_IDENTITY") or None
entitlements = str(root / "packaging/macos/entitlements.plist") if signing_identity else None
runtime_hook = root / "build/default_server.py"
runtime_hook.parent.mkdir(parents=True, exist_ok=True)
runtime_hook.write_text(
    "import os\n"
    f"os.environ.setdefault('CTA_DEFAULT_SERVER_URL', {os.environ.get('CTA_DEFAULT_SERVER_URL', '')!r})\n",
    encoding="utf-8",
)

icon_png = root / "src/cta_client/desktop/icon.png"
icon_svg = root / "src/cta_client/desktop/icon.svg"
icon_ico = root / "packaging/icons/icon.ico"
icon_icns = root / "packaging/icons/icon.icns"
datas = [
    (str(root / "LICENSE"), "."),
    (str(root / "NOTICE"), "."),
]
if icon_png.is_file():
    datas.append((str(icon_png), "."))
if icon_svg.is_file():
    datas.append((str(icon_svg), "."))

analysis = Analysis(
    [str(root / "src/cta_client/desktop/app.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hidden + ["PySide6.QtSvg", "PySide6.QtNetwork"],
    runtime_hooks=[str(runtime_hook)],
    excludes=["cta_server", "numpy", "scipy", "pytest"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe_kwargs = {}
if sys.platform == "win32" and icon_ico.is_file():
    exe_kwargs["icon"] = str(icon_ico)
elif sys.platform == "darwin" and icon_icns.is_file():
    exe_kwargs["icon"] = str(icon_icns)
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
    codesign_identity=signing_identity,
    entitlements_file=entitlements,
    **exe_kwargs,
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
    bundle_kwargs = {}
    if icon_icns.is_file():
        bundle_kwargs["icon"] = str(icon_icns)
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
        **bundle_kwargs,
    )
