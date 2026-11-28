"""The theme's wallpaper reaches Plasma as a wallpaper package the Global Theme names, and the Global Theme has its
own preview pictures. Without these, Plasma fell back to Breeze's "Next" wallpaper whenever it made a new desktop
(layout reset, System Settings with "Desktop and window layout"), and System Settings showed Breeze's pictures."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import EXAMPLE, have, pyside6
from kdecustomizer import build, previews, spec
from test_own_icons_and_more import png


@pytest.fixture
def themed(tmp_path):
    t = spec.load(EXAMPLE)
    t.wallpaper = str(tmp_path / "my wall.png")
    Path(t.wallpaper).write_bytes(png(64, 36))
    return t


def test_image_size_reads_headers(tmp_path):
    (tmp_path / "a.png").write_bytes(png(640, 360))
    assert previews.image_size(tmp_path / "a.png") == (640, 360)
    assert previews.wallpaper_file_name(tmp_path / "a.png") == "640x360.png"
    (tmp_path / "x.jpg").write_bytes(b"not an image")
    assert previews.image_size(tmp_path / "x.jpg") is None
    assert previews.wallpaper_file_name(tmp_path / "x.jpg") == "1920x1080.jpg"     # fallback name
    if pyside6():
        from PySide6.QtGui import QColor, QImage
        for fmt in ("JPEG", "WEBP"):
            img = QImage(321, 123, QImage.Format_RGB32)
            img.fill(QColor("#123456"))
            f = tmp_path / f"b.{fmt.lower()}"
            if img.save(str(f), fmt):
                assert previews.image_size(f) == (321, 123), fmt


def test_global_theme_names_the_wallpaper_package(themed, tmp_path):
    out = build.build(themed, tmp_path / "b")
    defaults = (out / "lookandfeel" / themed.id / "contents/defaults").read_text()
    assert f"[Wallpaper]\nImage={themed.slug}\n" in defaults
    sh = (out / "install.sh").read_text()
    assert f'plasma-apply-wallpaperimage "$DATA/wallpapers/{themed.slug}"' in sh
    themed.wallpaper = ""
    assert "[Wallpaper]" not in (build.build(themed, tmp_path / "c") / "lookandfeel" / themed.id
                                 / "contents/defaults").read_text()


def test_variant_points_at_the_installed_package(themed, tmp_path):
    themed.light_dark.auto = True
    out = build.build(themed, tmp_path / "b")
    from kdecustomizer import variant
    vt = variant.opposite(themed)
    d = (out / "variant" / vt.slug / "lookandfeel" / vt.id / "contents/defaults").read_text()
    assert f"Image={themed.slug}\n" in d and f"Image={vt.slug}\n" not in d


@pytest.mark.skipif(not pyside6(), reason="needs PySide6")
def test_global_theme_has_its_own_previews(qapp, themed, tmp_path):
    from PySide6.QtGui import QImage
    out = build.build(themed, tmp_path / "b")
    pv = out / "lookandfeel" / themed.id / "contents/previews"
    for name, size in previews.SIZES.items():
        img = QImage(str(pv / name))
        assert (img.width(), img.height()) == size, name


@pytest.mark.skipif(not (have("kwriteconfig6") and have("kreadconfig6")), reason="needs KConfig tools")
def test_install_makes_a_real_wallpaper_package(themed, tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "calls"
    for c in ["plasma-apply-colorscheme", "plasma-apply-cursortheme", "plasma-apply-desktoptheme",
              "plasma-apply-wallpaperimage", "plasma-apply-lookandfeel", "kpackagetool6", "qdbus6", "dbus-send",
              "pkexec", "systemctl"]:
        (bin_ / c).write_text(f'#!/bin/sh\necho "{c} $*" >> {log}\n')
        (bin_ / c).chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}")
    out = build.build(themed, tmp_path / "b")
    r = subprocess.run(["bash", str(out / "install.sh"), "--no-login", "--no-boot"], env=env, capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    pkg = Path(os.environ["XDG_DATA_HOME"]) / "wallpapers" / themed.slug
    meta = json.loads((pkg / "metadata.json").read_text())
    assert meta["KPlugin"]["Id"] == themed.slug and meta["KPackageStructure"] == "Wallpaper/Images"
    assert [p.name for p in (pkg / "contents/images").iterdir()] == ["64x36.png"]
    assert f"plasma-apply-wallpaperimage {pkg}" in log.read_text()
    # an older install left a plain image there: replaced by the package
    (pkg / "old.png").write_bytes(b"x")
    subprocess.run(["bash", str(out / "install.sh"), "--no-login", "--no-boot"], env=env, capture_output=True)
    assert not (pkg / "old.png").exists()
