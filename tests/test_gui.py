"""GUI smoke tests, offscreen: the editor loads a spec, round-trips it, and the preview paints every popup."""

import pytest

from conftest import EXAMPLE, pyside6

pytestmark = pytest.mark.skipif(not pyside6(), reason="needs PySide6")


@pytest.fixture
def app(qapp):
    return qapp


@pytest.fixture
def window(app):
    from kdecustomizer.gui.app import Main
    w = Main(str(EXAMPLE))
    w.resize(1400, 900)
    w.show()
    app.processEvents()
    yield w
    w.dirty = False
    w.close()


def test_form_round_trips_the_spec(window):
    from kdecustomizer import spec
    assert spec.dumps(window.from_form()) == spec.dumps(spec.load(EXAMPLE))


def test_tweaks_table(window):
    from kdecustomizer.gui.fields import TWEAK_PRESETS
    window._add_tweaks(next(e for _, label, e in TWEAK_PRESETS if label == "Stronger blur"))
    window._add_tweaks([("kdeglobals", "KDE", "AnimationDurationFactor", 0.5)])
    t = window.from_form()
    assert t.tweaks["kwinrc"]["Effect-blur"]["BlurStrength"] == 10          # replaced the example's 8
    assert t.tweaks["kdeglobals"]["KDE"]["AnimationDurationFactor"] == 0.5
    count = lambda: sum(len(g) for f in window.from_form().tweaks.values() for g in f.values())  # noqa: E731
    assert count() == 4             # example's 3 (blur rows replaced, not duplicated) + animation speed
    window.tweaks.selectRow(0)
    window._remove_tweaks()
    assert count() == 3


def test_preview_paints_every_popup(window, app):
    pv = window.preview
    pv.show_theme(window.from_form())
    for key in ("", "launcher", "calendar", "tray", "dialog"):
        window.popup.setCurrentIndex(window.popup.findData(key))
        app.processEvents()
        assert pv.popup == key
        img = pv.grab().toImage()
        assert not img.isNull()
        if key:
            assert pv._popup_rect is not None and pv._popup_rect.width() > 100
    assert set(pv._anchors) == {"launcher", "calendar", "tray"}


def test_from_desktop_on_a_blank_desktop(window):
    window.dirty = False
    window.from_desktop()
    assert window.from_form().name == "My Desktop" and window.dirty
