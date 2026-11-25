"""AI wallpaper (wallpaper.py) with a fake image backend; Fooocus aspect-ratio choice; the placeholder-id fix."""
import io

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from kdecustomizer import cli, imagegen, spec, wallpaper  # noqa: E402


class FakeBackend(imagegen.Backend):
    name = "Fake"

    def __init__(self):
        super().__init__("http://x")
        self.calls = []

    def generate(self, prompt, negative, seed):
        self.calls.append((prompt, negative, seed, self.size))
        im = Image.new("RGB", self.size, (20, 21, 31))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()


@pytest.fixture
def fake(monkeypatch):
    b = FakeBackend()
    monkeypatch.setattr(imagegen, "detect", lambda url, perf="", model="": b)
    return b


def test_describe_colors():
    assert wallpaper.describe("#14151f") == "near-black charcoal"
    assert "violet" in wallpaper.describe("#8b7cf6") or "indigo" in wallpaper.describe("#8b7cf6")
    assert wallpaper.describe("#ff5a1f").endswith("orange")
    assert wallpaper.describe("#f0f0f5") == "pale white"


def test_prompt_uses_idea_and_palette(midnight):
    p = wallpaper.prompt(midnight, "misty mountains.")
    assert p.startswith("misty mountains, desktop wallpaper") and "dark, moody" in p
    assert wallpaper.describe(midnight.palette.accent) in p
    assert wallpaper.prompt(midnight).startswith(midnight.description.rstrip(" ."))


@pytest.mark.parametrize("screen, size", [((3840, 2160), (1344, 768)), ((2560, 1600), (1216, 832)),
                                          ((3440, 1440), (1536, 640)), ((1080, 1920), (768, 1344))])
def test_render_size_matches_screen_shape(screen, size):
    assert wallpaper.render_size(screen) == size


def test_fooocus_ratio_choice():
    choices = ['704×1408 <span>1:2</span>', '1024×1024 <span>1:1</span>', '1344×768 <span>16:9</span>',
               '1152×896 <span>9:7</span>']
    assert imagegen.closest_ratio(choices, (1344, 768)).startswith("1344×768")
    assert imagegen.closest_ratio(choices, (1024, 1024)).startswith("1024×1024")
    assert imagegen.closest_ratio(choices, (1216, 832)).startswith("1152×896")
    assert imagegen.closest_ratio([], (1, 1)) is None


def test_generate_scales_to_the_screen(midnight, tmp_path, fake):
    path = wallpaper.generate(midnight, tmp_path, "http://x", idea="dunes", seed=7, screen=(1920, 1080))
    assert path == tmp_path / "midnight-wallpaper-7.jpg"
    with Image.open(path) as im:
        assert im.size == (1920, 1080) and im.format == "JPEG"
    assert fake.calls[0][3] == (1344, 768) and fake.calls[0][2] == 7 and "dunes" in fake.calls[0][0]


def test_cli_sets_the_spec_wallpaper(midnight, tmp_path, fake, capsys):
    f = tmp_path / "m.toml"
    spec.save(midnight, f)
    assert cli.main(["wallpaper", str(f), "neon city", "--size", "1280x800", "--seed", "3"]) == 0
    t = spec.load(f)
    assert t.wallpaper == str(tmp_path / "midnight-wallpaper-3.jpg")
    with Image.open(t.wallpaper) as im:
        assert im.size == (1280, 800)
    capsys.readouterr()
    assert cli.main(["wallpaper", str(f), "x", "--prompt-only"]) == 0
    assert capsys.readouterr().out.startswith("x, desktop wallpaper")


def test_named_theme_gets_a_real_id(tmp_path):
    t = spec.Theme(name="SC1")                       # id still org.kdecustomizer.untitled
    spec.save(t, tmp_path / "t.toml")
    assert spec.load(tmp_path / "t.toml").id == "org.kdecustomizer.sc1"
    (tmp_path / "u.toml").write_text('id = "org.kdecustomizer.untitled"\nname = "Neon Night"\n')
    assert spec.load(tmp_path / "u.toml").id == "org.kdecustomizer.neonnight"
    assert spec.fix_id(spec.Theme()).id == "org.kdecustomizer.untitled"      # unnamed stays a placeholder
    assert spec.fix_id(spec.Theme(name="X", id="com.me.x")).id == "com.me.x"   # real ids are kept
