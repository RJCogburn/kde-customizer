"""Themes that kde-customizer has installed for this user: listing them and removing one with all its parts.

A theme's Look-and-Feel package is ours when its metadata has `X-KDE-Customizer-Slug` (or, from older versions,
an `org.kdecustomizer.*` id). Its other parts are found by the names install.sh gives them (see build.py):
<Slug>.colors, the <Slug> Plasma style, <Slug>-Icons, <Slug>-Cursors, <Slug>-Decoration, the <Slug> Kvantum theme,
Konsole's <Slug>.colorscheme/.profile, wallpapers/<Slug>. The light/dark variant ("<Name> Light|Dark") is listed
under its theme and removed with it. A theme the desktop is using can't be removed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

PREFIX = "org.kdecustomizer."


def _data() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")


def _conf() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _state() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")


def _cache() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")


def read_kconfig(path: Path) -> dict[str, dict[str, str]]:
    """Tiny KConfig reader: {"Group" or "Group][Sub": {key: value}}; `key[$e]` flags are dropped."""
    out: dict[str, dict[str, str]] = {}
    group = None
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
            out.setdefault(group, {})
        elif group is not None and "=" in line:
            k, _, v = line.partition("=")
            out[group][re.sub(r"\[\$\w+\]$", "", k.strip())] = v.strip()
    return out


def _setting(file: str, group: str, key: str) -> str:
    """The user's value, else the one in ~/.config/kdedefaults (what plasma-apply-lookandfeel writes)."""
    for path in (_conf() / file, _conf() / "kdedefaults" / file):
        v = read_kconfig(path).get(group, {}).get(key)
        if v:
            return v
    return ""


@dataclass
class Installed:
    """One installed theme (its Look-and-Feel package) and its light/dark variants."""

    id: str
    name: str
    slug: str
    package: Path                   # the Look-and-Feel package dir
    variants: list["Installed"] = field(default_factory=list)

    def parts(self) -> list[Path]:
        """Every file/dir of this theme (and its variants) that exists."""
        d, c, s = _data(), _conf(), self.slug
        cands = [
            self.package,
            d / "color-schemes" / f"{s}.colors",
            d / "konsole" / f"{s}.colorscheme",
            d / "konsole" / f"{s}.profile",
            d / "icons" / f"{s}-Icons",
            d / "icons" / f"{s}-Cursors",
            d / "aurorae" / "themes" / f"{s}-Decoration",
            d / "wallpapers" / s,
            d / "kde-customizer" / "follow" / self.id,
            _state() / "kde-customizer" / f"login-{s}",
            _state() / "kde-customizer" / f"boot-{s}",
            _state() / "kde-customizer" / f"installed-{s}",
        ]
        style = d / "plasma" / "desktoptheme" / s
        if "kde-customizer" in _text(style / "metadata.json"):      # never someone else's style of that name
            cands.append(style)
        kv = c / "Kvantum" / s
        if (kv / f"{s}.kvconfig").is_file() and (kv / f"{s}.svg").is_file():
            cands.append(kv)
        found = [p for p in cands if p.exists() or p.is_symlink()]
        for v in self.variants:
            found += [p for p in v.parts() if p not in found]
        return found

    def in_use(self) -> list[str]:
        """Why this theme can't be removed right now (empty = it can)."""
        why = []
        ids = {self.id} | {v.id for v in self.variants}
        slugs = {self.slug} | {v.slug for v in self.variants}
        if _setting("kdeglobals", "KDE", "LookAndFeelPackage") in ids:
            why.append("it is the current global theme")
        if _setting("kdeglobals", "KDE", "AutomaticLookAndFeel").lower() == "true" and (
                {_setting("kdeglobals", "KDE", "DefaultLightLookAndFeel"),
                 _setting("kdeglobals", "KDE", "DefaultDarkLookAndFeel")} & ids):
            why.append("light/dark switching uses it")
        if _setting("kdeglobals", "General", "ColorScheme") in slugs:
            why.append("its color scheme is in use")
        if _setting("plasmarc", "Theme", "name") in slugs:
            why.append("its Plasma style is in use")
        return why


def _text(p: Path) -> str:
    try:
        return p.read_text(errors="replace")
    except OSError:
        return ""


def _package(d: Path) -> Installed | None:
    """An Installed for a Look-and-Feel folder if kde-customizer made it, else None."""
    try:
        meta = json.loads((d / "metadata.json").read_text())
    except (OSError, ValueError):
        return None
    plugin = meta.get("KPlugin", {})
    pid = plugin.get("Id") or d.name
    slug = meta.get("X-KDE-Customizer-Slug")
    if not slug:
        if not pid.startswith(PREFIX):
            return None
        defaults = read_kconfig(d / "contents" / "defaults")
        slug = defaults.get("kdeglobals][General", {}).get("ColorScheme", "")
    if not slug:
        return None
    return Installed(pid, plugin.get("Name") or slug, slug, d)


def themes() -> list[Installed]:
    """Our installed themes by name; a "<Name> Light|Dark" package of another one is listed as its variant."""
    root = _data() / "plasma" / "look-and-feel"
    found = [t for d in sorted(root.iterdir()) if d.is_dir() and (t := _package(d))] if root.is_dir() else []
    by_name = {t.name: t for t in found}
    out = []
    for t in found:
        base = re.sub(r" (Light|Dark)$", "", t.name)
        parent = by_name.get(base) if base != t.name else None
        if parent and parent is not t:
            parent.variants.append(t)
        else:
            out.append(t)
    return sorted(out, key=lambda t: t.name.lower())


def stamp(theme: Installed) -> str:
    """The spec fingerprint (build.spec_hash) install.sh recorded for it; "" from versions before 0.1.25."""
    try:
        return (_state() / "kde-customizer" / f"installed-{theme.slug}").read_text().strip()
    except OSError:
        return ""


def outdated(specs: list[Path] | None = None) -> dict[str, Path]:
    """{installed theme id: its spec file} for installed themes whose spec (one of `specs`, default: the recent
    list) has changed since it was installed."""
    from . import build, library, spec
    found: dict[str, Path] = {}
    by_id = {t.id: t for t in themes()}
    for path in (library.recent() if specs is None else specs):
        try:
            t = spec.load(path)
        except Exception:       # unreadable spec: nothing to compare
            continue
        inst = by_id.get(t.id)
        if inst and t.id not in found and (st := stamp(inst)) and st != build.spec_hash(t):
            found[t.id] = Path(path)
    return found


def spec_for(theme: Installed) -> Path | None:
    """The recent spec file that installs this theme (same id), if any."""
    from . import library, spec
    for path in library.recent():
        try:
            if spec.load(path).id == theme.id:
                return Path(path)
        except Exception:
            continue
    return None


def find(key: str) -> Installed | None:
    """By id, name or slug (case-insensitive)."""
    k = key.lower()
    return next((t for t in themes() if k in (t.id.lower(), t.name.lower(), t.slug.lower())), None)


def remove(theme: Installed, dry_run: bool = False) -> list[Path]:
    """Delete every part of the theme. Returns what was (or, with dry_run, would be) removed."""
    if why := theme.in_use():
        raise RuntimeError(f"{theme.name} can't be removed: {', '.join(why)}")
    parts = theme.parts()
    if dry_run:
        return parts
    for p in parts:
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)
    for slug in {theme.slug} | {v.slug for v in theme.variants}:
        for f in _cache().glob(f"plasma_theme_{slug}*.kcache"):
            f.unlink(missing_ok=True)
    return parts
