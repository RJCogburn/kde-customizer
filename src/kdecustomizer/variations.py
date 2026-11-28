"""Nearby palettes to choose from (GUI: Colors › Variations): the accent turned around the color wheel, the
neutrals warmer or cooler, more or less contrast, more or less color. Each one is made readable the way the
light/dark variant is (variant._readable), so every choice passes the contrast check."""
from __future__ import annotations

from dataclasses import replace

from . import color, spec
from .variant import _hex, _hls, _readable

WARM, COOL = 0.08, 0.60          # hues the neutrals lean toward (orange, blue)


def _rotate(c: str, turn: float) -> str:
    h, l, s = _hls(c)
    return _hex((h + turn) % 1.0, l, s)


def _tint(c: str, hue: float, lo: float, hi: float) -> str:
    """A neutral in `hue` (same lightness, saturation kept within lo..hi). Turning the old hue toward the target
    instead would pass through magenta or green on the way."""
    _, l, s = _hls(c)
    return _hex(hue, l, min(hi, max(lo, s)))


def _saturate(c: str, factor: float) -> str:
    h, l, s = _hls(c)
    return _hex(h, l, s * factor)


def _contrast(p: spec.Palette, dark: bool, k: float) -> spec.Palette:
    """k > 0: background/surface and text further apart in lightness, k < 0: closer."""
    away = -1 if dark else 1            # the way the background moves for more contrast (darker on dark themes)

    def shift(c: str, d: float) -> str:
        h, l, s = _hls(c)
        return _hex(h, l + d, s)
    return replace(p, background=shift(p.background, away * k * 0.6), surface=shift(p.surface, away * k * 0.6),
                   foreground=shift(p.foreground, -away * k))


def _fix(p: spec.Palette, dark: bool) -> spec.Palette:
    """Every role readable on its background, like the image palette and the light/dark variant."""
    light = not dark
    fg = p.foreground
    for bg in (p.background, p.surface):
        fg = _readable(fg, bg, 4.5, light)
    return replace(p, foreground=fg,
                   accent=_readable(p.accent, p.background, 3.5, light),
                   positive=_readable(p.positive, p.background, 3.0, light),
                   neutral=_readable(p.neutral, p.background, 3.0, light),
                   negative=_readable(p.negative, p.background, 3.0, light))


def variations(p: spec.Palette) -> list[tuple[str, spec.Palette]]:
    """[(label, palette)] around `p` (link/visited are left to follow the accent)."""
    base = replace(p.resolved(), link="", visited="")
    dark = color.is_dark(base.background)
    out = [
        ("Accent turned left", replace(base, accent=_rotate(base.accent, -1 / 12))),
        ("Accent turned right", replace(base, accent=_rotate(base.accent, 1 / 12))),
        ("Opposite accent", replace(base, accent=_rotate(base.accent, 0.5))),
        ("Warmer", replace(base, background=_tint(base.background, WARM, 0.10, 0.25),
                           surface=_tint(base.surface, WARM, 0.10, 0.22),
                           foreground=_tint(base.foreground, WARM, 0.08, 0.2))),
        ("Cooler", replace(base, background=_tint(base.background, COOL, 0.10, 0.25),
                           surface=_tint(base.surface, COOL, 0.10, 0.22),
                           foreground=_tint(base.foreground, COOL, 0.08, 0.2))),
        ("More contrast", _contrast(base, dark, 0.06)),
        ("Softer", _contrast(base, dark, -0.06)),
        ("More color", replace(base, accent=_saturate(base.accent, 1.35), background=_saturate(base.background, 1.6),
                               surface=_saturate(base.surface, 1.6))),
        ("Less color", replace(base, **{k: _saturate(getattr(base, k), 0.45)
                                        for k in ("background", "surface", "accent")})),
    ]
    seen = {base.background + base.surface + base.foreground + base.accent}
    result = []
    for label, v in out:
        v = _fix(v, dark)
        key = v.background + v.surface + v.foreground + v.accent
        if key not in seen:                     # e.g. "more color" on a pure gray does nothing
            seen.add(key)
            result.append((label, v))
    return result
