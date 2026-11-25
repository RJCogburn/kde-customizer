"""Background removal for rendered icons: the rembg chain (in-process / external Python) and the built-in cutter."""
import io
import os
import stat

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from kdecustomizer import imagegen, signature, spec  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_lookup(monkeypatch, tmp_path):
    imagegen._found_python.clear()
    monkeypatch.setenv("U2NET_HOME", str(tmp_path / "u2net"))
    monkeypatch.delenv("KDEC_REMBG_PYTHON", raising=False)
    monkeypatch.setattr(imagegen, "_ai_pythons", lambda: [])
    yield
    imagegen._found_python.clear()


def render() -> bytes:
    """A light backdrop (with a gradient and a soft shadow) and a light-gray metal panel whose right edge
    fades softly into it — what the old cutter ate — plus a separate small badge."""
    w = h = 256
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            v = 246 - y // 32                                  # gentle vertical gradient
            px[x, y] = (v, v, v)
    shadow = Image.new("L", (w, h), 0)                        # soft (blurred) floor shadow, like renders have
    ImageDraw.Draw(shadow).ellipse((50, 200, 170, 225), fill=60)
    from PIL import ImageFilter
    im.paste((150, 150, 150), (0, 0), shadow.filter(ImageFilter.GaussianBlur(8)))
    d = ImageDraw.Draw(im)
    d.rectangle((60, 40, 160, 200), fill=(198, 203, 210))     # light metal panel
    d.rectangle((60, 40, 66, 200), fill=(40, 44, 52))         # dark spine on its left only
    for i in range(8):                                        # right edge fades into the backdrop
        g = 198 + i * 5
        d.line((161 + i, 40, 161 + i, 200), fill=(g, g + 2, min(255, g + 4)))
    d.ellipse((196, 60, 220, 84), fill=(40, 150, 230))        # detached badge
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def test_builtin_keeps_light_metal_and_detached_parts(monkeypatch):
    monkeypatch.setattr(imagegen, "remove_background", lambda d: (None, "off"))
    icon = imagegen.to_icon(render(), size=256)
    a = icon.getchannel("A")
    w, h = icon.size
    alpha = a.tobytes()
    opaque = sum(1 for v in alpha if v > 200)
    # the panel (100x160) + spine + badge survive: well over a third of the squared icon
    assert opaque > 0.35 * w * h
    # the detached blue badge survives as its own piece
    rgba = icon.tobytes()
    blue = sum(1 for i in range(0, len(rgba), 4) if rgba[i + 3] > 200 and rgba[i + 2] > 180 and rgba[i] < 90)
    assert blue > 100
    # corners are background
    assert a.getpixel((0, 0)) == 0 and a.getpixel((w - 1, h - 1)) == 0


def fake_python(tmp_path, out_png: bytes, ok_import=True):
    """An executable that behaves like `python -c '<rembg code>'`: prints a prepared RGBA PNG."""
    (tmp_path / "cut.png").write_bytes(out_png)
    script = tmp_path / "python3"
    script.write_text(f"#!/bin/sh\n{'exit 0' if not ok_import else ''}\n"
                      f'case "$2" in *"import rembg, onnxruntime"*) exit 0 ;; esac\n'
                      f"cat >/dev/null; cat '{tmp_path / 'cut.png'}'\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def rgba_png() -> bytes:
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle((16, 16, 48, 48), fill=(200, 205, 210, 255))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def test_external_rembg_python_is_used(tmp_path, monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "rembg", None)       # not importable here
    py = fake_python(tmp_path, rgba_png())
    monkeypatch.setenv("KDEC_REMBG_PYTHON", py)
    cut, how = imagegen.remove_background(render())
    assert cut == rgba_png() and py in how
    assert py in imagegen.cutout_method()
    logs = []
    icon = imagegen.to_icon(render(), size=128, log=logs.append)
    assert icon.size == (128, 128) and "rembg" in logs[0]
    assert imagegen._rembg_cache().read_text() == py                   # remembered for next time


def test_no_rembg_anywhere(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "rembg", None)
    cut, how = imagegen.remove_background(render())
    assert cut is None and "no rembg" in how
    assert imagegen.cutout_method().startswith("built-in")


def test_best_downloaded_model(tmp_path):
    home = tmp_path / "u2net"
    home.mkdir()
    assert imagegen._rembg_model() == "u2net"
    (home / "isnet-general-use.onnx").write_bytes(b"x")
    assert imagegen._rembg_model() == "isnet-general-use"


def test_raw_kept_and_recut(tmp_path, monkeypatch):
    monkeypatch.setattr(imagegen, "remove_background", lambda d: (None, "off"))
    sig = tmp_path / "sig"
    signature.save_raw(sig, "folder", render())
    signature.save_raw(sig, "user-trash", render())
    (sig / "svg").mkdir(parents=True)
    (sig / "svg" / "user-trash.svg").write_text("<svg/>")              # a vector icon is never overwritten
    done = signature.recut(sig)
    assert done == ["folder"]
    assert (sig / "png" / "folder.png").is_file() and (sig / "svg" / "user-trash.svg").is_file()
    signature.clear(sig, ["folder"])
    assert not list((sig / "raw").glob("folder.*"))


def test_cli_recut(tmp_path, monkeypatch, capsys):
    from kdecustomizer import cli
    monkeypatch.setattr(imagegen, "remove_background", lambda d: (None, "off"))
    t = spec.Theme(name="R")
    spec.save(t, tmp_path / "r.toml")
    sig = tmp_path / "r-icons"
    signature.save_raw(sig, "folder", render())
    assert cli.main(["icons", str(tmp_path / "r.toml"), "--recut"]) == 0
    assert (sig / "png" / "folder.png").is_file()
    t = spec.load(tmp_path / "r.toml")
    assert t.iconset.generate and t.iconset.signature == "image"
