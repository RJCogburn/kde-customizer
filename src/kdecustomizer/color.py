"""Small color helpers. Colors are '#rrggbb' strings at the edges, (r, g, b) tuples inside."""
from __future__ import annotations

RGB = tuple[int, int, int]


def parse(hex_color: str) -> RGB:
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"bad color: {hex_color!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def to_hex(c: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*c)


def to_kde(c: RGB | str) -> str:
    """KDE config format: 'r,g,b'."""
    if isinstance(c, str):
        c = parse(c)
    return ",".join(str(v) for v in c)


def mix(a: RGB | str, b: RGB | str, t: float) -> RGB:
    """Linear blend: t=0 -> a, t=1 -> b."""
    a = parse(a) if isinstance(a, str) else a
    b = parse(b) if isinstance(b, str) else b
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


def luminance(c: RGB | str) -> float:
    c = parse(c) if isinstance(c, str) else c

    def ch(v: int) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (ch(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def is_dark(c: RGB | str) -> bool:
    return luminance(c) < 0.25


def lighten(c: RGB | str, t: float) -> RGB:
    return mix(c, (255, 255, 255), t)


def darken(c: RGB | str, t: float) -> RGB:
    return mix(c, (0, 0, 0), t)


def shift(c: RGB | str, t: float, dark: bool) -> RGB:
    """Move a color 'away from the background' — lighter on dark themes, darker on light ones."""
    return lighten(c, t) if dark else darken(c, t)
