"""KDE color scheme (.colors) generator — goes to ~/.local/share/color-schemes/."""
from __future__ import annotations

from ..color import RGB, luminance, mix, shift, to_kde
from ..spec import Theme


def scheme(theme: Theme) -> dict[str, dict[str, RGB | str]]:
    """Every color role, derived from the palette. Used by generate() and the GUI preview."""
    p = theme.palette.resolved()
    dark = theme.dark
    bg, surf, fg, acc = p.background, p.surface, p.foreground, p.accent

    view_bg = shift(bg, 0.03, dark)
    on_accent = (255, 255, 255) if luminance(acc) < 0.4 else (0, 0, 0)

    def role(back, alt, fore, inactive_t=0.45):
        return {
            "BackgroundNormal": back,
            "BackgroundAlternate": alt,
            "DecorationFocus": acc,
            "DecorationHover": shift(acc, 0.2, dark),
            "ForegroundActive": acc,
            "ForegroundInactive": mix(fore, back, inactive_t),
            "ForegroundLink": p.link,
            "ForegroundNegative": p.negative,
            "ForegroundNeutral": p.neutral,
            "ForegroundNormal": fore,
            "ForegroundPositive": p.positive,
            "ForegroundVisited": p.visited,
        }

    sections = {
        "Colors:Button": role(surf, shift(surf, 0.04, dark), fg),
        "Colors:Complementary": role(bg, surf, fg),
        "Colors:Header": role(surf, bg, fg),
        "Colors:Header][Inactive": role(bg, surf, fg),
        "Colors:Selection": {
            **role(acc, shift(acc, 0.1, dark), on_accent, 0.3),
            "ForegroundActive": on_accent,
            "ForegroundLink": on_accent,
            "ForegroundVisited": on_accent,
        },
        "Colors:Tooltip": role(surf, bg, fg),
        "Colors:View": role(view_bg, shift(view_bg, 0.03, dark), fg),
        "Colors:Window": role(bg, surf, fg),
        "WM": {
            "activeBackground": surf,
            "activeBlend": fg,
            "activeForeground": fg,
            "inactiveBackground": bg,
            "inactiveBlend": mix(fg, bg, 0.45),
            "inactiveForeground": mix(fg, bg, 0.45),
        },
    }
    return sections


def generate(theme: Theme) -> str:
    sections = scheme(theme)
    bg = theme.palette.background

    lines: list[str] = [
        "[ColorEffects:Disabled]",
        f"Color={to_kde(bg)}", "ColorAmount=0", "ColorEffect=0",
        "ContrastAmount=0.65", "ContrastEffect=1",
        "IntensityAmount=0.1", "IntensityEffect=2",
        "",
        "[ColorEffects:Inactive]",
        "ChangeSelectionColor=true",
        f"Color={to_kde(bg)}", "ColorAmount=0.025", "ColorEffect=2",
        "ContrastAmount=0.1", "ContrastEffect=2",
        "Enable=false", "IntensityAmount=0", "IntensityEffect=0",
        "",
    ]
    for name, keys in sections.items():
        if name == "WM":
            continue
        lines.append(f"[{name}]")
        lines += [f"{k}={to_kde(v)}" for k, v in keys.items()]
        lines.append("")
    lines += [
        "[General]",
        f"ColorScheme={theme.slug}",
        f"Name={theme.name}",
        "shadeSortColumn=true",
        "",
        "[KDE]",
        "contrast=4",
        "",
        "[WM]",
        *[f"{k}={to_kde(v)}" for k, v in sections["WM"].items()],
        "",
    ]
    return "\n".join(lines)
