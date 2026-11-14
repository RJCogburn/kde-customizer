"""Signature icons — the ~14 icons people see constantly, made in a custom style.

Three sources, all writing into the theme's signature folder (`iconset.signature_dir`):
  * svg:    an AI (any provider from ai.py) draws them as SVG vectors — crisp at every size.
  * image:  a local image AI (Fooocus / ComfyUI / A1111-Forge via imagegen.py) renders them; the
            background is cut away and a 512px master PNG is kept (resized per size at build time).
  * import: images made anywhere (ArtCraft, Krita, …) named after the slot, e.g. `folder-music.png`.
Layout:  <signature_dir>/svg/<slot>.svg  and/or  <signature_dir>/png/<slot>.png   (svg wins if both)
"""
from __future__ import annotations

import colorsys
import io
import json
import re
import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

from . import ai, color, imagegen
from .iconset import SLOTS
from .spec import Theme

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)


def default_dir(theme: Theme, spec_path: str | Path | None) -> Path:
    base = Path(spec_path).parent if spec_path else Path.cwd()
    return base / f"{theme.slug.lower()}-icons"


def _hue_name(hex_color: str) -> str:
    r, g, b = (v / 255 for v in color.parse(hex_color))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.25 or (l < 0.2 and s < 0.4):  # near-neutrals and very dark tints read as gray/black
        return "white" if l > 0.8 else "black" if l < 0.2 else "silver gray" if l > 0.5 else "graphite gray"
    names = [(12, "red"), (34, "orange"), (52, "gold"), (65, "yellow"), (150, "green"), (190, "teal"),
             (250, "blue"), (275, "indigo"), (320, "violet"), (345, "pink"), (360, "red")]
    name = next(n for limit, n in names if h * 360 <= limit)
    return ("pale " if l > 0.75 else "deep " if l < 0.3 else "") + name


def style_of(theme: Theme) -> str:
    """The user's style text, or one derived from the palette."""
    if theme.iconset.style.strip():
        return theme.iconset.style.strip()
    p = theme.palette
    return (f"elegant modern style, {_hue_name(p.accent)} as the main color, {_hue_name(p.surface)} details, "
            f"{'dark' if theme.dark else 'light'} desktop")


# --- prompts for image AIs (also exported for apps like ArtCraft) ---------------------------------

NEGATIVE = ("dark background, black background, gradient background, colored background, scenery, room, "
            "text, letters, words, watermark, logo, signature, multiple objects, frame, border, floor, ground, "
            "table, reflection, cast shadow, busy background, cropped, cut off, blurry")


def image_prompt(theme: Theme, slot: str) -> str:
    # The background instruction goes first: dark styles ("graphite", "night") otherwise darken the
    # whole scene and the cut-out has nothing plain to remove.
    return (f"isolated on a plain pure white background, {SLOTS[slot][1]}, desktop app icon, {style_of(theme)}, "
            "single centered object floating in empty space, no floor, no reflection, no cast shadow, "
            "soft studio lighting, high detail, clean silhouette, no text")


def prompts_text(theme: Theme) -> str:
    """Human-readable prompt sheet for making the icons in any image app, then importing them."""
    out = [f"Signature icons for “{theme.name}” — make each image square, on a plain white background,",
           "and save it under the file name shown. Then import the folder (GUI: Icons → Import images…,",
           "or `kdec icons THEME.toml --import FOLDER`).", "", f"Negative prompt (all): {NEGATIVE}", ""]
    for slot in SLOTS:
        out += [f"{slot}.png", f"  {image_prompt(theme, slot)}", ""]
    return "\n".join(out)


# --- SVG mode -------------------------------------------------------------------------------------

_SVG_GUIDE = """\
You are an icon designer. Draw desktop icons as hand-written SVG for a KDE Plasma icon theme.

Rules for every icon:
- Root: <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">.
- Self-contained: no <script>, no <image>, no external links or fonts, no text/letters.
- Use only the theme's colors (given below) plus white/black and their tints; gradients are fine.
- Keep shapes bold and simple so they read at 16px; leave ~4px padding inside the 64x64 box.
- All icons must share ONE consistent style (same perspective, corner radius, stroke weight, lighting).
- Folder-based icons (folder, folder-*, user-home, user-desktop) share the same folder shape with a
  small emblem on the front.

Reply with a single ```json block: an object mapping each requested icon name to its SVG string.
"""


def sanitize_svg(text: str) -> str:
    """Parse and clean an AI-written SVG. Raises ValueError if it isn't a usable SVG."""
    text = text.strip()
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"not valid SVG: {e}") from None
    if root.tag not in (f"{{{SVG_NS}}}svg", "svg"):
        raise ValueError("root element is not <svg>")
    banned = {"script", "foreignObject", "image", "iframe"}
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag.split("}")[-1] in banned:
                parent.remove(child)
    for el in root.iter():
        for attr in list(el.attrib):
            local = attr.split("}")[-1]
            val = el.attrib[attr]
            if local.startswith("on") or (local == "href" and not val.startswith("#")) or "url(http" in val:
                del el.attrib[attr]
    if "viewBox" not in root.attrib:
        w = re.sub(r"[^\d.]", "", root.attrib.get("width", "64")) or "64"
        h = re.sub(r"[^\d.]", "", root.attrib.get("height", "64")) or "64"
        root.attrib["viewBox"] = f"0 0 {w} {h}"
    root.attrib.setdefault("width", "64")
    root.attrib.setdefault("height", "64")
    if len(list(root.iter())) < 3:
        raise ValueError("SVG is empty")
    return ET.tostring(root, encoding="unicode")


def _palette_text(theme: Theme) -> str:
    p = theme.palette.resolved()
    return (f"Theme colors: background {p.background}, surface {p.surface}, text {p.foreground}, "
            f"accent {p.accent}, positive {p.positive}, warning {p.neutral}, negative {p.negative}. "
            f"{'Dark' if theme.dark else 'Light'} theme.")


def generate_svg(theme: Theme, sig_dir: Path, prov: ai.Provider, *, api_key: str | None = None,
                 references: list[str] = (), only: list[str] | None = None, log=lambda s: None) -> list[str]:
    """Have an AI draw the signature icons as SVG. Returns the slots written."""
    slots = only or list(SLOTS)
    content: list[dict] = []
    if references:
        content.append({"type": "text", "text": "REFERENCE material — match its style:"})
        for r in references:
            try:
                content += ai.load_reference(r)
            except ValueError as e:
                raise ai.AIError(str(e)) from None
    wanted = "\n".join(f"- {s}: {SLOTS[s][1]}" for s in slots)
    content.append({"type": "text", "text": f"{_palette_text(theme)}\nStyle: {style_of(theme)}\n\n"
                                            f"Draw these icons:\n{wanted}"})
    messages: list[dict] = [{"role": "user", "content": content}]
    got: dict[str, str] = {}
    for attempt in range(2):
        log(f"asking {prov.name} to draw {len(slots) - len(got)} icons{' (retry)' if attempt else ''}…")
        reply = ai.call_provider(prov, _SVG_GUIDE, messages, api_key)
        m = re.findall(r"```(?:json)?\s*\n(.*?)```", reply, re.S)
        problems: list[str] = []
        try:
            data = json.loads(max(m, key=len) if m else reply)
        except json.JSONDecodeError as e:
            data, problems = {}, [f"reply was not valid JSON ({e})"]
        for slot in slots:
            if slot in got:
                continue
            if slot not in data:
                problems.append(f"{slot}: missing")
                continue
            try:
                got[slot] = sanitize_svg(str(data[slot]))
            except ValueError as e:
                problems.append(f"{slot}: {e}")
        if not problems:
            break
        log("issues: " + "; ".join(problems[:4]))
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": "Fix these and reply with a ```json block containing only the "
                                                 "icons listed:\n- " + "\n- ".join(problems)}]
    if not got:
        raise ai.AIError("the AI didn't return any usable SVG icons")
    for slot, svg in got.items():
        _store(sig_dir, slot, "svg", svg.encode())
    return list(got)


# --- image mode -----------------------------------------------------------------------------------

def generate_images(theme: Theme, sig_dir: Path, url: str, *, performance: str = "", only: list[str] | None = None,
                    seed: int | None = None, log=lambda s: None) -> list[str]:
    """Render signature icons with a local image AI. One shared seed keeps the set consistent."""
    backend = imagegen.detect(url, performance)
    seed = seed or imagegen.random_seed()
    done = []
    slots = only or list(SLOTS)
    for n, slot in enumerate(slots, 1):
        log(f"{backend.name}: rendering {slot} ({n}/{len(slots)})…")
        raw = backend.generate(image_prompt(theme, slot), NEGATIVE, seed)
        buf = io.BytesIO()
        imagegen.to_icon(raw).save(buf, "PNG")
        _store(sig_dir, slot, "png", buf.getvalue())
        done.append(slot)
    return done


def import_images(theme: Theme, sig_dir: Path, folder: str | Path, cut_background: bool = True) -> list[str]:
    """Import <slot>.png/.jpg/.webp/.svg files made in any app. Returns the slots imported."""
    folder = Path(folder)
    done = []
    for slot in SLOTS:
        for ext in (".svg", ".png", ".webp", ".jpg", ".jpeg"):
            f = folder / f"{slot}{ext}"
            if not f.is_file():
                continue
            if ext == ".svg":
                _store(sig_dir, slot, "svg", sanitize_svg(f.read_text(encoding="utf-8")).encode())
            else:
                from PIL import Image
                data = f.read_bytes()
                with Image.open(f) as im:
                    has_alpha = im.mode in ("RGBA", "LA") and im.getextrema()[-1][0] < 250
                if has_alpha or not cut_background:
                    with Image.open(f) as im:
                        icon = imagegen._square(im.convert("RGBA"), 512)
                else:
                    icon = imagegen.to_icon(data)
                buf = io.BytesIO()
                icon.save(buf, "PNG")
                _store(sig_dir, slot, "png", buf.getvalue())
            done.append(slot)
            break
    return done


def _store(sig_dir: Path, slot: str, kind: str, data: bytes) -> None:
    """Write one signature icon; drop the other kind for that slot so exactly one source is used."""
    other = sig_dir / ("png" if kind == "svg" else "svg") / f"{slot}.{'png' if kind == 'svg' else 'svg'}"
    other.unlink(missing_ok=True)
    (sig_dir / kind).mkdir(parents=True, exist_ok=True)
    (sig_dir / kind / f"{slot}.{kind}").write_bytes(data)


def existing(sig_dir: str | Path | None) -> dict[str, Path]:
    """slot -> file currently used for it (svg preferred)."""
    out: dict[str, Path] = {}
    if not sig_dir:
        return out
    d = Path(sig_dir)
    for slot in SLOTS:
        for kind in ("svg", "png"):
            f = d / kind / f"{slot}.{kind}"
            if f.is_file():
                out[slot] = f
                break
    return out


def clear(sig_dir: str | Path, slots: list[str] | None = None) -> None:
    d = Path(sig_dir)
    if slots is None:
        shutil.rmtree(d, ignore_errors=True)
        return
    for slot in slots:
        for kind in ("svg", "png"):
            (d / kind / f"{slot}.{kind}").unlink(missing_ok=True)
