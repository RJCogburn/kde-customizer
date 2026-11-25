"""snapshot.take(): fake a desktop's config files, read them back into a spec."""
from pathlib import Path

import pytest

from kdecustomizer import build, snapshot, spec
from kdecustomizer.generators import colors


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def config(isolated_home):
    return isolated_home / ".config"


def test_parse_kconfig_nested_groups_and_flags():
    c = snapshot.parse_kconfig("[A]\nk=1\n[A][B]\nkey[$e]=$HOME/x\n# comment\n[C]\n")
    assert c[("A",)] == {"k": "1"}
    assert c[("A", "B")] == {"key": "$HOME/x"}
    assert c[("C",)] == {}


def test_cascade_user_wins_over_defaults(config, tmp_path, monkeypatch):
    defaults = tmp_path / "kdedefaults"
    monkeypatch.setenv("XDG_CONFIG_DIRS", f"{defaults}:{tmp_path / 'etc-xdg'}")
    write(tmp_path / "etc-xdg/kcminputrc", "[Mouse]\ncursorTheme=from-etc\nsize=24\n")
    write(defaults / "kcminputrc", "[Mouse]\ncursorTheme=from-lnf\n")
    assert snapshot.read_config("kcminputrc")[("Mouse",)] == {"cursorTheme": "from-lnf", "size": "24"}
    write(config / "kcminputrc", "[Mouse]\ncursorTheme=from-user\n")
    assert snapshot.read_config("kcminputrc")[("Mouse",)]["cursorTheme"] == "from-user"


def test_palette_round_trips_through_our_own_scheme(config, midnight):
    write(config / "kdeglobals", colors.generate(midnight))
    got = snapshot.take("X").palette
    want = midnight.palette.resolved()
    for f in ("background", "surface", "foreground", "accent", "positive", "neutral", "negative", "visited"):
        assert getattr(got, f) == getattr(want, f), f
    # and so the regenerated scheme is identical
    t = snapshot.take(midnight.name)
    assert colors.generate(t) == colors.generate(midnight)


def test_accent_color_override(config, midnight):
    write(config / "kdeglobals", colors.generate(midnight) + "\n[General]\nAccentColor=255,0,128\n")
    assert snapshot.take("X").palette.accent == "#ff0080"


def test_names_fonts_and_buttons(config):
    write(config / "kdeglobals", "[Icons]\nTheme=Papirus-Dark\n[KDE]\nwidgetStyle=Fusion\n"
                                 "[General]\nfont=Inter,10.5,-1,5,400,0,0,0,0,0\nfixed=Hack,9,-1\n"
                                 "[WM]\nactiveFont=Inter,11,-1,5,700\n")
    write(config / "kcminputrc", "[Mouse]\ncursorTheme=Bibata\n")
    write(config / "plasmarc", "[Theme]\nname=Sweet\n")
    write(config / "ksplashrc", "[KSplash]\nEngine=none\nTheme=x\n")
    write(config / "kwinrc", "[org.kde.kdecoration2]\nlibrary=org.kde.kwin.aurorae\n"
                             "theme=__aurorae__svg__Sweet\nButtonsOnLeft=XIA\nButtonsOnRight=\n")
    t = snapshot.take("My Desk")
    assert (t.icons, t.cursors, t.widget_style, t.plasma_style, t.splash) == \
        ("Papirus-Dark", "Bibata", "Fusion", "Sweet", "None")
    assert (t.decoration.library, t.decoration.theme) == ("org.kde.kwin.aurorae", "__aurorae__svg__Sweet")
    assert (t.decoration.buttons_left, t.decoration.buttons_right) == ("XIA", "")
    assert (t.fonts.general, t.fonts.fixed, t.fonts.window_title) == ("Inter,10.5", "Hack,9", "Inter,11")
    assert t.id == "org.kdecustomizer.mydesk"
    assert not (t.plasma.generate or t.iconset.generate or t.cursorset.generate or t.decoration.generate)


def test_generated_parts_come_back_as_generate(midnight, tmp_path, cursor_base, isolated_home, config):
    """Install a kde-customizer build into the fake home, then snapshot it."""
    t = midnight
    t.plasma.generate = t.cursorset.generate = t.decoration.generate = t.splash_screen.generate = True
    out = build.build(t, tmp_path / "b")
    data = isolated_home / ".local/share"
    import shutil
    shutil.copytree(out / "plasma" / t.slug, data / "plasma/desktoptheme" / t.slug)
    shutil.copytree(out / "cursors" / t.cursors_name, data / "icons" / t.cursors_name, symlinks=True)
    shutil.copytree(out / "aurorae" / t.decoration_name, data / "aurorae/themes" / t.decoration_name)
    shutil.copytree(out / "lookandfeel" / t.id, data / "plasma/look-and-feel" / t.id)
    write(config / "kdeglobals", colors.generate(t) + f"\n[KDE]\nLookAndFeelPackage={t.id}\n")
    write(config / "plasmarc", f"[Theme]\nname={t.slug}\n")
    write(config / "kcminputrc", f"[Mouse]\ncursorTheme={t.cursors_name}\n")
    write(config / "ksplashrc", f"[KSplash]\nTheme={t.id}\n")
    lib, deco = t.decoration_kwin
    write(config / "kwinrc", f"[org.kde.kdecoration2]\nlibrary={lib}\ntheme={deco}\n")
    s = snapshot.take("Again")
    assert s.plasma.generate and s.decoration.generate and s.splash_screen.generate
    assert s.cursorset.generate and s.cursorset.base == "breeze_cursors" and s.cursors == "breeze_cursors"
    assert s.decoration.theme == spec.Decoration.theme          # generated name not copied as an installed one
    assert "Plasma style" in snapshot.summary(s)


def test_panels_and_wallpaper(config, tmp_path):
    pkg = tmp_path / "Next"
    (pkg / "contents/images").mkdir(parents=True)
    (pkg / "contents/images/small.png").write_bytes(b"x")
    (pkg / "contents/images/big.png").write_bytes(b"x" * 100)
    write(config / "plasma-org.kde.plasma.desktop-appletsrc", f"""
[Containments][1]
activityId=abc
lastScreen=1
plugin=org.kde.plasma.folder
wallpaperplugin=org.kde.image

[Containments][1][Wallpaper][org.kde.image][General]
Image=file:///nonexistent.png

[Containments][2]
activityId=abc
lastScreen=0
plugin=org.kde.plasma.folder
wallpaperplugin=org.kde.image

[Containments][2][Wallpaper][org.kde.image][General]
Image=file://{pkg}/

[Containments][10]
lastScreen=0
location=3
plugin=org.kde.panel

[Containments][10][General]
AppletOrder=12;11

[Containments][10][Applets][11]
plugin=org.kde.plasma.digitalclock

[Containments][10][Applets][12]
plugin=org.kde.plasma.kickoff

[Containments][20]
lastScreen=1
location=4
plugin=org.kde.panel

[Containments][20][Applets][21]
plugin=org.kde.plasma.icontasks
""")
    write(config / "plasmashellrc", """
[PlasmaViews][Panel 10]
alignment=1
floating=0
panelLengthMode=1

[PlasmaViews][Panel 10][Defaults]
thickness=36
""")
    t = snapshot.take("X")
    assert t.wallpaper == str(pkg / "contents/images/big.png")
    assert len(t.panels) == 1                       # only screen 0's
    p = t.panels[0]
    assert (p.location, p.height, p.floating, p.alignment, p.length_mode) == ("top", 36, False, "left", "fit")
    assert p.widgets == ["org.kde.plasma.kickoff", "org.kde.plasma.digitalclock"]


def test_empty_desktop_gives_defaults():
    t = snapshot.take("Blank")
    assert t.palette == spec.Palette()
    assert len(t.panels) == 1 and t.wallpaper == ""


def test_cli_snapshot(config, tmp_path, capsys):
    from kdecustomizer import cli
    out = tmp_path / "desk.toml"
    assert cli.main(["snapshot", str(out)]) == 0
    assert spec.load(out).name == "Desk"
    assert cli.main(["snapshot", str(out)]) == 1                 # exists: needs --force
    assert cli.main(["snapshot", str(out), "--force", "--name", "Other"]) == 0
    assert spec.load(out).name == "Other"
