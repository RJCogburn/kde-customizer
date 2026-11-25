import os
import struct
from dataclasses import replace

import pytest

from conftest import SVG, qtsvg
from kdecustomizer import cursorset, spec


def theme(fill="background") -> spec.Theme:
    t = spec.Theme(name="Mid")
    t.palette = spec.Palette(background="#14151f", foreground="#e4e4f0", accent="#8b7cf6")
    t.cursorset = replace(t.cursorset, generate=True, fill=fill)
    return t


def test_recolor_maps_body_outline_accent_and_keeps_shadow_black():
    c = cursorset.colors(theme())
    out = cursorset.recolor_svg(SVG, c)
    assert f'fill="{c["body"]}"' in out.split(">", 1)[0]        # root fill = body for unfilled shapes
    assert 'fill="#000"' in out                                # blurred shadow pinned black
    assert c["outline"] in out and c["accent"] in out
    assert "#fff" not in out and "#46a7ac" not in out


@pytest.mark.parametrize("fill", spec.CursorSet.FILLS)
def test_fills_pick_contrasting_outline(fill):
    c = cursorset.colors(theme(fill))
    assert c["body"] != c["outline"]
    if fill == "background":
        assert (c["body"], c["outline"]) == ("#14151f", "#e4e4f0")
    if fill == "foreground":
        assert (c["body"], c["outline"]) == ("#e4e4f0", "#14151f")


def fake_render(svg: bytes, w: int, h: int) -> bytes:
    return b"\x01\x02\x03\x04" * (w * h)


def test_xcursor_layout():
    frames = [{"filename": "a.svg", "hotspot_x": 4, "hotspot_y": 4, "nominal_size": 24, "delay": 30},
              {"filename": "b.svg", "hotspot_x": 4, "hotspot_y": 4, "nominal_size": 24, "delay": 30}]
    data = cursorset.xcursor(frames, {"a.svg": SVG, "b.svg": SVG}, fake_render)
    magic, header, version, n = struct.unpack("<4sIII", data[:16])
    assert (magic, header, version) == (b"Xcur", 16, 0x10000)
    assert n == 2 * len(cursorset.XCURSOR_SIZES)
    for i in range(n):
        typ, size, pos = struct.unpack("<III", data[16 + 12 * i: 28 + 12 * i])
        hdr = struct.unpack("<9I", data[pos: pos + 36])
        assert typ == 0xFFFD0002 and hdr[1] == typ and hdr[2] == size
        w, h, xhot, yhot, delay = hdr[4:9]
        assert w == round(32 * size / 24) and xhot == int(4 * size / 24) and delay == 30
        assert xhot < w and yhot < h


def test_build_theme(cursor_base, tmp_path, monkeypatch):
    monkeypatch.setattr(cursorset, "_renderer", lambda: fake_render)
    t = theme()
    out = cursorset.build(t, tmp_path)
    assert out.name == "Mid-Cursors"
    assert "Inherits=breeze_cursors" in (out / "index.theme").read_text()
    assert (out / "cursors_scalable/wait/wait-02.svg").is_file()
    assert os.readlink(out / "cursors_scalable/arrow") == "default"
    assert os.readlink(out / "cursors/arrow") == "default"
    assert (out / "cursors/default").read_bytes()[:4] == b"Xcur"
    assert "#14151f" in (out / "cursors_scalable/default/default.svg").read_text()


def test_without_qt_the_base_xcursors_are_copied(cursor_base, tmp_path, monkeypatch):
    (cursor_base / "cursors" / "default").write_bytes(b"Xcur-original")
    monkeypatch.setattr(cursorset, "_renderer", lambda: None)
    out = cursorset.build(theme(), tmp_path)
    assert (out / "cursors/default").read_bytes() == b"Xcur-original"
    assert not (out / "cursors/wait").exists()          # base has no Xcursor for it: nothing to copy


def test_missing_base_raises(tmp_path):
    t = theme()
    t.cursorset.base = "nope"
    assert not cursorset.base_available(t)
    with pytest.raises(ValueError, match="nope"):
        cursorset.build(t, tmp_path)


def test_scalable_themes_lists_only_svg_themes(cursor_base, tmp_path):
    (tmp_path / "usr-share/icons/xonly/cursors").mkdir(parents=True)
    assert cursorset.scalable_themes() == ["breeze_cursors"]


@pytest.mark.skipif(not qtsvg(), reason="needs PySide6 with QtSvg to render")
def test_real_render(cursor_base, tmp_path):
    out = cursorset.build(theme(), tmp_path)
    data = (out / "cursors/default").read_bytes()
    _, _, _, n = struct.unpack("<4sIII", data[:16])
    _, size, pos = struct.unpack("<III", data[16:28])
    w, h = struct.unpack("<9I", data[pos: pos + 36])[4:6]
    pixels = data[pos + 36: pos + 36 + w * h * 4]
    assert any(pixels[i + 3] for i in range(0, len(pixels), 4))   # something opaque was drawn
