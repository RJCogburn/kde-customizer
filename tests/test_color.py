import pytest

from kdecustomizer import color


def test_parse_and_hex():
    assert color.parse("#ff8000") == (255, 128, 0)
    assert color.parse("#f80") == (255, 136, 0)
    assert color.to_hex((255, 128, 0)) == "#ff8000"
    assert color.to_kde("#ff8000") == "255,128,0"
    assert color.parse("ff8000") == (255, 128, 0)      # the # is optional


@pytest.mark.parametrize("bad", ["#ff80", "#gg0000", ""])
def test_parse_rejects(bad):
    with pytest.raises(ValueError):
        color.parse(bad)


def test_contrast_extremes():
    assert color.contrast("#000000", "#ffffff") == pytest.approx(21, rel=1e-3)
    assert color.contrast("#777777", "#777777") == pytest.approx(1)


def test_mix_and_darkness():
    assert color.mix("#000000", "#ffffff", 0.5) in [(127, 127, 127), (128, 128, 128)]
    assert color.is_dark("#14151f")
    assert not color.is_dark("#f0f0f0")


def test_shift_moves_away_from_the_background():
    assert color.luminance(color.shift("#202020", 0.2, dark=True)) > color.luminance("#202020")
    assert color.luminance(color.shift("#e0e0e0", 0.2, dark=False)) < color.luminance("#e0e0e0")
