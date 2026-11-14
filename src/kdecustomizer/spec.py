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
    library: str = "org.kde.breeze"
    theme: str = "Breeze"
    buttons_left: str = "M"           # KWin button codes: M menu, S on-all-desktops, H help,
    buttons_right: str = "IAX"        # I minimize, A maximize, X close, F keep-above, B keep-below


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
    widget_style: str = "Breeze"      # Qt style; "kvantum" once a Kvantum theme is generated
    plasma_style: str = "default"     # Plasma desktop theme name
    splash: str = "org.kde.Breeze"
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
        "panels": lambda lst: [_build(Panel, p) for p in lst],
    }
    for key, fn in sub.items():
        if key in data:
            data[key] = fn(data[key])
    return _build(Theme, data)


def load(path: str | Path) -> Theme:
    path = Path(path)
    with path.open("rb") as f:
        theme = from_dict(tomllib.load(f))
    if theme.wallpaper:
        wp = Path(theme.wallpaper).expanduser()
        if not wp.is_absolute():
            wp = path.parent / wp
        theme.wallpaper = str(wp)
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
    for name in ("palette", "decoration", "fonts"):
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
