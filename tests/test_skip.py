"""install.sh --no-… options: a part skipped this time is left exactly as it is (not undone), the rest installs.
Runs the whole script in a temp HOME with the desktop-touching tools replaced by stubs that log their calls."""
import os
import subprocess
from pathlib import Path

import pytest

from conftest import have
from kdecustomizer import build

pytestmark = pytest.mark.skipif(not (have("kwriteconfig6") and have("kreadconfig6")),
                                reason="needs kreadconfig6/kwriteconfig6 (KF6 KConfig)")

STUBS = ["plasma-apply-colorscheme", "plasma-apply-cursortheme", "plasma-apply-desktoptheme",
         "plasma-apply-wallpaperimage", "plasma-apply-lookandfeel", "kpackagetool6", "qdbus6", "dbus-send",
         "kquitapp6", "plasmashell", "pkexec", "systemctl", "code", "flatpak"]


@pytest.fixture
def env(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "calls"
    log.write_text("")
    for c in STUBS:
        (bin_ / c).write_text(f'#!/bin/sh\necho "{c} $*" >> {log}\nexit 0\n')
        (bin_ / c).chmod(0o755)
    (bin_ / "getent").write_text("#!/bin/sh\nexit 0\n")      # "a greeter user exists"
    (bin_ / "getent").chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}")
    conf = Path(os.environ["XDG_CONFIG_HOME"])
    data = Path(os.environ["XDG_DATA_HOME"])
    (conf / "kitty").mkdir(parents=True)
    (conf / "kitty/kitty.conf").write_text("font_size 11\n")
    return env, conf, data, log


def kread(f, g, k):
    return subprocess.run(["kreadconfig6", "--file", f, "--group", g, "--key", k],
                          capture_output=True, text=True).stdout.strip()


def install(midnight, tmp_path, env, *args):
    e, *_ = env
    midnight.wallpaper = str(tmp_path / "wall.png")
    Path(midnight.wallpaper).write_bytes(b"\x89PNG\r\n\x1a\n")
    midnight.apps.vscode = True
    out = build.build(midnight, tmp_path / "b")
    r = subprocess.run(["bash", str(out / "install.sh"), *args], env=e, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_every_option_is_in_the_usage_and_parsed(midnight, tmp_path):
    sh = (build.build(midnight, tmp_path / "b") / "install.sh").read_text()
    for var, flag, _ in build.SKIP_PARTS.values():
        assert f"#   {flag}" in sh and f"{flag}) {var}=0 ;;" in sh
    assert build.skip_args(["gtk", "boot"]) == ["--no-gtk", "--no-boot"]


def test_skipped_parts_are_left_alone(midnight, tmp_path, env):
    _, conf, data, log = env
    out = install(midnight, tmp_path, env, *build.skip_args(build.SKIP_PARTS))
    calls = log.read_text()
    # skipped
    assert not (conf / "gtk-4.0/kde-customizer.css").exists()
    assert (conf / "kitty/kitty.conf").read_text() == "font_size 11\n"
    assert "plasma-apply-wallpaperimage" not in calls and not (data / "wallpapers" / midnight.slug).exists()
    assert "code --install-extension" not in calls
    assert "pkexec" not in calls
    assert kread("kwinrc", "Effect-blur", "BlurStrength") == ""          # the theme's own [tweaks]
    assert "skipped (--no-gtk)" in out and "skipped (--no-login)" in out
    # still installed: the desktop itself, and settings that come from the spec (fonts)
    assert (data / "color-schemes" / f"{midnight.slug}.colors").is_file()
    assert "plasma-apply-lookandfeel -a" in calls
    assert "JetBrains Mono" in kread("kdeglobals", "General", "fixed")


def test_without_options_everything_installs(midnight, tmp_path, env):
    """Also the login-screen check with both greeter users present (the getent stub says yes to both)."""
    _, conf, _, log = env
    install(midnight, tmp_path, env, "--no-boot")
    calls = log.read_text()
    assert (conf / "gtk-4.0/kde-customizer.css").is_file()
    assert "BEGIN_KDEC_THEME" in (conf / "kitty/kitty.conf").read_text()
    assert "plasma-apply-wallpaperimage" in calls
    assert "code --install-extension" in calls
    assert "pkexec" in calls                                               # login screen changed: one prompt
    assert kread("kwinrc", "Effect-blur", "BlurStrength") == "8"
