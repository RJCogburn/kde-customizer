"""Plymouth boot splash: theme files, the script's callbacks, PNGs, boot/apply.sh via its test hook."""
import configparser
import struct
import subprocess
import zlib
from dataclasses import replace

import pytest

from kdecustomizer import build, spec
from kdecustomizer.generators import bootsplash


def decode_png(data: bytes) -> tuple[int, int, bytes]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat = 8, b""
    w = h = 0
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        crc = struct.unpack(">I", data[pos + 8 + n:pos + 12 + n])[0]
        assert crc == zlib.crc32(kind + body) & 0xFFFFFFFF
        if kind == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            assert (depth, ctype) == (8, 6)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    assert len(raw) == h * (1 + 4 * w)
    return w, h, raw


@pytest.fixture
def theme(midnight):
    t = replace(midnight)
    t.boot_splash = replace(t.boot_splash, generate=True)
    return t


def test_theme_files(theme):
    files = bootsplash.files(theme)
    n = bootsplash.name(theme)
    assert n == "kdec-midnight"
    meta = configparser.ConfigParser()
    meta.read_string(files[f"{n}.plymouth"])
    assert meta["Plymouth Theme"]["ModuleName"] == "script"
    assert meta["script"]["ScriptFile"] == f"/usr/share/plymouth/themes/{n}/{n}.script"
    for img in ("track.png", "fill.png", "entry.png", "bullet.png"):
        w, h, _ = decode_png(files[img])
        assert w > 0 and h > 0


def test_bullet_is_round_and_transparent_outside(theme):
    w, h, raw = decode_png(bootsplash.files(theme)["bullet.png"])
    alpha = lambda x, y: raw[y * (1 + 4 * w) + 1 + 4 * x + 3]   # noqa: E731
    assert alpha(0, 0) == 0 and alpha(w // 2, h // 2) == 255


def test_script_registers_every_callback(theme):
    s = bootsplash.script(theme)
    for cb in ("SetBootProgressFunction", "SetDisplayPasswordFunction", "SetDisplayQuestionFunction",
               "SetDisplayNormalFunction", "SetMessageFunction", "SetHideMessageFunction"):
        assert f"Plymouth.{cb}(" in s, cb
    assert s.count("{") == s.count("}")
    assert '"Midnight"' in s


def test_script_text_is_escaped(theme):
    theme.boot_splash.text = 'Say "hi" \\o/'
    assert r'Image.Text("Say \"hi\" \\o/"' in bootsplash.script(theme)


def test_solid_background(theme):
    theme.boot_splash.background = "solid"
    s = bootsplash.script(theme)
    top = s.split("SetBackgroundTopColor(")[1].split(")")[0]
    assert top == s.split("SetBackgroundBottomColor(")[1].split(")")[0]


def test_apply_installs_files(theme, tmp_path):
    out = build.build(theme, tmp_path / "b")
    root = tmp_path / "root"
    r = subprocess.run(["bash", str(out / "boot/apply.sh"), str(out)], capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "KDEC_BOOT_ROOT": str(root)})
    assert r.returncode == 0, r.stderr
    d = root / "usr/share/plymouth/themes/kdec-midnight"
    assert (d / "kdec-midnight.plymouth").is_file() and (d / "bullet.png").is_file()


def test_install_asks_once_for_both_parts(theme, tmp_path):
    theme.login_screen = replace(theme.login_screen, generate=True)
    sh = (build.build(theme, tmp_path / "b") / "install.sh").read_text()
    assert sh.count("pkexec") == 1
    assert "PARTS+=(login)" in sh and "PARTS+=(boot)" in sh
    assert "--no-boot" in sh and "--no-login" in sh
    subprocess.run(["bash", "-n", "-c", sh], check=True)


def test_no_root_step_without_login_or_boot(midnight, tmp_path):
    t = replace(midnight, login_screen=spec.LoginScreen(generate=False))
    assert "pkexec" not in (build.build(t, tmp_path / "b") / "install.sh").read_text()


def test_background_must_be_known():
    with pytest.raises(ValueError, match="boot_splash"):
        spec.from_dict({"boot_splash": {"background": "video"}})
