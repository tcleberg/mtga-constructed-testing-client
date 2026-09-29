import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cta_client.desktop import resources


def test_icon_file_prefers_png_over_svg(tmp_path, monkeypatch):
    png = tmp_path / "icon.png"
    svg = tmp_path / "icon.svg"
    png.write_bytes(b"png")
    svg.write_text("<svg/>", encoding="utf-8")
    monkeypatch.setattr(resources, "_icon_dirs", lambda: [tmp_path])
    assert resources.icon_file("icon.png", "icon.svg") == png


def test_icon_file_falls_back_to_svg(tmp_path, monkeypatch):
    svg = tmp_path / "icon.svg"
    svg.write_text("<svg/>", encoding="utf-8")
    monkeypatch.setattr(resources, "_icon_dirs", lambda: [tmp_path])
    assert resources.icon_file("icon.png", "icon.svg") == svg


def test_packaged_svg_is_ascii_so_qt_can_load_it():
    """A Latin-1 times sign in a comment made QIcon(icon.svg) fail closed."""
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "src/cta_client/desktop/icon.svg",
        "packaging/icons/icon.svg",
    ):
        raw = (root / relative).read_bytes()
        assert all(byte < 128 for byte in raw), relative


def test_desktop_png_is_present_for_the_tray():
    png = Path(__file__).resolve().parents[1] / "src/cta_client/desktop/icon.png"
    assert png.is_file()
    assert png.stat().st_size > 1000


def test_application_icon_loads_the_png():
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    icon = resources.application_icon()
    assert not icon.isNull()
