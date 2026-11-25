"""[light_dark] auto: the opposite variant, its build/install lines, and the follow hook (follow.sh)."""
import os
import subprocess
from pathlib import Path

import pytest

from conftest import have
from kdecustomizer import build, color, spec, variant
from kdecustomizer.generators import lightdark


@pytest.fixture
def auto(midnight):
    midnight.light_dark.auto = True
    return midnight


def test_opposite_palette_is_readable_and_keeps_hues(midnight):
    v = variant.opposite(midnight)
    p = v.palette
    assert not color.is_dark(p.background) and color.is_dark(midnight.palette.background)
    assert color.contrast(p.foreground, p.background) >= 7
    assert color.contrast(p.foreground, p.surface) >= 4.5
    for c in (p.accent, p.positive, p.neutral, p.negative):
        assert color.contrast(c, p.background) >= 3.0
    assert v.name == "Midnight Light" and v.id == "org.kdecustomizer.midnightlight" and not v.light_dark.auto
    back = variant.opposite(v)                       # and back again: a dark one
    assert color.is_dark(back.palette.background) and back.name == "Midnight Light Dark"


def test_pair_order(midnight):
    light, dark = variant.pair(midnight)
    assert dark is midnight and light.name == "Midnight Light"


def test_spec_round_trip(auto, tmp_path):
    spec.save(auto, tmp_path / "t.toml")
    assert "[light_dark]\nauto = true" in (tmp_path / "t.toml").read_text()
    assert spec.load(tmp_path / "t.toml").light_dark.auto


def test_build_and_install_lines(auto, tmp_path):
    out = build.build(auto, tmp_path / "b")
    v = out / "variant" / "MidnightLight"
    assert (v / "lookandfeel" / "org.kdecustomizer.midnightlight" / "contents/defaults").is_file()
    assert not (v / "install.sh").exists() and not (v / "wallpapers").exists()      # only the parts that switch
    for f in ("follow.sh", "kdec-follow.path", "kdec-follow.service"):
        assert (out / "follow" / f).is_file()
    assert "PathChanged=@CONF@/kdeglobals" in (out / "follow/kdec-follow.path").read_text()
    script = (out / "install.sh").read_text()
    subprocess.run(["bash", "-n", str(out / "install.sh")], check=True)
    assert "--key AutomaticLookAndFeel true" in script
    assert "DefaultLightLookAndFeel org.kdecustomizer.midnightlight" in script
    assert f"DefaultDarkLookAndFeel {auto.id}" in script
    assert script.index("light/dark variant") < script.index("==> applying")
    assert "systemctl --user enable --now kdec-follow.path" in script
    assert "--key widgetStyle kvantum" not in script                          # Kvantum can't follow the switch


def test_without_auto_switching_is_turned_off(midnight, tmp_path):
    script = (build.build(midnight, tmp_path / "b") / "install.sh").read_text()
    assert "--key AutomaticLookAndFeel false" in script
    assert "systemctl --user disable --now kdec-follow.path" in script
    assert not (tmp_path / "b/Midnight/variant").exists()


@pytest.mark.skipif(not (have("kreadconfig6") and have("kwriteconfig6")), reason="needs KF6 KConfig tools")
def test_follow_script_switches_terminals_and_gtk(tmp_path):
    conf = Path(os.environ["XDG_CONFIG_HOME"])
    f = tmp_path / "follow"
    for lnf, tag in [("org.x.light", "LIGHT"), ("org.x.dark", "DARK")]:
        d = f / lnf
        d.mkdir(parents=True)
        (d / "kde-customizer.css").write_text(tag)
        (d / "kitty.conf").write_text(tag)
        (d / "alacritty.toml").write_text(tag)
        (d / "ghostty").write_text(f"X{tag.title()}")
        (d / "konsole").write_text(f"X{tag.title()}.profile")
        (d / "firefox.css").write_text(tag)
    (f / "follow.sh").write_text(lightdark.follow_script())
    for rel, text in [("gtk-4.0/kde-customizer.css", "DARK"), ("kitty/kde-customizer-theme.conf", "DARK"),
                      ("ghostty/config", "font-size = 12\n# BEGIN_KDEC_THEME\ntheme = XDark\n# END_KDEC_THEME\n")]:
        (conf / rel).parent.mkdir(parents=True, exist_ok=True)
        (conf / rel).write_text(text)
    home = Path(os.environ["HOME"])
    ff = home / ".mozilla/firefox"
    (ff / "p1/chrome").mkdir(parents=True)
    (ff / "profiles.ini").write_text("[Profile0]\nPath=p1\nIsRelative=1\n")
    (ff / "p1/chrome/kde-customizer.css").write_text("DARK")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "pkill").write_text(f"#!/bin/sh\necho \"$*\" >> {tmp_path}/signals\n")
    (bin_ / "pkill").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}"}

    def switch(lnf):
        subprocess.run(["kwriteconfig6", "--file", "kdeglobals", "--group", "KDE", "--key", "LookAndFeelPackage", lnf],
                       check=True)
        subprocess.run(["bash", str(f / "follow.sh")], check=True, env=env)

    switch("org.x.light")
    assert (conf / "gtk-4.0/kde-customizer.css").read_text() == "LIGHT"
    assert (conf / "kitty/kde-customizer-theme.conf").read_text() == "LIGHT"
    assert "theme = XLight" in (conf / "ghostty/config").read_text()
    assert not (conf / "alacritty/kde-customizer.toml").exists()          # Alacritty isn't set up: left alone
    konsole = subprocess.run(["kreadconfig6", "--file", "konsolerc", "--group", "Desktop Entry", "--key",
                              "DefaultProfile"], capture_output=True, text=True).stdout.strip()
    assert konsole == "XLight.profile"
    assert (tmp_path / "signals").read_text().count("USR1") == 1
    assert (ff / "p1/chrome/kde-customizer.css").read_text() == "LIGHT"
    switch("org.x.light")                                                 # nothing changed: kitty not poked again
    assert (tmp_path / "signals").read_text().count("USR1") == 1
    switch("org.kde.breeze.desktop")                                      # not ours: nothing touched
    assert (conf / "gtk-4.0/kde-customizer.css").read_text() == "LIGHT"
    switch("org.x.dark")
    assert (conf / "kitty/kde-customizer-theme.conf").read_text() == "DARK"
    assert "theme = XDark" in (conf / "ghostty/config").read_text()
