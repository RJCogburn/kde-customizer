"""Plasma 6 Global Theme (Look-and-Feel) package."""
from __future__ import annotations

import json

from ..spec import Theme


def metadata(theme: Theme) -> str:
    return json.dumps({
        "KPackageStructure": "Plasma/LookAndFeel",
        "KPlugin": {
            "Id": theme.id,
            "Name": theme.name,
            "Description": theme.description or f"{theme.name} — built with kde-customizer",
            "Authors": [{"Name": theme.author or "Unknown"}],
            "License": "GPL-2.0+",
            "Version": theme.version,
            "Category": "",
        },
        "X-Plasma-APIVersion": "2",
        "X-KDE-Customizer-Slug": theme.slug,     # marks our packages for `kdec installed` / the theme manager
    }, indent=2) + "\n"


def defaults(theme: Theme) -> str:
    """contents/defaults — the keys plasma-apply-lookandfeel knows how to apply."""
    lib, deco = theme.decoration_kwin
    return "\n".join([
        "[kdeglobals][KDE]", f"widgetStyle={theme.widget_style}", "",
        "[kdeglobals][General]", f"ColorScheme={theme.slug}", "",
        "[kdeglobals][Icons]", f"Theme={theme.icons_name}", "",
        "[plasmarc][Theme]", f"name={theme.plasma_style_name}", "",
        "[kcminputrc][Mouse]", f"cursorTheme={theme.cursors_name}", "",
        "[kwinrc][org.kde.kdecoration2]", f"library={lib}", f"theme={deco}", "",
        "[ksplashrc][KSplash]", f"Theme={theme.splash_name}", "",
    ])
