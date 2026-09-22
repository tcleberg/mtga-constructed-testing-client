#!/usr/bin/env python3
"""Rasterize packaging/icons/icon.svg into the icns/ico/png set the packagers consume."""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ICONS = ROOT / "packaging/icons"
SVG = ICONS / "icon.svg"
MASTER = ICONS / "icon.png"
ICONSET = ICONS / "icon.iconset"
DESKTOP_PNG = ROOT / "src/cta_client/desktop/icon.png"
RESVG_PREFIX = ROOT / "packaging/scripts/.resvg"

ICONSET_SIZES = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def ensure_resvg() -> Path:
    module = RESVG_PREFIX / "node_modules" / "@resvg" / "resvg-js"
    if not module.is_dir():
        RESVG_PREFIX.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["npm", "install", "--prefix", str(RESVG_PREFIX), "@resvg/resvg-js@3"],
            check=True,
        )
    return RESVG_PREFIX


def rasterize(size: int, dest: Path, prefix: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    script = rf"""
const {{ Resvg }} = require('@resvg/resvg-js');
const {{ readFileSync, writeFileSync }} = require('fs');
const svg = readFileSync({str(SVG)!r});
const png = new Resvg(svg, {{ fitTo: {{ mode: 'width', value: {size} }} }}).render().asPng();
writeFileSync({str(dest)!r}, png);
"""
    subprocess.run(
        ["node", "-e", script],
        check=True,
        cwd=str(prefix),
        env={**os.environ, "NODE_PATH": str(prefix / "node_modules")},
    )


def write_ico(dest: Path, images: list[tuple[int, bytes]]) -> None:
    offset = 6 + 16 * len(images)
    entries = bytearray()
    blobs = bytearray()
    for size, data in images:
        stored = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", stored, stored, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    dest.write_bytes(struct.pack("<HHH", 0, 1, len(images)) + entries + blobs)


def main() -> int:
    if not SVG.is_file():
        raise SystemExit(f"missing {SVG}")
    prefix = ensure_resvg()
    rasterize(1024, MASTER, prefix)
    if ICONSET.exists():
        shutil.rmtree(ICONSET)
    ICONSET.mkdir()
    rendered: dict[int, bytes] = {1024: MASTER.read_bytes()}
    for name, size in ICONSET_SIZES:
        if size not in rendered:
            path = ICONSET / name
            rasterize(size, path, prefix)
            rendered[size] = path.read_bytes()
        else:
            (ICONSET / name).write_bytes(rendered[size])
    ico_pngs: list[tuple[int, bytes]] = []
    for size in ICO_SIZES:
        if size not in rendered:
            path = ICONS / f"_ico_{size}.png"
            rasterize(size, path, prefix)
            rendered[size] = path.read_bytes()
            path.unlink()
        ico_pngs.append((size, rendered[size]))
    subprocess.run(
        ["iconutil", "-c", "icns", "-o", str(ICONS / "icon.icns"), str(ICONSET)],
        check=True,
    )
    write_ico(ICONS / "icon.ico", ico_pngs)
    DESKTOP_PNG.write_bytes(rendered[256])
    shutil.rmtree(ICONSET)
    print(f"wrote {ICONS / 'icon.icns'}")
    print(f"wrote {ICONS / 'icon.ico'}")
    print(f"wrote {MASTER}")
    print(f"wrote {DESKTOP_PNG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
