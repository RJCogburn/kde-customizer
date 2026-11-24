"""Generated cursor theme `<Slug>-Cursors` = an installed SVG cursor theme recolored to the palette.

Plasma 6 cursor themes carry two copies of every cursor:
- `cursors_scalable/<name>/` — SVG frames + `metadata.json` (hotspot in SVG pixels, nominal size,
  frame delay). KWin draws these on Wayland at any scale.
- `cursors/<name>` — Xcursor binaries for X11 / XWayland apps.

Recoloring works on the SVGs: the cursor body (Breeze leaves it unfilled = black) becomes `fill`,
grays slide between body and outline by lightness, and colored details map to palette roles.
The Xcursors are then rendered from the recolored SVGs with QtSvg (PySide6). Without PySide6 the
base's Xcursors are copied unchanged, so X11 apps keep the base look.
"""
from __future__ import annotations

import colorsys
import json
import os
import re
import shutil
import struct
from pathlib import Path

from . import color
from .spec import Theme

# Xcursor nominal sizes written (Breeze ships 12..72 in steps of 6; 96 for big HiDPI pointers)
XCURSOR_SIZES = [24, 30, 36, 48, 60, 72, 96]
_HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_SVG_TAG = re.compile(r"<svg\b[^>]*>")
_FILTERED = re.compile(r"<(path|circle|ellipse|rect|use|g|polygon)\b(?![^>]*\bfill=)([^>]*\bfilter=[^>]*?)(/?)>")


def find_dir(name: str) -> Path | None:
    from . import iconset
    return iconset.find_theme_dir(name)


def scalable_themes() -> list[str]:
    """Installed cursor themes with SVG cursors (the ones we can recolor)."""
    from . import system
    out = []
    for name in system.cursor_themes():
        d = find_dir(name)
        if d and (d / "cursors_scalable").is_dir():
            out.append(name)
    return sorted(set(out), key=str.lower)


def colors(theme: Theme) -> dict[str, str]:
    """Palette roles the cursors are painted in: body, outline, accent, accent2, and status colors."""
    p = theme.palette.resolved()
    bg, fg, acc = p.background, p.foreground, p.accent
    fill = theme.cursorset.fill
    if fill == "foreground":
        body, outline, far = fg, bg, fg
    elif fill == "accent":
        body = acc
        outline, far = (bg, fg) if color.contrast(acc, bg) >= color.contrast(acc, fg) else (fg, bg)
    else:
        body, outline, far = bg, fg, bg
    # colored details (spinner, badges) sit on outline-colored discs: the 2nd spinner color moves away from it
    return {
        "body": body, "outline": outline,
        "accent": acc, "accent2": color.to_hex(color.mix(acc, far, 0.4)),
        "negative": p.negative, "neutral": p.neutral, "positive": p.positive,
    }


# Breeze's exact colors -> role; anything else is classified by hue/lightness.
_KNOWN = {
    "#46a7ac": "accent", "#3daee9": "accent", "#d4497f": "accent2",
    "#ed1515": "negative", "#f67400": "neutral", "#18c087": "positive", "#11d116": "positive",
}


def _recolorer(c: dict[str, str]):
    body, outline = color.parse(c["body"]), color.parse(c["outline"])

    def sub(m: re.Match) -> str:
        h = m.group(1).lower()
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        role = _KNOWN.get("#" + h)
        if role:
            return c[role]
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        hue, light, sat = colorsys.rgb_to_hls(r, g, b)
        if sat < 0.25 or light < 0.08 or light > 0.95:     # gray: between body (dark) and outline (light)
            return color.to_hex(color.mix(body, outline, light))
        deg = hue * 360
        if deg < 25 or deg >= 345:
            return c["negative"]
        if deg < 65:
            return c["neutral"]
        if deg < 160:
            return c["positive"]
        return c["accent"]

    return sub


def recolor_svg(text: str, c: dict[str, str]) -> str:
    text = _HEX.sub(_recolorer(c), text)
    # shadows: unfilled + blurred -> keep them black when the root gets a default fill below
    text = _FILTERED.sub(lambda m: f'<{m.group(1)} fill="#000"{m.group(2)}{m.group(3)}>', text)
    # unfilled shapes (Breeze's cursor bodies) inherit the root's fill
    return _SVG_TAG.sub(lambda m: m.group(0)[:-1].rstrip("/") + f' fill="{c["body"]}">', text, count=1)


def preview_svg(theme: Theme, name: str = "default") -> tuple[str, dict] | None:
    """(svg text, first frame's metadata) of one cursor as the theme will show it, or None."""
    gen = theme.cursorset.generate
    d = find_dir(theme.cursorset.base if gen else theme.cursors)
    src = d / "cursors_scalable" / name if d else None
    if not src or not (src / "metadata.json").is_file():
        return None
    frame = json.loads((src / "metadata.json").read_text())[0]
    text = (src / frame["filename"]).read_text()
    return (recolor_svg(text, colors(theme)) if gen else text), frame


# --- Xcursor ------------------------------------------------------------------

def _renderer():
    """(svg_bytes, size_px) -> premultiplied ARGB32 little-endian bytes, or None without QtSvg."""
    try:
        from PySide6.QtCore import QByteArray, QRectF, Qt
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        return None

    def render(svg: bytes, w: int, h: int) -> bytes:
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        QSvgRenderer(QByteArray(svg)).render(p, QRectF(0, 0, w, h))
        p.end()
        # ARGB32 in memory is the 32-bit pixel in native (little-endian) order = what Xcursor stores
        return bytes(img.constBits())[: w * h * 4]

    return render


def _svg_size(text: str) -> tuple[float, float]:
    tag = _SVG_TAG.search(text).group(0)
    w = re.search(r'\bwidth="([\d.]+)', tag)
    h = re.search(r'\bheight="([\d.]+)', tag)
    if w and h:
        return float(w.group(1)), float(h.group(1))
    vb = re.search(r'viewBox="[\d.\-]+[ ,]+[\d.\-]+[ ,]+([\d.]+)[ ,]+([\d.]+)', tag)
    return (float(vb.group(1)), float(vb.group(2))) if vb else (32.0, 32.0)


def xcursor(frames: list[dict], svgs: dict[str, str], render) -> bytes:
    """Xcursor file for one cursor: every frame at every size in XCURSOR_SIZES."""
    images = []
    for size in XCURSOR_SIZES:
        for fr in frames:
            text = svgs[fr["filename"]]
            sw, sh = _svg_size(text)
            k = size / fr.get("nominal_size", 24)
            w, h = max(1, round(sw * k)), max(1, round(sh * k))
            hx = min(w - 1, int(fr.get("hotspot_x", 0) * k))
            hy = min(h - 1, int(fr.get("hotspot_y", 0) * k))
            pixels = render(text.encode(), w, h)
            images.append(struct.pack("<9I", 36, 0xFFFD0002, size, 1, w, h, hx, hy,
                                      int(fr.get("delay", 50))) + pixels)
    header = struct.pack("<4sIII", b"Xcur", 16, 0x10000, len(images))
    pos = 16 + 12 * len(images)
    toc = b""
    for size_img, img in zip([s for s in XCURSOR_SIZES for _ in frames], images):
        toc += struct.pack("<III", 0xFFFD0002, size_img, pos)
        pos += len(img)
    return header + toc + b"".join(images)


# --- build --------------------------------------------------------------------

def build(theme: Theme, out_root: Path) -> Path:
    """Write `<out_root>/<Slug>-Cursors/`. Returns that directory."""
    base = find_dir(theme.cursorset.base)
    if not base or not (base / "cursors_scalable").is_dir():
        raise ValueError(f"[cursorset] base '{theme.cursorset.base}' is not an installed cursor theme with SVG "
                         f"cursors; pick one of: {', '.join(scalable_themes()) or '(none found)'}")
    out = out_root / theme.cursors_name
    if out.exists():
        shutil.rmtree(out)
    (out / "cursors_scalable").mkdir(parents=True)
    (out / "cursors").mkdir()
    c = colors(theme)
    render = _renderer()
    src = base / "cursors_scalable"

    for entry in sorted(src.iterdir()):
        if entry.is_symlink():                              # aliases: keep them as relative links
            target = os.readlink(entry)
            os.symlink(target, out / "cursors_scalable" / entry.name)
            os.symlink(Path(target).name, out / "cursors" / entry.name)
            continue
        if not entry.is_dir() or not (entry / "metadata.json").is_file():
            continue
        dest = out / "cursors_scalable" / entry.name
        dest.mkdir()
        svgs = {}
        for f in sorted(entry.iterdir()):
            if f.suffix == ".svg":
                svgs[f.name] = recolor_svg(f.read_text(), c)
                (dest / f.name).write_text(svgs[f.name])
            elif f.is_file():
                shutil.copy2(f, dest / f.name)
        frames = json.loads((entry / "metadata.json").read_text())
        if render:
            (out / "cursors" / entry.name).write_bytes(xcursor(frames, svgs, render))
        elif (base / "cursors" / entry.name).is_file():
            shutil.copy2(base / "cursors" / entry.name, out / "cursors" / entry.name)

    # drop dangling links (an alias whose target the base only ships in one of the two forms)
    for sub in ("cursors", "cursors_scalable"):
        for f in (out / sub).iterdir():
            if f.is_symlink() and not f.exists():
                f.unlink()

    (out / "index.theme").write_text(
        "[Icon Theme]\n"
        f"Name={theme.name} Cursors\n"
        f"Comment=Generated by kde-customizer from {theme.cursorset.base}\n"
        f"Inherits={theme.cursorset.base}\n")
    return out
