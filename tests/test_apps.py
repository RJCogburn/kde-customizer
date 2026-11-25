"""Other terminals/editors: generated files, and install.sh's config edits (on, idempotent, undone when off)."""
import io
import json
import re
import subprocess
import tomllib
import zipfile
from dataclasses import replace

import pytest
from pathlib import Path

from kdecustomizer import build, spec
from kdecustomizer.generators import apps, konsole

HEX = re.compile(r"#[0-9a-f]{6}([0-9a-f]{2})?")


def test_terminal_files_use_the_konsole_palette(midnight):
    a = konsole.ansi(midnight)
    bg = "#%02x%02x%02x" % a["Background"]
    red = "#%02x%02x%02x" % a["Color1"]
    k = apps.kitty(midnight)
    assert f"background {bg}" in k and f"color1 {red}" in k and "color15 " in k
    al = tomllib.loads(apps.alacritty(midnight))["colors"]
    assert al["primary"]["background"] == bg and al["normal"]["red"] == red and len(al["bright"]) == 8
    wz = tomllib.loads(apps.wezterm(midnight))["colors"]
    assert wz["background"] == bg and wz["ansi"][1] == red and len(wz["brights"]) == 8
    g = apps.ghostty(midnight)
    assert f"palette = 1={red}" in g and f"background = {bg}" in g


def test_vsix_is_a_valid_theme_extension(midnight):
    z = zipfile.ZipFile(io.BytesIO(apps.vsix(midnight)))
    names = set(z.namelist())
    assert {"[Content_Types].xml", "extension.vsixmanifest", "extension/package.json"} <= names
    pkg = json.loads(z.read("extension/package.json"))
    t = pkg["contributes"]["themes"][0]
    assert pkg["publisher"] == "kdecustomizer" and pkg["name"] == "kdec-midnight" and pkg["version"] == "1.0.0"
    assert t["uiTheme"] == "vs-dark" and t["label"] == "Midnight"
    theme = json.loads(z.read("extension/" + t["path"][2:]))
    assert all(HEX.fullmatch(v) for v in theme["colors"].values()), theme["colors"]
    assert theme["colors"]["editor.background"] == "#1b1c26" or HEX.fullmatch(theme["colors"]["editor.background"])
    assert all(HEX.fullmatch(tc["settings"]["foreground"]) for tc in theme["tokenColors"])
    assert apps.vsix(midnight) == apps.vsix(midnight)              # reproducible


def test_light_theme_uses_light_vscode_base():
    t = spec.Theme(name="Paper")
    t.palette = spec.Palette(background="#f4f1ea", surface="#e9e4d8", foreground="#2b2b2b", accent="#c0392b")
    assert json.loads(zipfile.ZipFile(io.BytesIO(apps.vsix(t))).read("extension/package.json")
                      )["contributes"]["themes"][0]["uiTheme"] == "vs"


def test_only_enabled_apps_are_built(midnight, tmp_path):
    t = replace(midnight, apps=spec.Apps(kitty=True, alacritty=False, wezterm=False, ghostty=False, vscode=False))
    out = build.build(t, tmp_path / "b")
    assert [p.name for p in (out / "apps").iterdir()] == ["kitty"]


def section(sh: str, start: str) -> str:
    i = sh.index(start)
    j = sh.index("\nfi\n", i)
    return sh[i:j + 3]


def install(theme, tmp_path, key):
    out = build.build(theme, tmp_path / f"b-{key}")
    sh = (out / "install.sh").read_text()
    return out, section(sh, {"alacritty": "if command -v alacritty", "kitty": "if command -v kitty",
                             "ghostty": "if command -v ghostty"}[key])


def run(snip, out, conf):
    subprocess.run(["bash", "-c", "set -euo pipefail\n" + snip], check=True, capture_output=True,
                   env={"PATH": "/usr/bin:/bin", "CONF": str(conf), "DIR": str(out)})


CACHY = """[env]
TERM = "xterm-256color"

[general]
live_config_reload = true

[colors]
draw_bold_text_with_bright_colors = true

[colors.primary]
background = "0x2E3440"

[colors.normal]
black = "0x3B4252"

[[colors.hints.enabled]]
regex = "x"

[window]
opacity = 0.8
"""


@pytest.mark.parametrize("before", [
    CACHY,
    'import = ["~/.config/alacritty/other.toml"]\n\n[colors.primary]\nbackground = "#000000"\n',
    '[window]\nopacity = 1\n',
    'live_config_reload = true\n',
    None,
])
def test_alacritty_on_then_off(midnight, tmp_path, before):
    conf = tmp_path / "conf"
    (conf / "alacritty").mkdir(parents=True)
    cfg = conf / "alacritty/alacritty.toml"
    if before is not None:
        cfg.write_text(before)
    out, on = install(midnight, tmp_path, "alacritty")
    run(on, out, conf)
    run(on, out, conf)                                  # idempotent
    d = tomllib.loads(cfg.read_text())
    imports = d.get("general", {}).get("import") or d.get("import")
    assert imports.count("~/.config/alacritty/kde-customizer.toml") == 1
    colors = d.get("colors", {})
    assert set(colors) <= {"draw_bold_text_with_bright_colors"}          # the user's color tables are out
    assert (conf / "alacritty/kde-customizer.toml").is_file()
    off = replace(midnight, apps=replace(midnight.apps, alacritty=False))
    out2, off_snip = install(off, tmp_path, "alacritty")
    run(off_snip, out2, conf)
    if before is not None and "import" not in before and "[general]" in before or before == CACHY:
        assert cfg.read_text() == before                                  # byte-for-byte back
    assert "kde-customizer" not in cfg.read_text()
    assert not (conf / "alacritty/kde-customizer.toml").exists()
    tomllib.loads(cfg.read_text())


def test_kitty_block_replaced_not_duplicated_and_removed(midnight, tmp_path):
    conf = tmp_path / "conf"
    (conf / "kitty").mkdir(parents=True)
    (conf / "kitty/kitty.conf").write_text("font_size 12\n")
    out, on = install(midnight, tmp_path, "kitty")
    run(on, out, conf)
    run(on, out, conf)
    text = (conf / "kitty/kitty.conf").read_text()
    assert text.count("BEGIN_KDEC_THEME") == 1 and text.startswith("font_size 12\n")
    assert text.rstrip().endswith("# END_KDEC_THEME")
    assert "include kde-customizer-theme.conf" in text
    assert (conf / "kitty/themes/Midnight.conf").is_file()
    off = replace(midnight, apps=replace(midnight.apps, kitty=False))
    out2, off_snip = install(off, tmp_path, "kitty")
    run(off_snip, out2, conf)
    assert "KDEC" not in (conf / "kitty/kitty.conf").read_text()


def test_ghostty_prefers_config_ghostty(midnight, tmp_path):
    conf = tmp_path / "conf"
    (conf / "ghostty").mkdir(parents=True)
    (conf / "ghostty/config.ghostty").write_text("font-size = 12\n")
    out, on = install(midnight, tmp_path, "ghostty")
    run(on, out, conf)
    assert "theme = Midnight" in (conf / "ghostty/config.ghostty").read_text()
    assert not (conf / "ghostty/config").exists()


@pytest.mark.skipif(any(Path(d, "kitty").exists() for d in ("/usr/bin", "/bin")), reason="kitty is installed")
def test_apps_not_installed_are_left_alone(midnight, tmp_path):
    conf = tmp_path / "conf"
    conf.mkdir()
    out, on = install(midnight, tmp_path, "kitty")
    run(on, out, conf)                                  # no kitty on PATH and no ~/.config/kitty: nothing written
    assert not (conf / "kitty").exists()
