"""A readable palette taken from an image (usually the wallpaper).

The image is sampled down to a few thousand pixels and clustered (k-means in RGB). The biggest cluster gives the
background's hue, the most colorful sizeable cluster the accent; lightness is then set the way the light/dark
variant does it (variant.py), and every color is moved until it reads on the background. Dark or light follows the
image's average brightness unless asked.
"""
from __future__ import annotations

import colorsys
import random
from pathlib import Path

from . import color, spec
from .variant import _hex, _hls, _readable

SAMPLES = 4096


def pixels(path: str | Path) -> list[tuple[int, int, int]]:
    """RGB samples of the image, via Qt (always there with the GUI) or Pillow."""
    path = str(Path(path).expanduser())
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage
        img = QImage(path)
        if img.isNull():
            raise ValueError(f"can't read image {path}")
        img = img.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_RGB32)
        out = []
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixel(x, y)
                out.append(((c >> 16) & 255, (c >> 8) & 255, c & 255))
        return out
    except ImportError:
        pass
    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError("reading images needs PySide6 or Pillow") from e
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((96, 96))
        return list(im.getdata())


def _kmeans(px: list[tuple[int, int, int]], k: int = 6, rounds: int = 12) -> list[tuple[tuple[float, ...], int]]:
    """[(center, size)] biggest first."""
    rnd = random.Random(7)                       # same image -> same palette
    pts = px if len(px) <= SAMPLES else rnd.sample(px, SAMPLES)
    centers = [tuple(map(float, c)) for c in rnd.sample(pts, min(k, len(pts)))]
    groups: list[list] = []
    for _ in range(rounds):
        groups = [[] for _ in centers]
        for p in pts:
            i = min(range(len(centers)), key=lambda j: sum((p[n] - centers[j][n]) ** 2 for n in range(3)))
            groups[i].append(p)
        centers = [tuple(sum(p[n] for p in g) / len(g) for n in range(3)) if g else centers[i]
                   for i, g in enumerate(groups)]
    out = [(centers[i], len(g)) for i, g in enumerate(groups) if g]
    return sorted(out, key=lambda cs: -cs[1])


def _rgb_hex(c) -> str:
    return color.to_hex(tuple(max(0, min(255, round(v))) for v in c))


def extract(px: list[tuple[int, int, int]], dark: bool | None = None,
            base: spec.Palette | None = None) -> spec.Palette:
    """Palette from RGB samples. `base` supplies the status colors' hues (default: the spec's)."""
    if not px:
        raise ValueError("no pixels")
    base = base or spec.Palette()
    clusters = _kmeans(px)
    total = sum(n for _, n in clusters)
    if dark is None:
        avg = sum(colorsys.rgb_to_hls(*(v / 255 for v in c))[1] * n for c, n in clusters) / total
        dark = avg < 0.55

    # background hue: the biggest cluster on the theme's side of the image (dark clusters for a dark theme)
    side = [cn for cn in clusters if (colorsys.rgb_to_hls(*(v / 255 for v in cn[0]))[1] < 0.6) == dark]
    bh, _, bs = _hls(_rgb_hex((side or clusters)[0][0]))
    if dark:
        bg = _hex(bh, 0.11, min(bs, 0.3))
        surface = _hex(bh, 0.15, min(bs, 0.25))
        fg = _hex(bh, 0.91, min(bs, 0.2))
    else:
        bg = _hex(bh, 0.95, min(bs, 0.35))
        surface = _hex(bh, 0.91, min(bs, 0.3))
        fg = _hex(bh, 0.13, min(bs, 0.3))

    # accent: the most colorful cluster that isn't a speck; hue far enough from the background helps
    def score(cn):
        h, l, s = _hls(_rgb_hex(cn[0]))
        share = cn[1] / total
        if share < 0.02 or l < 0.08 or l > 0.95:
            return -1.0
        far = min(abs(h - bh), 1 - abs(h - bh)) * 2          # 0 = same hue, 1 = opposite
        return s * (share ** 0.35) * (0.7 + 0.3 * far)
    best = max(clusters, key=score)
    ah, _, as_ = _hls(_rgb_hex(best[0]))
    if score(best) <= 0 or as_ < 0.2:                    # a gray image: keep the current accent's hue
        ah, _, as_ = _hls(base.accent)
    accent = _hex(ah, 0.66 if dark else 0.42, max(as_, 0.6))

    to_light = not dark
    return spec.Palette(background=bg, surface=surface, foreground=fg,
                        accent=_readable(accent, bg, 3.5, to_light),
                        positive=_readable(base.positive, bg, 3.0, to_light),
                        neutral=_readable(base.neutral, bg, 3.0, to_light),
                        negative=_readable(base.negative, bg, 3.0, to_light))


def from_image(path: str | Path, dark: bool | None = None, base: spec.Palette | None = None) -> spec.Palette:
    return extract(pixels(path), dark, base)
