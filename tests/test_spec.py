import tomllib

import pytest

from kdecustomizer import color, spec


def test_example_loads_and_round_trips(midnight):
    again = spec.from_dict(tomllib.loads(spec.dumps(midnight)))
    assert again == midnight


def test_defaults_round_trip():
    t = spec.Theme()
    assert spec.from_dict(tomllib.loads(spec.dumps(t))) == t


def test_dumps_quotes_awkward_strings_and_tweak_keys():
    t = spec.Theme(name='Say "hi" \\ there')
    t.tweaks = {"kwinrc": {"Containments/1": {"odd key": 1.5, "flag": True}}}
    again = spec.from_dict(tomllib.loads(spec.dumps(t)))
    assert again.name == t.name
    assert again.tweaks == t.tweaks


def test_unknown_keys_are_rejected():
    with pytest.raises(ValueError, match="unknown keys"):
        spec.from_dict({"palette": {"bacground": "#000000"}})


@pytest.mark.parametrize("data, msg", [
    ({"plasma": {"radius": 40}}, "radius"),
    ({"plasma": {"opacity": 0.1}}, "opacity"),
    ({"widgets": {"radius": 20}}, "radius"),
    ({"decoration": {"title_height": 10}}, "title_height"),
    ({"decoration": {"radius": 20, "title_height": 30}}, "radius"),
    ({"decoration": {"border": 20}}, "border"),
    ({"decoration": {"title_align": "middle"}}, "title_align"),
    ({"decoration": {"button_style": "square"}}, "button_style"),
    ({"splash_screen": {"background": "video"}}, "background"),
    ({"login_screen": {"background": "video"}}, "background"),
    ({"cursorset": {"fill": "red"}}, "fill"),
])
def test_out_of_range_values_are_rejected(data, msg):
    with pytest.raises(ValueError, match=msg):
        spec.from_dict(data)


def test_load_resolves_relative_wallpaper(tmp_path):
    (tmp_path / "walls").mkdir()
    (tmp_path / "walls" / "w.png").write_bytes(b"x")
    (tmp_path / "t.toml").write_text('name = "T"\nwallpaper = "walls/w.png"\n')
    assert spec.load(tmp_path / "t.toml").wallpaper == str((tmp_path / "walls" / "w.png").resolve())


def test_load_rejects_bad_colors(tmp_path):
    (tmp_path / "t.toml").write_text('[palette]\naccent = "#12345"\n')
    with pytest.raises(ValueError):
        spec.load(tmp_path / "t.toml")


def test_names_follow_generate_flags():
    t = spec.Theme(name="Deep Sea!")
    assert t.slug == "DeepSea"
    assert (t.plasma_style_name, t.icons_name, t.cursors_name, t.splash_name) == \
        ("default", "breeze", "breeze_cursors", "org.kde.Breeze")
    t.plasma.generate = t.iconset.generate = t.cursorset.generate = t.splash_screen.generate = True
    t.decoration.generate = True
    assert t.plasma_style_name == "DeepSea"
    assert t.icons_name == "DeepSea-Icons"
    assert t.cursors_name == "DeepSea-Cursors"
    assert t.splash_name == t.id
    assert t.decoration_kwin == ("org.kde.kwin.aurorae", "__aurorae__svg__DeepSea-Decoration")


def test_custom_shapes_only_when_different_from_breeze():
    p = spec.PlasmaStyle()
    assert not p.custom_shapes
    p.radius = 12
    assert p.custom_shapes


def test_palette_resolves_link_and_visited():
    p = spec.Palette(accent="#3366ff", negative="#ff0000").resolved()
    assert p.link == "#3366ff"
    assert p.visited == color.to_hex(color.mix("#3366ff", "#ff0000", 0.4))
