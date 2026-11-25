"""App icons recolored to the palette: finding them, plate vs logo, SVG + PNG, iconset integration."""
from pathlib import Path

import pytest

from conftest import qtsvg
from kdecustomizer import appicons, color, iconset, spec

pytestmark = pytest.mark.skipif(not qtsvg(), reason="plate detection renders icons with QtSvg")

PLATE_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
             '<rect width="64" height="64" rx="12" fill="#2266cc"/>'          # blue tile
             '<circle cx="32" cy="32" r="14" fill="#ffffff"/></svg>')         # white logo
LOGO_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
            '<path d="M20 52 L32 8 L44 52 Z" fill="#ee8800"/></svg>')          # free-standing cone


@pytest.fixture(autouse=True)
def app(qapp):
    return qapp


def theme() -> spec.Theme:
    t = spec.Theme(name="Sc")
    t.palette = spec.Palette(background="#121315", surface="#1c1e21", foreground="#dadde2", accent="#ff5a1f")
    t.iconset = spec.IconSet(generate=True, base="Fake", app_icons="recolor")
    return t


@pytest.fixture
def desktop(tmp_path):
    """A base icon theme 'Fake' + hicolor PNG in the user dir + a few .desktop files."""
    share = tmp_path / "usr-share"
    fake = share / "icons/Fake"
    (fake / "64x64/apps").mkdir(parents=True)
    (fake / "index.theme").write_text("[Icon Theme]\nName=Fake\nInherits=hicolor\nDirectories=64x64/apps\n\n"
                                      "[64x64/apps]\nSize=64\nContext=Applications\nType=Fixed\n")
    (fake / "64x64/apps/plated.svg").write_text(PLATE_SVG)
    (fake / "64x64/apps/cone.svg").write_text(LOGO_SVG)
    (fake / "64x64/apps/folder.svg").write_text(LOGO_SVG)
    hic = share / "icons/hicolor"
    hic.mkdir(parents=True)
    (hic / "index.theme").write_text("[Icon Theme]\nName=Hicolor\nDirectories=48x48/apps\n\n"
                                     "[48x48/apps]\nSize=48\nContext=Applications\nType=Threshold\n")
    user_hic = Path.home() / ".local/share/icons/hicolor/48x48/apps"   # no index.theme here: uses hicolor's
    user_hic.mkdir(parents=True)
    from PySide6.QtGui import QColor, QImage, QPainter
    img = QImage(48, 48, QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.fillRect(4, 4, 40, 40, QColor("#20a050"))                       # green tile
    p.fillRect(18, 18, 12, 12, QColor("#ffffff"))                     # white logo
    p.end()
    img.save(str(user_hic / "wineapp.png"))
    apps = share / "applications"
    apps.mkdir()
    for name, icon, extra in [("a", "plated", ""), ("b", "cone", ""), ("c", "wineapp", ""),
                              ("d", "hidden", "NoDisplay=true\n"), ("e", "/opt/x/icon.png", ""),
                              ("f", "missing-everywhere", "")]:
        (apps / f"{name}.desktop").write_text(f"[Desktop Entry]\nType=Application\nName={name}\nIcon={icon}\n{extra}")
    return share


def test_installed_app_icons_skips_hidden_and_paths(desktop):
    assert appicons.installed_app_icons() == ["cone", "missing-everywhere", "plated", "wineapp"]


def test_finder_follows_inherits_and_user_hicolor(desktop):
    f = appicons.IconFinder("Fake")
    assert f.find("plated").suffix == ".svg"
    assert f.find("wineapp").suffix == ".png"           # ~/.local/share/icons/hicolor without its own index
    assert f.find("missing-everywhere") is None


def _px(img, x, y):
    c = img.pixelColor(x, y)
    return c.red(), c.green(), c.blue(), c.alpha()


def test_plated_icon_gets_graphite_plate_rim_and_keeps_its_logo(desktop, tmp_path):
    src = tmp_path / "p.svg"
    src.write_text(PLATE_SVG)
    img = appicons.load(src)
    st = appicons.stops(theme())
    out = appicons.restyle(img, st)
    assert out is not None
    n = out.width()
    logo = _px(out, n // 2, n // 2)
    assert logo[:3] == (255, 255, 255)                         # the logo keeps its own color
    plate = _px(out, n // 2, int(n * 0.18))                      # between rim and logo
    assert color.contrast(plate[:3], (255, 255, 255)) > 7       # graphite, not the old blue
    assert abs(plate[0] - plate[2]) < 30                        # neutral-ish, no longer blue
    rim = _px(out, n // 2, 3)                                   # just inside the top edge
    assert color.contrast(rim[:3], st["rim"]) < 1.6             # the accent rim
    assert _px(out, 0, 0)[3] == _px(img, 0, 0)[3]               # silhouette (rounded corner) kept


def test_dark_logo_on_light_tile_is_flipped(tmp_path):
    src = tmp_path / "d.svg"
    src.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
                   '<rect width="64" height="64" rx="10" fill="#f4f4f4"/><rect x="22" y="22" width="20" height="20" '
                   'fill="#111111"/></svg>')
    out = appicons.restyle(appicons.load(src), appicons.stops(theme()))
    n = out.width()
    assert appicons._lightness(_px(out, n // 2, n // 2)[:3]) > 0.8


def test_free_standing_logo_is_left_alone(tmp_path):
    src = tmp_path / "c.svg"
    src.write_text(LOGO_SVG)
    assert appicons.restyle(appicons.load(src), appicons.stops(theme())) is None


def test_png_source(desktop):
    f = appicons.IconFinder("Fake").find("wineapp")
    out = appicons.restyle(appicons.load(f), appicons.stops(theme()))
    assert out is not None and appicons.svg_wrap(out).startswith("<svg")


def test_iconset_build_adds_the_app_layer(desktop, tmp_path):
    out = iconset.build(theme(), tmp_path / "out")
    d = out / appicons.APPS_DIR
    assert sorted(p.stem for p in d.glob("*.svg")) == ["plated", "wineapp"]   # the cone has no plate
    idx = (out / "index.theme").read_text()
    assert appicons.APPS_DIR in idx and "Context=Applications" in idx


def test_keep_means_no_app_layer(desktop, tmp_path):
    t = theme()
    t.iconset.app_icons = "keep"
    out = iconset.build(t, tmp_path / "out")
    assert not (out / appicons.APPS_DIR).exists()


def test_signature_dirs_use_spec_context_names(tmp_path, desktop):
    """Regression: signature app icons were filed under Context=Apps, which KDE's lookup skips."""
    sig = tmp_path / "sig"
    (sig / "svg").mkdir(parents=True)
    for slot in ("folder", "system-file-manager"):
        (sig / "svg" / f"{slot}.svg").write_text(PLATE_SVG)
    t = theme()
    t.iconset.app_icons = "keep"
    t.iconset.signature_dir = str(sig)
    out = iconset.build(t, tmp_path / "out")
    idx = (out / "index.theme").read_text()
    assert "[signature/scalable/apps]" in idx and "Context=Apps\n" not in idx
    section = idx.split("[signature/scalable/apps]")[1].split("\n\n")[0]
    assert "Context=Applications" in section
