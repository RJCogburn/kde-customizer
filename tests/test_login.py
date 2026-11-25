"""login/apply.sh + greeter.sh through their test hooks (no root): everything lands under a temp root."""
import subprocess
from dataclasses import replace

import pytest

from conftest import have
from kdecustomizer import build

pytestmark = pytest.mark.skipif(not have("kwriteconfig6"), reason="needs kwriteconfig6 (KF6 KConfig)")


def ini(path):
    from kdecustomizer.snapshot import parse_kconfig
    return parse_kconfig(path.read_text())


@pytest.fixture
def out(midnight, tmp_path, cursor_base):
    wall = tmp_path / "wall.png"
    wall.write_bytes(b"\x89PNG")
    t = replace(midnight, wallpaper=str(wall))
    t.cursorset = replace(t.cursorset, generate=True)
    t.login_screen = replace(t.login_screen, generate=True)
    t.fonts = replace(t.fonts, general="Inter,10")
    return build.build(t, tmp_path / "b")


def run(out, tmp_path, dm, breeze=True):
    root, home = tmp_path / f"root-{dm}", tmp_path / f"greeter-{dm}"
    home.mkdir()
    if breeze:
        (root / "usr/share/sddm/themes/breeze").mkdir(parents=True)
    env = {"PATH": "/usr/bin:/bin", "KDEC_LOGIN_ROOT": str(root), "KDEC_LOGIN_HOME": str(home),
           "KDEC_LOGIN_DM": dm}
    r = subprocess.run(["bash", str(out / "login/apply.sh"), str(out)], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return root, home, r.stdout


def test_greeter_home_gets_config_and_assets(out, tmp_path):
    _, home, _ = run(out, tmp_path, "plasmalogin")
    assert ini(home / ".config/plasmarc")[("Theme",)]["name"] == "Midnight"
    assert ini(home / ".config/kcminputrc")[("Mouse",)]["cursorTheme"] == "Midnight-Cursors"
    g = ini(home / ".config/kdeglobals")
    assert g[("Colors:Window",)]["BackgroundNormal"] == "20,21,31"
    assert g[("General",)]["font"].startswith("Inter,10,")
    assert (home / ".local/share/icons/Midnight-Cursors/index.theme").is_file()
    assert (home / ".local/share/plasma/desktoptheme/Midnight/metadata.json").is_file()
    assert (home / "wallpapers/wall.png").is_file()


def test_merge_keeps_other_greeter_settings(out, tmp_path):
    home = tmp_path / "greeter-plasmalogin"
    (home / ".config").mkdir(parents=True)
    (home / ".config/kcminputrc").write_text("[Keyboard]\nNumLock=0\n")
    (home / ".cache").mkdir()
    (home / ".cache/old").write_text("x")
    root = tmp_path / "root-plasmalogin"
    env = {"PATH": "/usr/bin:/bin", "KDEC_LOGIN_ROOT": str(root), "KDEC_LOGIN_HOME": str(home),
           "KDEC_LOGIN_DM": "plasmalogin"}
    subprocess.run(["bash", str(out / "login/apply.sh"), str(out)], env=env, check=True, capture_output=True)
    rc = ini(home / ".config/kcminputrc")
    assert rc[("Keyboard",)]["NumLock"] == "0" and rc[("Mouse",)]["cursorTheme"] == "Midnight-Cursors"
    assert not (home / ".cache").exists()


def test_plasma_login_conf(out, tmp_path):
    root, home, msg = run(out, tmp_path, "plasmalogin")
    conf = ini(root / "etc/plasmalogin.conf")
    assert conf[("Greeter",)] == {"ShowClock": "true", "WallpaperPluginId": "org.kde.image"}
    assert conf[("Greeter", "Wallpaper", "org.kde.image", "General")]["Image"] == f"file://{home}/wallpapers/wall.png"
    assert "(plasmalogin)" in msg


def test_sddm_conf(out, tmp_path):
    root, _, msg = run(out, tmp_path, "sddm")
    kde = ini(root / "etc/sddm.conf.d/kde_settings.conf")[("Theme",)]
    assert kde["Current"] == "breeze" and kde["CursorTheme"] == "Midnight-Cursors"
    assert kde["Font"].startswith("Inter,10,")
    user = ini(root / "usr/share/sddm/themes/breeze/theme.conf.user")[("General",)]
    assert user == {"background": "/usr/share/sddm/themes/breeze/kde-customizer-background.png",
                    "color": "#14151f", "showClock": "true", "type": "image"}
    assert (root / "usr/share/sddm/themes/breeze/kde-customizer-background.png").is_file()
    assert "(sddm)" in msg


def test_sddm_without_breeze_still_sets_cursor(out, tmp_path):
    root, _, msg = run(out, tmp_path, "sddm", breeze=False)
    kde = ini(root / "etc/sddm.conf.d/kde_settings.conf")[("Theme",)]
    assert "Current" not in kde and kde["CursorTheme"] == "Midnight-Cursors"
    assert "not installed" in msg


def test_color_background_without_wallpaper(midnight, tmp_path):
    t = replace(midnight)
    t.login_screen = replace(t.login_screen, generate=True, clock=False)
    out = build.build(t, tmp_path / "b")
    root, _, _ = run(out, tmp_path, "plasmalogin")
    conf = ini(root / "etc/plasmalogin.conf")
    assert conf[("Greeter",)]["WallpaperPluginId"] == "org.kde.color"
    assert conf[("Greeter",)]["ShowClock"] == "false"
    assert conf[("Greeter", "Wallpaper", "org.kde.color", "General")]["Color"] == "20,21,31"
