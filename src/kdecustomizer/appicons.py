"""App icons restyled to the theme (`[iconset] app_icons = "recolor"`).

Every app the desktop can see (visible .desktop files, incl. Flatpak exports) keeps its own logo in its own
colors — the icon the user's base theme shows for it — but the icon's plate (its tile / circle / squircle
background) is redrawn as a graphite gradient with a thin accent rim, so the set looks like one family and
each logo pops against the theme. A logo that was dark on a light tile is flipped light so it reads on the
graphite. Free-standing logos (no plate) are left as they are: they already stand out.
Done in Qt on a 256 px render (SVG or PNG source), written as an SVG wrapping the PNG.
Apps whose Icon= is an absolute path can't be themed and are left alone.
"""
from __future__ import annotations

import base64
import colorsys
import configparser
import os
import re
from pathlib import Path

from . import color, system
from .spec import Theme

APPS_DIR = "apps-recolored/scalable"



def _data_dirs() -> list[Path]:
    # Flatpak's system exports are in XDG_DATA_DIRS already (its profile script adds them); the user ones
    # are added here in case the session started before Flatpak was set up
    extra = [Path.home() / ".local/share/flatpak/exports/share"]
    out = []
    for d in [*system._data_dirs(), *extra]:
        if d not in out:
            out.append(d)
    return out


def installed_app_icons() -> list[str]:
    """Icon names (not paths) of every visible app, sorted."""
    names: set[str] = set()
    seen_ids: set[str] = set()
    for base in _data_dirs():
        apps = base / "applications"
        if not apps.is_dir():
            continue
        for f in apps.rglob("*.desktop"):
            if f.name in seen_ids:          # first data dir wins, like the menu does
                continue
            seen_ids.add(f.name)
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                cp.read_string(f.read_text(errors="replace"))
            except (configparser.Error, OSError):
                continue
            if not cp.has_section("Desktop Entry"):
                continue
            e = cp["Desktop Entry"]
            if e.get("NoDisplay", "false").lower() == "true" or e.get("Hidden", "false").lower() == "true":
                continue
            icon = e.get("Icon", "").strip()
            if icon and "/" not in icon:
                names.add(icon[:-4] if icon.endswith((".png", ".svg", ".xpm")) else icon)
    return sorted(names)


# --- finding the icon the user sees ---------------------------------------------------------------

def _theme_dirs(name: str) -> list[Path]:
    return [d / name for d in [Path.home() / ".icons", *(b / "icons" for b in _data_dirs())] if (d / name).is_dir()]


def _index(theme_dir: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        cp.read_string((theme_dir / "index.theme").read_text(errors="replace"))
    except (OSError, configparser.Error):
        pass
    return cp


def theme_chain(name: str) -> list[str]:
    """The theme, everything it inherits (depth first), then hicolor."""
    out: list[str] = []

    def walk(n: str) -> None:
        if n in out:
            return
        out.append(n)
        for d in _theme_dirs(n):
            cp = _index(d)
            if cp.has_section("Icon Theme"):
                for parent in cp["Icon Theme"].get("Inherits", "").split(","):
                    if parent.strip():
                        walk(parent.strip())
                break
    walk(name)
    if "hicolor" in out:
        out.remove("hicolor")
    return out + ["hicolor"]


class IconFinder:
    """name -> best source file (SVG first, then the biggest PNG) along a theme chain, indexed once."""

    def __init__(self, base: str):
        self.files: dict[str, Path] = {}
        for theme in theme_chain(base):
            tdirs = _theme_dirs(theme)
            # one directory list per theme: base dirs without index.theme (e.g. ~/.local/share/icons/hicolor)
            # use the theme's index from another base dir, as the icon spec says
            cp = next((c for c in map(_index, tdirs) if c.has_section("Icon Theme")), None)
            dirs = self._app_dirs(cp) if cp else []
            for tdir in tdirs:
                self._add(tdir, dirs or self._guess_dirs(tdir))
        for d in _data_dirs():                      # last resort, like the icon spec
            pix = d / "pixmaps"
            if pix.is_dir():
                for f in pix.iterdir():
                    if f.suffix in (".svg", ".png"):
                        self.files.setdefault(f.stem, f)

    @staticmethod
    def _app_dirs(cp: configparser.ConfigParser) -> list[str]:
        """App icon dirs of a theme: scalable first, then larger fixed sizes."""
        dirs = []
        sec = cp["Icon Theme"]
        for d in (sec.get("Directories", "") + "," + sec.get("ScaledDirectories", "")).split(","):
            d = d.strip()
            if not d or "symbolic" in d or not cp.has_section(d):
                continue
            if cp[d].get("Context", "") != "Applications" and "/apps" not in f"/{d}" and "apps/" not in d:
                continue
            size = int(cp[d].get("Size", "0") or 0) * int(cp[d].get("Scale", "1") or 1)
            dirs.append((cp[d].get("Type", "Threshold") == "Scalable", size, d))
        return [d for _, _, d in sorted(dirs, key=lambda x: (not x[0], -x[1]))]

    @staticmethod
    def _guess_dirs(tdir: Path) -> list[str]:
        """No index.theme anywhere: <size>/apps and apps/<size> folders, biggest (or scalable) first."""
        found = [str(p.relative_to(tdir)) for p in [*tdir.glob("*/apps"), *tdir.glob("apps/*")] if p.is_dir()]

        def size(d: str) -> int:
            if "scalable" in d:
                return 10_000
            m = re.search(r"(\d+)x\d+", d) or re.search(r"(\d+)", d)
            return int(m.group(1)) if m else 0
        return sorted((d for d in found if "symbolic" not in d), key=size, reverse=True)

    def _add(self, tdir: Path, dirs: list[str]) -> None:
        for d in dirs:
            p = tdir / d
            if not p.is_dir():
                continue
            for f in p.iterdir():
                if f.suffix in (".svg", ".png"):
                    # first theme / base dir / biggest size that has the name wins: the icon the user sees
                    self.files.setdefault(f.stem, f)

    def find(self, name: str) -> Path | None:
        f = self.files.get(name)
        if f is None:
            return None
        try:
            return Path(os.path.realpath(f))
        except OSError:
            return None


# --- the restyling ------------------------------------------------------------------------------

SIZE = 256
PLATE_DISTANCE = 80        # RGB distance within which a color counts as part of the plate


def stops(theme: Theme) -> dict[str, color.RGB]:
    """Plate gradient (top light -> bottom dark graphite) and the rim (accent)."""
    p = theme.palette.resolved()
    acc, surf, fg = color.parse(p.accent), color.parse(p.surface), color.parse(p.foreground)
    if theme.dark:
        top, bottom = color.mix(surf, fg, 0.24), color.mix(surf, (0, 0, 0), 0.25)
    else:
        top, bottom = color.mix(fg, surf, 0.30), color.mix(fg, (0, 0, 0), 0.10)
    return {"plate_top": top, "plate_bottom": color.mix(bottom, acc, 0.06), "rim": acc}


def _lightness(c: color.RGB) -> float:
    return colorsys.rgb_to_hls(*(v / 255 for v in c))[1]


def _dist(a: color.RGB, b: color.RGB) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def find_plate(img) -> color.RGB | None:
    """The icon's background shape (tile, circle, squircle), or None for a free-standing logo.

    First a ring just inside the edges (where a plate shows even under busy artwork), then — for plates the
    ring misses — one color covering most of a mostly-filled icon. `img`: a QImage of the icon.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    n = 48
    small = img.scaled(n, n, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_ARGB32)

    def rgba(x, y):
        px = small.pixel(x, y)
        return (px >> 24) & 0xFF, ((px >> 16) & 0xFF, (px >> 8) & 0xFF, px & 0xFF)

    def biggest_group(colors: list) -> list:
        best: list = []
        for c in colors[:: max(1, len(colors) // 32)]:
            group = [o for o in colors if _dist(o, c) < PLATE_DISTANCE * 0.75]
            if len(group) > len(best):
                best = group
        return best

    def mean(group):
        return tuple(round(sum(v[i] for v in group) / len(group)) for i in range(3))

    every = [c for a, c in (rgba(x, y) for y in range(0, n, 2) for x in range(0, n, 2)) if a >= 200]

    def has_logo(plate) -> bool:
        """Something on it that isn't plate — else the "plate" is the logo itself (a ring, a disc)."""
        other = sum(1 for c in every if _dist(c, plate) >= PLATE_DISTANCE)
        return other >= max(4, len(every) * 0.06)

    ring_pts = []
    for inset in (4, 6, 8):
        lo, hi = inset, n - 1 - inset
        for k in range(lo, hi + 1, 2):
            ring_pts += [(k, lo), (k, hi), (lo, k), (hi, k)]
    ring = [c for a, c in map(lambda p: rgba(*p), ring_pts) if a >= 200]
    if len(ring) >= len(ring_pts) * 0.5:
        g = biggest_group(ring)
        if len(g) >= len(ring) * 0.4 and has_logo(mean(g)):
            return mean(g)

    if len(every) >= (n // 2) ** 2 * 0.45:
        g = biggest_group(every)
        if len(g) >= len(every) * 0.35 and has_logo(mean(g)):
            return mean(g)
    return None


def load(path: Path):
    """Icon file -> SIZE x SIZE ARGB32 QImage (None if unreadable or no Qt)."""
    try:
        from PySide6.QtCore import QByteArray, QRectF, Qt
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        return None
    img = QImage(SIZE, SIZE, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    if path.suffix == ".svg":
        try:
            r = QSvgRenderer(QByteArray(path.read_bytes()))
        except OSError:
            p.end()
            return None
        if not r.isValid():
            p.end()
            return None
        r.render(p, QRectF(0, 0, SIZE, SIZE))
    else:
        src = QImage(str(path))
        if src.isNull():
            p.end()
            return None
        src = src.scaled(SIZE, SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawImage((SIZE - src.width()) // 2, (SIZE - src.height()) // 2, src)
    p.end()
    return img.convertToFormat(QImage.Format_ARGB32)


def _logo_is_dark(img, plate: color.RGB) -> bool:
    """Mostly dark, unsaturated logo pixels (e.g. black on a white tile): they'd vanish on graphite."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    small = img.scaled(48, 48, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_ARGB32)
    ls, ss = [], []
    for y in range(48):
        for x in range(48):
            px = small.pixel(x, y)
            if (px >> 24) & 0xFF < 200:
                continue
            c = ((px >> 16) & 0xFF, (px >> 8) & 0xFF, px & 0xFF)
            if _dist(c, plate) < PLATE_DISTANCE:
                continue
            h, l_, s_ = colorsys.rgb_to_hls(*(v / 255 for v in c))
            ls.append(l_)
            ss.append(s_)
    if len(ls) < 12:
        return False
    return sum(ls) / len(ls) < 0.33 and sum(ss) / len(ss) < 0.35


def restyle(img, st):
    """Plated icon -> graphite gradient plate + accent rim, logo untouched (or flipped light if dark).
    Returns None for a free-standing logo (nothing to restyle)."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, qRgba
    plate = find_plate(img)
    if plate is None:
        return None
    n = img.width()
    out = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    if _logo_is_dark(img, plate):
        out.invertPixels(QImage.InvertRgb)        # black logo -> white (the plate is redrawn on top anyway)

    # soft mask of the plate: per-pixel distance from the plate color (Difference blend, then a ramp)
    diff = img.convertToFormat(QImage.Format_RGB32)
    p = QPainter(diff)
    p.setCompositionMode(QPainter.CompositionMode_Difference)
    p.fillRect(diff.rect(), QColor(*plate))
    p.end()
    dg = diff.convertToFormat(QImage.Format_Grayscale8)
    cut = PLATE_DISTANCE // 2
    mask = QImage(dg.constBits(), dg.width(), dg.height(), dg.bytesPerLine(), QImage.Format_Indexed8).copy()
    mask.setColorTable([qRgba(0, 0, 0, max(0, min(255, round((cut + 10 - g) * 255 / 20)))) for g in range(256)])
    mask = mask.convertToFormat(QImage.Format_ARGB32_Premultiplied)

    # the new plate: graphite gradient where the old plate was
    layer = QImage(n, n, QImage.Format_ARGB32_Premultiplied)
    grad = QLinearGradient(QPointF(0, 0), QPointF(0, n))
    grad.setColorAt(0, QColor(*st["plate_top"]))
    grad.setColorAt(1, QColor(*st["plate_bottom"]))
    p = QPainter(layer)
    p.fillRect(layer.rect(), grad)
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    p.drawImage(0, 0, mask)
    p.end()
    p = QPainter(out)
    p.drawImage(0, 0, layer)
    p.end()

    # accent rim just inside the silhouette: alpha minus a slightly shrunk copy of it
    w = max(2.0, n * 0.03)
    k = (n - 2 * w) / n
    rim = QImage(n, n, QImage.Format_ARGB32_Premultiplied)
    rim.fill(QColor(*st["rim"]))
    p = QPainter(rim)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    p.drawImage(0, 0, img)
    p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
    p.translate(w, w)
    p.scale(k, k)
    p.drawImage(0, 0, img)
    p.end()
    p = QPainter(out)
    p.setOpacity(0.9)
    p.drawImage(0, 0, rim)
    p.setOpacity(1)
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)    # the original's silhouette
    p.drawImage(0, 0, img)
    p.end()
    return out


def svg_wrap(img) -> str:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    data = base64.b64encode(bytes(ba)).decode()
    w, h = img.width(), img.height()
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<image width="{w}" height="{h}" xlink:href="data:image/png;base64,{data}"/></svg>')


def build_into(theme: Theme, out: Path, skip: set[str], only: set[str] | None = None) -> tuple[dict, int]:
    """Write recolored app icons into out/APPS_DIR. Returns ({dir: index keys}, count)."""
    finder = IconFinder(theme.iconset.base)
    names = sorted(only) if only is not None else installed_app_icons()
    st = stops(theme)
    d = out / APPS_DIR
    count = 0
    for name in names:
        if name in skip:
            continue
        src = finder.find(name)
        img = load(src) if src is not None else None
        if img is None:
            continue
        styled = restyle(img, st)
        if styled is None:                      # free-standing logo: the base theme's icon is shown as is
            continue
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.svg").write_text(svg_wrap(styled), encoding="utf-8")
        count += 1
    if not count:
        return {}, 0
    return {APPS_DIR: {"Size": "64", "MinSize": "8", "MaxSize": "512", "Type": "Scalable",
                       "Context": "Applications"}}, count
