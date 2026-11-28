"""GTK 4 / libadwaita colors: the CSS, and install.sh's gtk.css import handling."""
import os
import re
import subprocess
from dataclasses import replace

import pytest

from kdecustomizer import build, color, spec
from kdecustomizer.generators import gtk

# every color variable libadwaita 1.10 reads (minus palette/accent presets)
ADW = """accent-bg accent-fg accent window-bg window-fg view-bg view-fg headerbar-bg headerbar-fg headerbar-border
headerbar-backdrop headerbar-shade headerbar-darker-shade sidebar-bg sidebar-fg sidebar-backdrop sidebar-border
sidebar-shade secondary-sidebar-bg secondary-sidebar-fg secondary-sidebar-backdrop secondary-sidebar-border
secondary-sidebar-shade card-bg card-fg card-shade dialog-bg dialog-fg popover-bg popover-fg popover-shade
thumbnail-bg thumbnail-fg shade scrollbar-outline destructive-bg destructive-fg destructive success-bg success-fg
success warning-bg warning-fg warning error-bg error-fg error""".split()


def paper() -> spec.Theme:
    t = spec.Theme(name="Paper")
    t.palette = spec.Palette(background="#f4f1ea", surface="#e9e4d8", foreground="#2b2b2b", accent="#f0c419")
    return t


@pytest.mark.parametrize("make", [lambda: spec.load(__import__("conftest").EXAMPLE), paper])
def test_every_libadwaita_color_is_set(make):
    t = make()
    c = gtk.colors(t)
    assert set(ADW) <= set(c)
    for k, v in c.items():
        assert re.fullmatch(r"#[0-9a-f]{6}|rgba\(\d+, \d+, \d+, [\d.]+\)", v), (k, v)
    css = gtk.css(t)
    for k in ADW:
        assert f"--{k}-color:" in css
        assert f"@define-color {k.replace('-', '_')}_color " in css


def test_accent_text_stays_readable_on_light_views():
    t = paper()                                   # yellow accent on a cream view: too faint as text
    c = gtk.colors(t)
    view = gtk.colors_gen.scheme(t)["Colors:View"]["BackgroundNormal"]
    assert color.contrast(c["accent"], view) >= 3.0
    assert c["accent-bg"] == "#f0c419"            # the fill keeps the real accent


def snippet(tmp_path, theme) -> str:
    out = build.build(theme, tmp_path / "b")
    sh = (out / "install.sh").read_text()
    start = sh.index("if (( GTK )); then\n") + len("if (( GTK )); then\n")   # the part --no-gtk skips
    end = sh.index('\nelse\n  echo "==> GTK', start)
    return out, sh[start:end]


def run(snip, out, conf):
    subprocess.run(["bash", "-c", "set -euo pipefail\n" + snip], check=True, capture_output=True,
                   env={"PATH": "/usr/bin:/bin", "CONF": str(conf), "DIR": str(out)})


@pytest.mark.parametrize("before, after", [
    ("@import 'colors.css';", "@import 'colors.css';\n@import 'kde-customizer.css';\n"),   # KDE's (no newline)
    ("", "@import 'kde-customizer.css';\n"),
    (None, "@import 'kde-customizer.css';\n"),                                             # no gtk.css yet
    ("@import 'colors.css';\n@import 'mine.css';\nwindow { margin: 0; }\n",
     "@import 'colors.css';\n@import 'mine.css';\n@import 'kde-customizer.css';\nwindow { margin: 0; }\n"),
])
def test_import_is_added_once_after_the_last_import(midnight, tmp_path, before, after):
    out, snip = snippet(tmp_path, midnight)
    conf = tmp_path / "conf"
    (conf / "gtk-4.0").mkdir(parents=True)
    if before is not None:
        (conf / "gtk-4.0/gtk.css").write_text(before)
    run(snip, out, conf)
    run(snip, out, conf)                          # idempotent
    assert (conf / "gtk-4.0/gtk.css").read_text() == after
    assert (conf / "gtk-4.0/kde-customizer.css").read_text() == gtk.css(midnight)


def test_symlinked_gtk_css_is_kept(midnight, tmp_path):
    out, snip = snippet(tmp_path, midnight)
    conf = tmp_path / "conf"
    (conf / "gtk-4.0").mkdir(parents=True)
    (tmp_path / "dotfiles.css").write_text("@import 'colors.css';\n")
    os.symlink(tmp_path / "dotfiles.css", conf / "gtk-4.0/gtk.css")
    run(snip, out, conf)
    assert (conf / "gtk-4.0/gtk.css").is_symlink()
    assert "kde-customizer.css" in (tmp_path / "dotfiles.css").read_text()


def test_theme_without_gtk_removes_ours(midnight, tmp_path):
    out, snip = snippet(tmp_path, midnight)
    conf = tmp_path / "conf"
    (conf / "gtk-4.0").mkdir(parents=True)
    (conf / "gtk-4.0/gtk.css").write_text("@import 'colors.css';\nwindow { margin: 0; }\n")
    run(snip, out, conf)
    off = replace(midnight, gtk=spec.Gtk(generate=False))
    out2, snip2 = snippet(tmp_path / "2", off)
    assert not (out2 / "gtk").exists()
    run(snip2, out2, conf)
    assert (conf / "gtk-4.0/gtk.css").read_text() == "@import 'colors.css';\nwindow { margin: 0; }\n"
    assert not (conf / "gtk-4.0/kde-customizer.css").exists()


def test_flatpak_override_only_when_asked(midnight, tmp_path):
    _, snip = snippet(tmp_path, midnight)
    assert "flatpak override" not in snip
    _, snip = snippet(tmp_path / "f", replace(midnight, gtk=spec.Gtk(flatpak=True)))
    assert "flatpak override --user --filesystem=xdg-config/gtk-4.0:ro" in snip
