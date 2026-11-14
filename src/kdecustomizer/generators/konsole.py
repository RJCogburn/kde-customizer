"""Konsole color scheme + profile — go to ~/.local/share/konsole/."""
from __future__ import annotations

from ..color import lighten, mix, shift, to_kde
from ..spec import Theme

# ANSI slots derived from the palette; hues fixed, tuned toward fg/bg for cohesion.
_ANSI = {
    "Color0": None,          # black  -> background-ish
    "Color1": "#e5534b",     # red
    "Color2": "#57ab5a",     # green
    "Color3": "#c69026",     # yellow
    "Color4": "#539bf5",     # blue
    "Color5": "#b083f0",     # magenta
    "Color6": "#39c5cf",     # cyan
    "Color7": None,          # white  -> foreground-ish
}


def colorscheme(theme: Theme) -> str:
    p = theme.palette.resolved()
    dark = theme.dark
    out = ["[General]", f"Description={theme.name}", "Opacity=1", "Wallpaper=", ""]

    def entry(name, c):
        out.extend([f"[{name}]", f"Color={to_kde(c)}", ""])

    entry("Background", p.background)
    entry("BackgroundIntense", shift(p.background, 0.05, dark))
    entry("Foreground", p.foreground)
    entry("ForegroundIntense", lighten(p.foreground, 0.2) if dark else p.foreground)
    for slot, hue in _ANSI.items():
        if slot == "Color0":
            base = shift(p.background, 0.15, dark)
        elif slot == "Color7":
            base = mix(p.foreground, p.background, 0.15)
        else:
            base = mix(hue, p.foreground, 0.1)
        entry(slot, base)
        entry(slot + "Intense", lighten(base, 0.2))
    return "\n".join(out)


def profile(theme: Theme) -> str:
    font = theme.fonts.fixed or ""
    lines = ["[Appearance]", f"ColorScheme={theme.slug}"]
    if font:
        lines.append(f"Font={_qfont(font)}")
    lines += ["", "[General]", f"Name={theme.name}", "Parent=FALLBACK/", ""]
    return "\n".join(lines)


def _qfont(spec: str) -> str:
    """'Family,10' -> full QFont string Plasma 6 expects."""
    family, _, size = spec.partition(",")
    size = size.strip() or "10"
    return f"{family.strip()},{size},-1,5,400,0,0,0,0,0,0,0,0,0,0,1"
