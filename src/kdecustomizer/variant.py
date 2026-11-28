"""The opposite (light <-> dark) variant of a theme, for `[light_dark] auto`: same hues, same parts and settings,
lightness flipped. Plasma switches between the two Look-and-Feel packages by time of day (Night Light schedule)."""
from __future__ import annotations

import colorsys
import copy

from . import color, spec, system

# icon themes with a known partner for the other brightness
_ICON_PAIRS = {"Papirus-Dark": "Papirus", "breeze-dark": "breeze", "Adwaita-dark": "Adwaita",
               "Tela-dark": "Tela", "Qogir-dark": "Qogir", "Fluent-dark": "Fluent", "Colloid-dark": "Colloid"}


def _hls(c: str) -> tuple[float, float, float]:
    r, g, b = color.parse(c)
    return colorsys.rgb_to_hls(r / 255, g / 255, b / 255)


def _hex(h: float, l: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return color.to_hex((round(r * 255), round(g * 255), round(b * 255)))


def _readable(c: str, bg: str, need: float, to_light: bool) -> str:
    """Same hue and saturation, lightness moved (darker on a light background) until it reads on `bg`."""
    h, l, s = _hls(c)
    for _ in range(60):
        if color.contrast(_hex(h, l, s), bg) >= need:
            break
        l += -0.015 if to_light else 0.015
    return _hex(h, l, s)


def palette(p: spec.Palette) -> spec.Palette:
    """The opposite palette: lightness flipped, hues kept, accent and status colors moved until readable."""
    r = p.resolved()
    to_light = color.is_dark(r.background)
    bh, bl, bs = _hls(r.background)
    sh, sl, ss = _hls(r.surface)
    fh, fl, fs = _hls(r.foreground)
    if to_light:
        bg = _hex(bh, 0.95, min(bs, 0.35))
        surface = _hex(sh, 0.95 - max(0.025, abs(sl - bl)), min(ss, 0.3))
        fg = _hex(fh, 0.13, min(fs, 0.35))
    else:
        bg = _hex(bh, 0.11, min(bs, 0.3))
        surface = _hex(sh, 0.11 + max(0.025, abs(sl - bl)), min(ss, 0.25))
        fg = _hex(fh, 0.91, min(fs, 0.25))
    out = spec.Palette(background=bg, surface=surface, foreground=fg,
                       accent=_readable(r.accent, bg, 3.5, to_light),
                       positive=_readable(r.positive, bg, 3.0, to_light),
                       neutral=_readable(r.neutral, bg, 3.0, to_light),
                       negative=_readable(r.negative, bg, 3.0, to_light))
    if p.link:
        out.link = _readable(p.link, bg, 4.5, to_light)
    if p.visited:
        out.visited = _readable(p.visited, bg, 4.5, to_light)
    return out


def _icons(name: str, installed: list[str]) -> str:
    pairs = {**_ICON_PAIRS, **{v: k for k, v in _ICON_PAIRS.items()}}
    other = pairs.get(name)
    if other is None:                    # generic: Foo-dark <-> Foo
        low = name.lower()
        other = name[:-5] if low.endswith("-dark") else name + "-dark"
    have = {n.lower(): n for n in installed}
    return have.get(other.lower(), name) if installed else name


def is_light(theme: spec.Theme) -> bool:
    return not color.is_dark(theme.palette.resolved().background)


def opposite(theme: spec.Theme) -> spec.Theme:
    """The theme with a flipped palette, its own name/id ("<Name> Light" / "<Name> Dark"), auto off."""
    v = copy.deepcopy(theme)
    v.palette = palette(theme.palette)
    v.name = f"{theme.name} {'Light' if is_light(v) else 'Dark'}"
    v.id = spec.id_for(v.name)
    v.light_dark.auto = False
    installed = system.summary().get("icons", [])
    if v.iconset.generate:
        v.iconset.base = _icons(v.iconset.base, installed)
    else:
        v.icons = _icons(v.icons, installed)
    return v


def pair(theme: spec.Theme) -> tuple[spec.Theme, spec.Theme]:
    """(light, dark) — the theme and its variant in that order."""
    v = opposite(theme)
    return (v, theme) if is_light(v) else (theme, v)
