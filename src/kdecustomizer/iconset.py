"""Generated icon theme = recolored base theme + optional "signature" icons on top.

Layer 1 (always, deterministic): copy the base theme's folder/place icons, shift their folder-colored
fills to the palette accent, and inherit the base theme for everything else.
Layer 2 (optional): signature icons from `iconset.signature_dir` — `svg/<slot>.svg` (AI-drawn vectors)
and/or `png/<slot>.png` (local image AI masters, resized here). They replace the recolored versions.

Pure functions + file I/O; no Qt, no network.
"""
from __future__ import annotations

import colorsys
import configparser
import os
import re
import shutil
from pathlib import Path

from . import color, system
from .spec import Theme

# slot -> (context dir, what it depicts, extra icon names it should also answer to)
SLOTS: dict[str, tuple[str, str, list[str]]] = {
    "folder": ("places", "a closed folder", ["inode-directory"]),
    "folder-documents": ("places", "a folder with a document emblem", []),
    "folder-download": ("places", "a folder with a downward-arrow emblem", ["folder-downloads"]),
    "folder-pictures": ("places", "a folder with a picture emblem", ["folder-images"]),
    "folder-music": ("places", "a folder with a music-note emblem", ["folder-sound"]),
    "folder-videos": ("places", "a folder with a film emblem", ["folder-video"]),
    "user-home": ("places", "a folder with a house emblem", ["folder-home"]),
    "user-desktop": ("places", "a folder with a monitor emblem", ["folder-desktop"]),
    "user-trash": ("places", "an empty trash bin", []),
    "start-here-kde": ("places", "the app-launcher logo: an abstract emblem", ["start-here", "start-here-kde-plasma"]),
    "system-file-manager": ("apps", "a file manager app: a folder with a magnifier", ["org.kde.dolphin"]),
    "utilities-terminal": ("apps", "a terminal app: a window with a >_ prompt", ["org.kde.konsole", "konsole"]),
    "internet-web-browser": ("apps", "a web browser app: a globe", []),
    "preferences-system": ("apps", "a system settings app: a gear", ["systemsettings"]),
}
PNG_SIZES = [16, 22, 24, 32, 48, 64, 96, 128, 256]
_RECOLOR_NAMES = re.compile(r"^(folder|user-|inode-directory|network-workgroup)")
_VARIANT = re.compile(r"^folder-(adwaita|black|blue|bluegrey|breeze|brown|carmine|cyan|darkcyan|deeporange|green|"
                      r"grey|indigo|magenta|nordic|orange|palebrown|paleorange|pink|red|teal|violet|white|yaru|"
                      r"yellow)(-|\.svg)")
_HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def find_theme_dir(name: str) -> Path | None:
    for d in [Path.home() / ".icons", *(b / "icons" for b in system._data_dirs())]:
        if (d / name / "index.theme").is_file():
            return d / name
    return None


def svg_themes() -> list[str]:
    """Installed icon themes that ship SVG folder icons (recolorable)."""
    out = []
    for name in system.icon_themes():
        d = find_theme_dir(name)
        if d and any(d.glob("**/folder.svg")):
            out.append(name)
    return out


def _read_index(d: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    cp.read(d / "index.theme", encoding="utf-8")
    return cp


def _canonical_entries(directory: Path) -> list[Path]:
    """Icon names to recolor in one dir: every folder/place icon except Papirus' color variants
    (folder-red.svg, folder-blue-documents.svg… — apps never ask for those; the plain names link to them)
    and symbolic icons (monochrome, already follow the color scheme)."""
    try:
        return [Path(e.path) for e in os.scandir(directory)
                if e.name.endswith(".svg") and _RECOLOR_NAMES.match(e.name)
                and not _VARIANT.match(e.name) and "-symbolic" not in e.name]
    except FileNotFoundError:
        return []


def _hex_rgb(h: str) -> tuple[int, int, int]:
    return color.parse("#" + h)


def _dominant(svgs: list[str]) -> tuple[float, float, float] | None:
    """HLS of the base theme's folder color: the most common saturated hue, weighted by use."""
    bins: dict[int, list[tuple[float, float, float]]] = {}
    for text in svgs:
        for m in _HEX.finditer(text):
            r, g, b = (v / 255 for v in _hex_rgb(m.group(1)))
            h, l, s = colorsys.rgb_to_hls(r, g, b)
            if s > 0.3 and 0.15 < l < 0.85:
                bins.setdefault(int(h * 36) % 36, []).append((h, l, s))
    if not bins:
        return None
    best = max(bins.values(), key=len)
    n = len(best)
    return sum(x[0] for x in best) / n, sum(x[1] for x in best) / n, sum(x[2] for x in best) / n


def _recolorer(dominant: tuple[float, float, float], accent: str):
    h0, l0, s0 = dominant
    r, g, b = (v / 255 for v in color.parse(accent))
    ha, la, sa = colorsys.rgb_to_hls(r, g, b)

    def sub(m: re.Match) -> str:
        r, g, b = (v / 255 for v in _hex_rgb(m.group(1)))
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        dh = min(abs(h - h0), 1 - abs(h - h0))
        if s < 0.2 or dh > 40 / 360:
            return m.group(0)  # paper whites, shadows, emblems in other hues stay as they are
        nl = min(0.95, max(0.05, l + (la - l0) * 0.8))
        ns = min(1.0, max(0.0, s * (sa / s0 if s0 else 1)))
        nr, ng, nb = colorsys.hls_to_rgb(ha, nl, ns)
        return color.to_hex((round(nr * 255), round(ng * 255), round(nb * 255)))

    return lambda text: _HEX.sub(sub, text)


def _slot_names() -> set[str]:
    names = set()
    for slot, (_ctx, _d, aliases) in SLOTS.items():
        names.add(slot)
        names.update(aliases)
    return names


def build(theme: Theme, out_root: Path) -> Path:
    """Write the icon theme to out_root/<icons_name>/ and return that path."""
    ics = theme.iconset
    base_dir = find_theme_dir(ics.base)
    if base_dir is None:
        raise FileNotFoundError(f"icon theme {ics.base!r} is not installed")
    base = _read_index(base_dir)
    out = Path(out_root) / theme.icons_name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    icon_section = base["Icon Theme"] if base.has_section("Icon Theme") else {}
    base_dirs = [d for d in icon_section.get("Directories", "").split(",") if d]
    scaled = [d for d in icon_section.get("ScaledDirectories", "").split(",") if d]
    sig = Path(ics.signature_dir) if ics.signature_dir else None
    replaced = _slot_names() if sig and sig.is_dir() and any(sig.glob("*/*.*")) else set()

    # ---- layer 1: recolor ----
    files: list[tuple[str, Path]] = []
    for d in base_dirs + scaled:
        if not base.has_section(d) or base[d].get("Context") not in ("Places", "MimeTypes") or "symbolic" in d:
            continue
        for p in _canonical_entries(base_dir / d):
            if p.stem not in replaced:
                files.append((d, p))
    texts = {}
    for d, p in files:
        try:
            texts[(d, p.name)] = Path(os.path.realpath(p)).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    dom = _dominant(list(texts.values()))
    recolor = _recolorer(dom, theme.palette.accent) if dom else (lambda t: t)
    used_dirs: dict[str, dict[str, str]] = {}
    for (d, name), text in texts.items():
        (out / d).mkdir(parents=True, exist_ok=True)
        (out / d / name).write_text(recolor(text), encoding="utf-8")
        used_dirs[d] = dict(base[d])

    # ---- layer 2: signature icons ----
    if replaced:
        for slot, (ctx, _desc, aliases) in SLOTS.items():
            svg = sig / "svg" / f"{slot}.svg"
            png = sig / "png" / f"{slot}.png"
            if svg.is_file():
                d = f"signature/scalable/{ctx}"
                (out / d).mkdir(parents=True, exist_ok=True)
                for n in [slot, *aliases]:
                    shutil.copyfile(svg, out / d / f"{n}.svg")
                used_dirs[d] = {"Size": "64", "MinSize": "8", "MaxSize": "512", "Type": "Scalable",
                                "Context": ctx.title()}
            elif png.is_file():
                from PIL import Image  # only needed for image-mode signature icons
                with Image.open(png) as im:
                    im = im.convert("RGBA")
                    for size in PNG_SIZES:
                        d = f"signature/{size}/{ctx}"
                        (out / d).mkdir(parents=True, exist_ok=True)
                        small = im.resize((size, size), Image.LANCZOS)
                        for n in [slot, *aliases]:
                            small.save(out / d / f"{n}.png")
                        used_dirs[d] = {"Size": str(size), "Type": "Fixed", "Context": ctx.title()}

    # ---- index.theme ----
    plain = [d for d in used_dirs if d not in scaled]
    lines = ["[Icon Theme]", f"Name={theme.name} Icons", f"Comment=Generated by kde-customizer from {ics.base}",
             f"Inherits={ics.base},hicolor", f"Directories={','.join(plain)}"]
    in_scaled = [d for d in used_dirs if d in scaled]
    if in_scaled:
        lines.append(f"ScaledDirectories={','.join(in_scaled)}")
    lines.append("")
    for d, keys in used_dirs.items():
        lines.append(f"[{d}]")
        lines += [f"{k}={v}" for k, v in keys.items()]
        lines.append("")
    (out / "index.theme").write_text("\n".join(lines), encoding="utf-8")
    return out
