"""Generators are pure Theme -> str functions: check structure, not pixels."""
import configparser
import json
import re
import xml.etree.ElementTree as ET

import pytest

from kdecustomizer import spec
from kdecustomizer.generators import (aurorae, colors, konsole, kvantum, layout, lookandfeel, loginscreen,
                                      plasmastyle, splash)

SVG_NS = "{http://www.w3.org/2000/svg}"


def ids(svg_text: str) -> set[str]:
    root = ET.fromstring(svg_text)
    return {e.get("id") for e in root.iter() if e.get("id")}


def ini(text: str) -> configparser.ConfigParser:
    c = configparser.ConfigParser(interpolation=None, strict=False)
    c.optionxform = str
    c.read_string(text)
    return c


def light() -> spec.Theme:
    t = spec.Theme(name="Paper")
    t.palette = spec.Palette(background="#f4f1ea", surface="#ffffff", foreground="#2b2b2b", accent="#c0392b")
    return t


@pytest.mark.parametrize("make", [spec.Theme, light])
def test_color_scheme_has_every_section_and_valid_colors(make):
    t = make()
    c = ini(colors.generate(t))
    for sec in ("Colors:Window", "Colors:View", "Colors:Button", "Colors:Selection", "Colors:Tooltip",
                "Colors:Header", "Colors:Complementary", "General", "WM"):
        assert c.has_section(sec), sec
    for sec in c.sections():
        for k, v in c[sec].items():
            if re.fullmatch(r"\d+,\d+,\d+", v):
                assert all(0 <= int(x) <= 255 for x in v.split(",")), (sec, k, v)
    assert c["Colors:Window"]["BackgroundNormal"] == ",".join(map(str, spec.color.parse(t.palette.background)))


def test_konsole_scheme_and_profile(midnight):
    c = ini(konsole.colorscheme(midnight))
    assert c.has_section("Background") and c.has_section("Color7Intense")
    p = ini(konsole.profile(midnight))
    assert p["Appearance"]["ColorScheme"] == midnight.slug
    assert konsole._qfont("Inter,11").startswith("Inter,11,-1,5,400")


def test_lookandfeel_points_at_what_is_applied(midnight):
    meta = json.loads(lookandfeel.metadata(midnight))
    assert meta["KPlugin"]["Id"] == midnight.id
    d = lookandfeel.defaults(midnight)
    assert f"cursorTheme={midnight.cursors_name}" in d
    assert f"theme={midnight.decoration_kwin[1]}" in d
    assert midnight.splash_name in d


def test_layout_script_describes_each_panel(midnight):
    js = layout.generate(midnight)
    for p in midnight.panels:
        assert json.dumps(p.location) in js
        for w in p.widgets:
            assert w in js


def test_plasma_style_uses_breeze_svgs_unless_shapes_change():
    t = spec.Theme()
    t.plasma.generate = True
    assert plasmastyle.svgs(t) == {}
    t.plasma.radius = 14
    files = plasmastyle.svgs(t)
    for variant in ("", "translucent/", "solid/"):
        for f in ("dialogs/background.svg", "widgets/panel-background.svg", "widgets/tooltip.svg"):
            assert variant + f in files
    assert "widgets/background.svg" in files
    for name, text in files.items():
        got = ids(text)
        for piece in ("topleft", "top", "topright", "left", "center", "right", "bottomleft", "bottom",
                      "bottomright"):
            assert piece in got, (name, piece)
        assert any(i.startswith("shadow-") for i in got), name
    panel = next(v for k, v in files.items() if "panel-background" in k)
    assert any(i.startswith("thick-") for i in ids(panel))


def test_plasma_colors_and_rc(midnight):
    assert ini(plasmastyle.colors(midnight)).has_section("Colors:Window")
    rc = ini(plasmastyle.plasmarc(midnight))
    assert rc.sections()


@pytest.mark.parametrize("style", ["glyph", "dots"])
def test_aurorae_files(midnight, style):
    midnight.decoration.button_style = style
    files = aurorae.files(midnight)
    name = midnight.decoration_name
    assert "decoration.svg" in files and f"{name}rc" in files and "metadata.json" in files
    deco = ids(files["decoration.svg"])
    for pre in ("decoration-", "decoration-inactive-"):
        for piece in ("topleft", "top", "center", "bottomright"):
            assert pre + piece in deco
    for btn in ("close", "minimize", "maximize", "restore"):
        got = ids(files[f"{btn}.svg"])
        assert {"active-center", "hover-center", "pressed-center", "inactive-center"} <= got, btn
    rc = ini(files[f"{name}rc"])
    assert int(rc["Layout"]["TitleHeight"]) == midnight.decoration.title_height


def test_kvantum_theme(midnight):
    files = kvantum.files(midnight)
    name = midnight.kvantum_name
    svg_ids = ids(files[f"{name}.svg"])
    conf = ini(files[f"{name}.kvconfig"])
    # every interior/frame element the config names must exist in the SVG (or be intentionally empty)
    for sec in conf.sections():
        for key in ("interior.element", "frame.element"):
            el = conf[sec].get(key)
            if el and conf[sec].get(key.split(".")[0], "true") != "false":
                assert any(i == el or i.startswith(el + "-") for i in svg_ids), (sec, key, el)
    assert "button-default-indicator" in svg_ids


def test_splash_qml_escapes_text(midnight):
    midnight.splash_screen.generate = True
    midnight.splash_screen.text = 'He said "hi"\n'
    qml = splash.qml(midnight)
    assert "property int stage" in qml
    assert json.dumps(midnight.splash_screen.text) in qml
    assert splash.background_file(midnight) is None
    midnight.splash_screen.background = "wallpaper"
    midnight.wallpaper = "/x/y/photo.JPG"
    assert splash.background_file(midnight) == "background.jpg"
    assert 'source: "images/background.jpg"' in splash.qml(midnight)


def test_login_entries_cover_colors_style_cursor(midnight):
    from kdecustomizer.build import _FONT_KEYS
    e = loginscreen.entries(midnight, _FONT_KEYS, konsole._qfont)
    files = {(f, tuple(g), k): v for f, g, k, v in e}
    assert files[("plasmarc", ("Theme",), "name")] == midnight.plasma_style_name
    assert files[("kcminputrc", ("Mouse",), "cursorTheme")] == midnight.cursors_name
    assert files[("kdeglobals", ("Icons",), "Theme")] == midnight.icons_name
    assert ("kdeglobals", ("Colors:Header", "Inactive"), "BackgroundNormal") in files
