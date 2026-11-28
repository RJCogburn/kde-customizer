"""Export for the KDE Store (store.kde.org): one archive per part, the way each store category expects it, plus
the complete theme with install.sh and an UPLOAD.md saying which file goes where.

The store's "Get New…" buttons install one kind of thing each (a global theme, a Plasma style, icons…), so a
complete theme is uploaded as several items. The global theme refers to the others by name: people who install it
from the store get the parts they also installed, and the defaults for the rest."""
from __future__ import annotations

import shutil
import tarfile
from pathlib import Path

from . import build as builder
from .spec import Theme


def _pack(src: Path, dest: Path) -> Path:
    with tarfile.open(dest, "w:gz") as tar:
        tar.add(src, arcname=src.name)
    return dest


def export(theme: Theme, dest_dir: str | Path, build_root: str | Path = "build") -> dict[str, tuple[Path, str, str]]:
    """Write the store files into dest_dir. Returns {key: (file, store category, what it is)}."""
    out = builder.build(theme, build_root)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    slug = theme.slug
    files: dict[str, tuple[Path, str, str]] = {}

    def add(key, path: Path, category: str, what: str):
        files[key] = (path, category, what)

    add("global", _pack(out / "lookandfeel" / theme.id, dest / f"{slug}-global-theme.tar.gz"),
        "Global Themes (Plasma 6)",
        "the global theme: colors, styles, layout, splash screen; refers to the parts below")
    add("colors", Path(shutil.copy2(out / "color-schemes" / f"{slug}.colors", dest / f"{slug}.colors")),
        "Plasma Color Schemes", "the color scheme")
    if theme.plasma.generate:
        add("plasma", _pack(out / "plasma" / theme.plasma_style_name, dest / f"{slug}-plasma-style.tar.gz"),
            "Plasma Themes (Plasma styles)", "the panel and widget style")
    if theme.iconset.generate and (out / "icons" / theme.icons_name).is_dir():
        add("icons", _pack(out / "icons" / theme.icons_name, dest / f"{slug}-icons.tar.gz"), "Full Icon Themes",
            f"the icon theme (it builds on {theme.iconset.base}, which people need installed too)")
    if theme.cursorset.generate and (out / "cursors" / theme.cursors_name).is_dir():
        add("cursors", _pack(out / "cursors" / theme.cursors_name, dest / f"{slug}-cursors.tar.gz"), "Cursors",
            "the cursor theme")
    if theme.decoration.generate:
        add("decoration", _pack(out / "aurorae" / theme.decoration_name, dest / f"{slug}-decoration.tar.gz"),
            "Window Decorations (Aurorae)", "the title bars")
    if theme.widgets.generate:
        add("kvantum", _pack(out / "kvantum" / theme.kvantum_name, dest / f"{slug}-kvantum.tar.gz"), "Kvantum",
            "the app style (needs Kvantum)")
    if theme.konsole and (out / "konsole").is_dir():
        add("konsole", _pack(out / "konsole", dest / f"{slug}-konsole.tar.gz"), "Konsole Color Schemes",
            "Konsole colors (.colorscheme + profile)")
    if theme.boot_splash.generate and (out / "boot").is_dir():
        bdir = next((d for d in (out / "boot").iterdir() if d.is_dir()), None)
        if bdir:
            add("boot", _pack(bdir, dest / f"{slug}-plymouth.tar.gz"), "Plymouth Themes", "the boot splash")
    if theme.wallpaper and (out / "wallpapers").is_dir():
        wp = next((out / "wallpapers").iterdir())
        add("wallpaper", Path(shutil.copy2(wp, dest / f"{slug}-wallpaper{wp.suffix}")), "Wallpapers",
            "the wallpaper")
    add("complete", builder.export(theme, dest / f"{slug}-complete.tar.gz", build_root),
        "add it to the Global Theme item as an extra file",
        "everything, with install.sh — also GTK/terminal/Firefox colors, login screen and tweaks, which the store's "
        "Get New… buttons can't install")
    (dest / "UPLOAD.md").write_text(upload_text(theme, files))
    return files


def upload_text(theme: Theme, files: dict[str, tuple[Path, str, str]]) -> str:
    """UPLOAD.md: which file goes in which store category, plus tips."""
    lines = [
        f"# Uploading “{theme.name}” to the KDE Store",
        "",
        "Sign in at https://store.kde.org, then **Add Product** once per file below, picking the category shown "
        "(or the closest one). Use the same name and screenshots for all of them, and link the items to each other "
        "in their descriptions so people find the whole set.",
        "",
        "| File | Category | What it is |",
        "| --- | --- | --- |",
    ]
    for path, category, what in files.values():
        lines.append(f"| `{path.name}` | {category} | {what} |")
    lines += [
        "",
        "Screenshot: `preview.png` (when present) shows the whole desktop; a real screenshot after Apply is better.",
        "",
        "## Tips",
        "",
        "- The global theme only switches to the other parts when they are installed. Say in its description which "
        "items to get too, or point people to the complete archive.",
        f"- The icon theme inherits from **{theme.iconset.base}**: mention it, people need it installed."
        if theme.iconset.generate else "- Icons: the global theme uses the installed icon theme "
        f"**{theme.icons}**.",
        "- Respect the licenses of anything you didn't make (wallpaper, base icon theme).",
        "",
    ]
    return "\n".join(lines)
