"""Restore points (restore-point.sh, run first by install.sh) and `kdec revert` — in a temp HOME, with the
desktop-touching tools (plasma-apply-*, qdbus6, dbus-send, kquitapp6) replaced by stubs that log their calls."""
import os
import subprocess
from pathlib import Path

import pytest

from conftest import have
from kdecustomizer import build, cli, restorepoints
from kdecustomizer.generators import restore

pytestmark = pytest.mark.skipif(not (have("kwriteconfig6") and have("kreadconfig6")),
                                reason="needs kreadconfig6/kwriteconfig6 (KF6 KConfig)")

STUBS = ["plasma-apply-colorscheme", "plasma-apply-cursortheme", "plasma-apply-desktoptheme",
         "plasma-apply-wallpaperimage", "qdbus6", "dbus-send", "kquitapp6", "plasmashell"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "calls"
    for c in STUBS:
        (bin_ / c).write_text(f'#!/bin/sh\necho "{c} $*" >> {log}\n')
        (bin_ / c).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}:{os.environ['PATH']}")
    conf = Path(os.environ["XDG_CONFIG_HOME"])
    conf.mkdir(parents=True, exist_ok=True)
    return conf, log


def kread(f, g, k):
    return subprocess.run(["kreadconfig6", "--file", f, "--group", g, "--key", k],
                          capture_output=True, text=True).stdout.strip()


def kwrite(f, g, k, v):
    subprocess.run(["kwriteconfig6", "--file", f, "--group", g, "--key", k, v], check=True)


def test_install_takes_a_restore_point_first(midnight, tmp_path):
    out = build.build(midnight, tmp_path / "b")
    script = (out / "install.sh").read_text()
    assert (out / "restore-point.sh").is_file()
    assert script.index("restore-point.sh") < script.index('echo "==> color scheme"')
    subprocess.run(["bash", "-n", str(out / "restore-point.sh")], check=True)


def test_keys_cover_tweaks_and_fonts(midnight):
    midnight.fonts.general = "Inter,10"
    ks = restore.keys(midnight)
    assert ("kdeglobals", ("General",), "font") in ks
    assert ("kwinrc", ("org.kde.kdecoration2",), "ButtonsOnRight") in ks
    for f, groups in midnight.tweaks.items():
        for g, kv in groups.items():
            assert all((f, tuple(g.split("/")), k) in ks for k in kv)
    assert ("kdeglobals", ("General",), "ColorScheme") not in ks      # plasma-apply-colorscheme restores it


def test_round_trip(midnight, tmp_path, env, capsys):
    conf, log = env
    kwrite("kdeglobals", "General", "ColorScheme", "BreezeDark")
    kwrite("kdeglobals", "KDE", "LookAndFeelPackage", "org.kde.breezedark.desktop")
    kwrite("kwinrc", "org.kde.kdecoration2", "ButtonsOnLeft", "MS")
    (conf / "kitty").mkdir()
    (conf / "kitty/kitty.conf").write_text("font_size 11\n")
    (conf / "kdedefaults").mkdir()
    (conf / "kdedefaults/kdeglobals").write_text("[KDE]\nwidgetStyle=Breeze\n")

    out = build.build(midnight, tmp_path / "b")
    subprocess.run(["bash", str(out / "restore-point.sh")], check=True, capture_output=True)

    # what an install changes
    kwrite("kdeglobals", "KDE", "LookAndFeelPackage", midnight.id)
    kwrite("kwinrc", "org.kde.kdecoration2", "ButtonsOnLeft", "M")
    kwrite("kwinrc", "org.kde.kdecoration2", "ButtonsOnRight", "IAX")
    (conf / "kitty/kitty.conf").write_text("font_size 11\n# BEGIN_KDEC_THEME\ninclude x\n# END_KDEC_THEME\n")
    (conf / "gtk-4.0").mkdir()
    (conf / "gtk-4.0/kde-customizer.css").write_text("x")
    (conf / "kdedefaults/kdeglobals").write_text("[KDE]\nwidgetStyle=kvantum\n")

    assert cli.main(["revert", "--list"]) == 0
    assert "before Midnight" in capsys.readouterr().out
    assert cli.main(["revert"]) == 0

    assert kread("kdeglobals", "KDE", "LookAndFeelPackage") == "org.kde.breezedark.desktop"
    assert kread("kwinrc", "org.kde.kdecoration2", "ButtonsOnLeft") == "MS"
    assert kread("kwinrc", "org.kde.kdecoration2", "ButtonsOnRight") == ""       # wasn't set: deleted
    assert (conf / "kitty/kitty.conf").read_text() == "font_size 11\n"
    assert not (conf / "gtk-4.0/kde-customizer.css").exists()
    assert (conf / "kdedefaults/kdeglobals").read_text() == "[KDE]\nwidgetStyle=Breeze\n"
    calls = log.read_text()
    assert "plasma-apply-colorscheme BreezeDark" in calls and "qdbus6 org.kde.KWin /KWin reconfigure" in calls
    assert restorepoints.points() == []                                          # used up: next revert goes further back
    assert cli.main(["revert"]) == 1


def test_layout_keeps_the_panels(midnight, tmp_path, env):
    conf, log = env
    (conf / "plasma-org.kde.plasma.desktop-appletsrc").write_text("[Containments][1]\nplugin=org.kde.panel\n")
    out = build.build(midnight, tmp_path / "b")
    subprocess.run(["bash", str(out / "restore-point.sh"), "--layout"], check=True, capture_output=True)
    (conf / "plasma-org.kde.plasma.desktop-appletsrc").write_text("new layout")
    assert cli.main(["revert"]) == 0
    assert "org.kde.panel" in (conf / "plasma-org.kde.plasma.desktop-appletsrc").read_text()
    calls = log.read_text()
    assert "kquitapp6 plasmashell" in calls and "plasma-apply-wallpaperimage" not in calls


def test_only_the_newest_are_kept(midnight, tmp_path, env):
    root = restorepoints.root()
    for i in range(12):
        d = root / f"20250101-0000{i:02d}-Old"
        d.mkdir(parents=True)
        (d / "restore.sh").write_text("true\n")
    out = build.build(midnight, tmp_path / "b")
    subprocess.run(["bash", str(out / "restore-point.sh")], check=True, capture_output=True)
    pts = restorepoints.points()
    assert len(pts) == restore.KEEP and pts[0].theme == "Midnight"
