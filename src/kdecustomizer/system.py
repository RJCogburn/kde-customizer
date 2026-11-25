"""What's installed on this machine — for editor dropdowns and AI prompts. Read-only, no Qt."""
from __future__ import annotations

import os
from pathlib import Path


def _data_dirs() -> list[Path]:
    home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    rest = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
    return [home, *(Path(d) for d in rest if d)]


def _dirs(sub: str) -> list[Path]:
    seen: dict[str, Path] = {}
    for base in [Path.home() / ".icons", *(_d / sub for _d in _data_dirs())] if sub == "icons" else \
            [d / sub for d in _data_dirs()]:
        if base.is_dir():
            for d in base.iterdir():
                if d.is_dir() and d.name not in seen:
                    seen[d.name] = d
    return sorted(seen.values(), key=lambda p: p.name.lower())


def icon_themes() -> list[str]:
    return [d.name for d in _dirs("icons")
            if (d / "index.theme").is_file() and not (d / "cursors").is_dir() and d.name != "default"]


def cursor_themes() -> list[str]:
    return [d.name for d in _dirs("icons") if (d / "cursors").is_dir()]


def plasma_styles() -> list[str]:
    return [d.name for d in _dirs("plasma/desktoptheme")]


def color_schemes() -> list[str]:
    return sorted({p.stem for d in _data_dirs() for p in (d / "color-schemes").glob("*.colors")})


def widget_styles() -> list[str]:
    styles = ["Breeze", "Fusion"]
    if any((d / "Kvantum").is_dir() for d in _data_dirs()):
        styles.append("kvantum")
    return styles


def kvantum_installed() -> bool:
    """Kvantum's Qt 6 style plugin (or its manager) is on this machine."""
    import shutil
    plugin_dirs = [Path("/usr/lib/qt6/plugins/styles"), Path("/usr/lib64/qt6/plugins/styles"),
                   *Path("/usr/lib").glob("*/qt6/plugins/styles")]
    return shutil.which("kvantummanager") is not None or any((d / "libkvantum.so").exists() for d in plugin_dirs)


def plasma_login_installed() -> bool:
    """Plasma Login Manager (the greeter `login_screen` themes) is set up: its greeter user exists."""
    import pwd
    try:
        pwd.getpwnam("plasmalogin")
        return True
    except KeyError:
        return False


def summary() -> dict[str, list[str]]:
    return {
        "icons": icon_themes(),
        "cursors": cursor_themes(),
        "plasma_style": plasma_styles(),
        "widget_style": widget_styles(),
    }
