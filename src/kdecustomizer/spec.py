"""Theme spec: the single source of truth a theme is built from (TOML on disk)."""
from __future__ import annotations

import re
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from . import color


@dataclass
class Palette:
    background: str = "#1e1f29"
    surface: str = "#282a36"
    foreground: str = "#e6e6f0"
    accent: str = "#7c6cf0"
    positive: str = "#3fb950"
    neutral: str = "#d29922"
    negative: str = "#f85149"
    link: str = ""      # defaults to accent
    visited: str = ""   # defaults to a mix of accent + negative

    def resolved(self) -> "Palette":
        p = Palette(**asdict(self))
        p.link = p.link or p.accent
        p.visited = p.visited or color.to_hex(color.mix(p.accent, p.negative, 0.4))
        return p


@dataclass
class Panel:
    location: str = "bottom"          # top | bottom | left | right
    height: int = 44
    floating: bool = True
    alignment: str = "center"         # left | center | right
    length_mode: str = "fill"         # fill | fit
    widgets: list[str] = field(default_factory=lambda: [
        "org.kde.plasma.kickoff",
        "org.kde.plasma.icontasks",
        "org.kde.plasma.marginsseparator",
        "org.kde.plasma.systemtray",
        "org.kde.plasma.digitalclock",
        "org.kde.plasma.showdesktop",
    ])


@dataclass
class Decoration:
    library: str = "org.kde.breeze"   # installed decoration (ignored if generate)
    theme: str = "Breeze"
    buttons_left: str = "M"           # KWin button codes: M menu, S on-all-desktops, H help,
    buttons_right: str = "IAX"        # I minimize, A maximize, X close, F keep-above, B keep-below
    generate: bool = False            # build an Aurorae title bar from the palette; overrides library/theme
    radius: int = 8                   # top corner radius (px) of generated title bars
    title_height: int = 30            # title bar height (px)
    title_align: str = "center"       # left | center | right
    border: int = 2                   # side/bottom border (px); 0 = borderless
    button_style: str = "glyph"       # glyph (symbols, round hover) | dots (colored circles)

    TITLE_ALIGNS = ("left", "center", "right")
    BUTTON_STYLES = ("glyph", "dots")


@dataclass
class PlasmaStyle:
    generate: bool = False            # build a palette-matched Plasma style; overrides `plasma_style`
    blur: bool = True                 # blur + contrast behind translucent panels/popups
    adaptive_transparency: bool = True  # panels go opaque when a window is maximized
    radius: int = 6                   # corner radius (px) of floating panels, popups, tooltips, desktop widgets
    opacity: float = 0.85             # fill opacity of panels/popups (1.0 = solid); 0.85 = Breeze
    outline: bool = False             # thin edge in the text color around panels and popups

    BREEZE_SHAPE = (6, 0.85, False)   # Breeze's own SVGs already look like this

    @property
    def custom_shapes(self) -> bool:
        """True when the style needs its own SVGs instead of falling back to Breeze's."""
        return (self.radius, round(self.opacity, 3), self.outline) != self.BREEZE_SHAPE


@dataclass
class Widgets:
    generate: bool = False            # build a Kvantum app style from the palette (needs Kvantum installed;
                                      # without it, apps keep `widget_style`)
    radius: int = 4                   # corner radius (px) of buttons, fields, menus, tabs, check boxes


@dataclass
class SplashScreen:
    generate: bool = False            # build a splash screen in the palette; overrides `splash`
    background: str = "gradient"      # gradient | wallpaper (the theme's, dimmed) | solid
    text: str = ""                    # big text in the middle; "" = the theme name

    BACKGROUNDS = ("gradient", "wallpaper", "solid")


@dataclass
class IconSet:
    generate: bool = False            # build an icon theme matched to the palette; overrides `icons`
    base: str = "Papirus-Dark"        # installed SVG icon theme to recolor and inherit from
    signature: str = "none"           # custom "signature" icons on top: none | svg (AI-drawn) | image (local image AI)
    style: str = ""                   # look of the signature icons, e.g. "brushed gold metal, dark glass"
    signature_dir: str = ""           # folder of generated signature icons (relative to the spec file)


@dataclass
class Fonts:
    general: str = ""                 # e.g. "Inter,10" — empty = leave as is
    fixed: str = ""
    small: str = ""
    toolbar: str = ""
    menu: str = ""
    window_title: str = ""


@dataclass
class Theme:
    id: str = "org.kdecustomizer.untitled"
    name: str = "Untitled"
    author: str = ""
    description: str = ""
    version: str = "1.0"
    palette: Palette = field(default_factory=Palette)
    icons: str = "breeze"
    cursors: str = "breeze_cursors"
    widget_style: str = "Breeze"      # Qt style; with [widgets] generate, the fallback when Kvantum is missing
    plasma_style: str = "default"     # installed Plasma style to use (ignored if plasma.generate)
    plasma: PlasmaStyle = field(default_factory=PlasmaStyle)
    iconset: IconSet = field(default_factory=IconSet)
    widgets: Widgets = field(default_factory=Widgets)
    splash: str = "org.kde.Breeze"    # installed splash (ignored if splash_screen.generate)
    splash_screen: SplashScreen = field(default_factory=SplashScreen)
    wallpaper: str = ""               # path to image; copied into the package
    decoration: Decoration = field(default_factory=Decoration)
    fonts: Fonts = field(default_factory=Fonts)
    panels: list[Panel] = field(default_factory=lambda: [Panel()])
    konsole: bool = True
    # Arbitrary config writes applied at install time: {file: {group: {key: value}}}
    # Nested groups use "/" — e.g. "Plugins" or "Effect-blur".
    tweaks: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)

    @property
    def dark(self) -> bool:
        return color.is_dark(self.palette.background)

    @property
    def slug(self) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "", self.name.title()) or "Untitled"

    @property
    def plasma_style_name(self) -> str:
        """The Plasma style actually applied: our generated one, or the named installed one."""
        return self.slug if self.plasma.generate else self.plasma_style

    @property
    def decoration_name(self) -> str:
        """Folder name of the generated Aurorae theme."""
        return f"{self.slug}-Decoration"

    @property
    def decoration_kwin(self) -> tuple[str, str]:
        """(library, theme) as KWin's kwinrc [org.kde.kdecoration2] wants them."""
        if self.decoration.generate:
            return "org.kde.kwin.aurorae", f"__aurorae__svg__{self.decoration_name}"
        return self.decoration.library, self.decoration.theme

    @property
    def splash_name(self) -> str:
        """The splash actually used: our Look-and-Feel package's own, or the named installed one."""
        return self.id if self.splash_screen.generate else self.splash

    @property
    def kvantum_name(self) -> str:
        """Folder/theme name of the generated Kvantum theme."""
        return self.slug

    @property
    def icons_name(self) -> str:
        """The icon theme actually applied: our generated one, or the named installed one."""
        return f"{self.slug}-Icons" if self.iconset.generate else self.icons


def _build(cls, data: dict[str, Any]):
    known = {f.name: f for f in fields(cls)}
    unknown = set(data) - set(known)
    if unknown:
        raise ValueError(f"unknown keys in [{cls.__name__.lower()}]: {', '.join(sorted(unknown))}")
    return cls(**data)


def from_dict(data: dict[str, Any]) -> Theme:
    data = dict(data)
    sub = {
        "palette": lambda d: _build(Palette, d),
        "decoration": lambda d: _build(Decoration, d),
        "fonts": lambda d: _build(Fonts, d),
        "plasma": lambda d: _build(PlasmaStyle, d),
        "iconset": lambda d: _build(IconSet, d),
        "widgets": lambda d: _build(Widgets, d),
        "splash_screen": lambda d: _build(SplashScreen, d),
        "panels": lambda lst: [_build(Panel, p) for p in lst],
    }
    for key, fn in sub.items():
        if key in data:
            data[key] = fn(data[key])
    theme = _build(Theme, data)
    p = theme.plasma
    if not 0 <= p.radius <= 32:
        raise ValueError(f"[plasma] radius must be 0..32, got {p.radius}")
    if not 0.3 <= p.opacity <= 1.0:
        raise ValueError(f"[plasma] opacity must be 0.3..1.0, got {p.opacity}")
    if theme.splash_screen.background not in SplashScreen.BACKGROUNDS:
        raise ValueError(f"[splash_screen] background must be one of {', '.join(SplashScreen.BACKGROUNDS)}")
    if not 0 <= theme.widgets.radius <= 12:
        raise ValueError(f"[widgets] radius must be 0..12, got {theme.widgets.radius}")
    d = theme.decoration
    if d.title_align not in d.TITLE_ALIGNS:
        raise ValueError(f"[decoration] title_align must be one of {', '.join(d.TITLE_ALIGNS)}")
    if d.button_style not in d.BUTTON_STYLES:
        raise ValueError(f"[decoration] button_style must be one of {', '.join(d.BUTTON_STYLES)}")
    if not 20 <= d.title_height <= 60:
        raise ValueError(f"[decoration] title_height must be 20..60, got {d.title_height}")
    if not 0 <= d.radius <= min(16, d.title_height // 2):
        raise ValueError(f"[decoration] radius must be 0..{min(16, d.title_height // 2)}, got {d.radius}")
    if not 0 <= d.border <= 12:
        raise ValueError(f"[decoration] border must be 0..12, got {d.border}")
    return theme


def load(path: str | Path) -> Theme:
    path = Path(path)
    with path.open("rb") as f:
        theme = from_dict(tomllib.load(f))
    if theme.wallpaper:
        wp = Path(theme.wallpaper).expanduser()
        if not wp.is_absolute():
            wp = path.parent / wp
        theme.wallpaper = str(wp.resolve())
    if theme.iconset.signature_dir:
        sd = Path(theme.iconset.signature_dir).expanduser()
        theme.iconset.signature_dir = str((sd if sd.is_absolute() else path.parent / sd).resolve())
    for c in asdict(theme.palette).values():
        if c:
            color.parse(c)  # validate early
    return theme


# --- minimal TOML writer (stdlib has no tomllib.dump) -------------------------

def _val(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_val(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def _key(k: str) -> str:
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else _val(k)


def dumps(theme: Theme) -> str:
    d = asdict(theme)
    out: list[str] = []
    tables: dict[str, dict] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            tables[k] = v
        elif k == "panels":
            continue
        else:
            out.append(f"{_key(k)} = {_val(v)}")
    for name in ("palette", "plasma", "iconset", "widgets", "decoration", "splash_screen", "fonts"):
        out.append(f"\n[{name}]")
        out += [f"{_key(k)} = {_val(v)}" for k, v in tables[name].items()]
    for p in d["panels"]:
        out.append("\n[[panels]]")
        out += [f"{_key(k)} = {_val(v)}" for k, v in p.items()]
    for file, groups in d["tweaks"].items():
        for group, kv in groups.items():
            out.append(f"\n[tweaks.{_key(file)}.{_key(group)}]")
            out += [f"{_key(k)} = {_val(v)}" for k, v in kv.items()]
    return "\n".join(out) + "\n"


def save(theme: Theme, path: str | Path) -> None:
    Path(path).write_text(dumps(theme))
