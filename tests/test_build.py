"""build.build(): the whole output tree, install.sh, portability."""
import subprocess
import tarfile
from dataclasses import replace

import pytest

from conftest import ROOT, have
from kdecustomizer import build, spec


def everything(theme: spec.Theme, wallpaper) -> spec.Theme:
    t = replace(theme)
    t.wallpaper = str(wallpaper)
    t.plasma = replace(t.plasma, generate=True, radius=12)
    t.cursorset = replace(t.cursorset, generate=True)
    t.widgets = replace(t.widgets, generate=True)
    t.decoration = replace(t.decoration, generate=True)
    t.splash_screen = replace(t.splash_screen, generate=True, background="wallpaper")
    t.login_screen = replace(t.login_screen, generate=True)
    t.fonts = replace(t.fonts, general="Inter,10")
    t.tweaks = {"kwinrc": {"Plugins": {"wobblywindowsEnabled": True}}}
    return t


@pytest.fixture
def wallpaper(tmp_path):
    p = tmp_path / "pics" / "my wall.png"
    p.parent.mkdir()
    p.write_bytes(b"\x89PNG fake")
    return p


@pytest.fixture
def built(midnight, wallpaper, cursor_base, tmp_path):
    t = everything(midnight, wallpaper)
    return t, build.build(t, tmp_path / "out")


def test_build_tree(built):
    t, out = built
    for rel in ["install.sh", "theme.toml", "layout.js", f"color-schemes/{t.slug}.colors",
                f"lookandfeel/{t.id}/metadata.json", f"lookandfeel/{t.id}/contents/defaults",
                f"lookandfeel/{t.id}/contents/splash/Splash.qml",
                f"lookandfeel/{t.id}/contents/splash/images/background.png",
                f"plasma/{t.slug}/metadata.json", f"plasma/{t.slug}/widgets/panel-background.svg",
                f"aurorae/{t.decoration_name}/decoration.svg", f"kvantum/{t.slug}/{t.slug}.kvconfig",
                f"cursors/{t.cursors_name}/index.theme",
                f"cursors/{t.cursors_name}/cursors_scalable/default/default.svg",
                "login/apply.sh", "login/greeter.sh", "wallpapers/my wall.png",
                f"konsole/{t.slug}.colorscheme"]:
        assert (out / rel).exists(), rel


def test_scripts_are_valid_bash(built):
    _, out = built
    for script in ("install.sh", "login/apply.sh", "login/greeter.sh"):
        subprocess.run(["bash", "-n", str(out / script)], check=True)


def test_no_build_machine_paths(built, tmp_path):
    """Portability rule: nothing in the build refers to where it was built."""
    _, out = built
    for f in out.rglob("*"):
        if f.is_file() and not f.is_symlink() and f.suffix not in (".png", ".jpg") and f.parent.name != "cursors":
            text = f.read_text(errors="replace")
            assert str(tmp_path) not in text, f
            assert str(ROOT) not in text, f


def test_bundled_spec_is_portable_and_loads(built):
    t, out = built
    again = spec.load(out / "theme.toml")
    assert again.wallpaper == str((out / "wallpapers" / "my wall.png").resolve())
    assert 'wallpaper = "wallpapers/my wall.png"' in (out / "theme.toml").read_text()
    assert again.cursorset.generate and again.login_screen.generate


def test_install_script_sections(built):
    t, out = built
    sh = (out / "install.sh").read_text()
    assert "plasma-apply-cursortheme" in sh and t.cursors_name in sh
    assert sh.count("pkexec") == 1 and "PARTS+=(login)" in sh
    assert "--no-login" in sh and "--layout" in sh
    assert "kwriteconfig6 --notify --file kwinrc --group Plugins --key wobblywindowsEnabled true" in sh
    assert "__aurorae__svg__" in sh
    assert 'plasma-apply-wallpaperimage "$DATA/wallpapers/' in sh


def test_all_tweaks_merges_derived_settings(built):
    t, _ = built
    tw = build.all_tweaks(t)
    assert tw["kwinrc"]["org.kde.kdecoration2"]["theme"] == t.decoration_kwin[1]
    assert tw["ksplashrc"]["KSplash"]["Theme"] == t.id
    assert tw["kdeglobals"]["General"]["font"].startswith("Inter,10,")
    assert tw["kwinrc"]["Plugins"]["wobblywindowsEnabled"] is True


def test_missing_cursor_base_falls_back(midnight, tmp_path, capsys):
    t = replace(midnight)
    t.cursorset = replace(t.cursorset, generate=True, base="nope_cursors")
    out = build.build(t, tmp_path / "out")
    assert not (out / "cursors").exists()
    assert "cursorTheme=breeze_cursors" in (out / f"lookandfeel/{t.id}/contents/defaults").read_text()
    assert 'base = "nope_cursors"' in (out / "theme.toml").read_text()     # the spec itself is kept
    assert "warning" in capsys.readouterr().err


def test_export_archive(midnight, tmp_path):
    dest = build.export(midnight, tmp_path / "x.tar.gz", build_root=tmp_path / "b")
    with tarfile.open(dest) as tar:
        names = tar.getnames()
    assert f"{midnight.slug}/install.sh" in names and f"{midnight.slug}/theme.toml" in names


@pytest.mark.skipif(not have("bash"), reason="bash")
def test_install_dry_run_via_cli(tmp_path, capsys):
    from kdecustomizer import cli
    assert cli.main(["apply", str(ROOT / "examples/midnight.toml"), "-o", str(tmp_path), "--dry-run"]) == 0
    assert "plasma-apply-lookandfeel" in capsys.readouterr().out
