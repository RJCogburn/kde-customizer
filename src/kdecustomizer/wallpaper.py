"""A wallpaper rendered by the local image AI (Fooocus / ComfyUI / A1111-Forge) in the theme's palette.

SDXL renders near one megapixel, so the picture is made at the SDXL size closest to the screen's shape
(e.g. 1344x768 for 16:9) and then scaled up and center-cropped to the screen (LANCZOS + a light sharpen).
Saved next to the spec as <slug>-wallpaper-<seed>.jpg; the spec's `wallpaper` then points at it.
"""
from __future__ import annotations

import colorsys
import io
import json
import subprocess
from pathlib import Path

from . import color, imagegen
from .spec import Theme

# SDXL training buckets (w, h): renders at these sizes look their best
SDXL_SIZES = [(1024, 1024), (1152, 896), (1216, 832), (1344, 768), (1536, 640), (896, 1152), (832, 1216),
              (768, 1344), (640, 1536)]
DEFAULT_SCREEN = (2560, 1440)

NEGATIVE = ("text, letters, words, watermark, signature, logo, caption, frame, border, user interface, "
            "lowres, blurry, jpeg artifacts, noise, oversaturated, cluttered, deformed")

_HUES = [(15, "red"), (40, "orange"), (52, "amber"), (68, "yellow"), (95, "lime"), (150, "green"), (175, "teal"),
         (195, "cyan"), (215, "azure"), (240, "blue"), (260, "indigo"), (280, "violet"), (300, "purple"),
         (325, "magenta"), (345, "pink"), (360, "crimson")]


def describe(hex_color: str) -> str:
    """'deep indigo', 'muted teal', 'charcoal gray' — words an image model understands."""
    r, g, b = color.parse(hex_color)
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    if s < 0.12 or (l < 0.12 and s < 0.3) or (l > 0.92 and s < 0.5):
        return ("near-black charcoal" if l < 0.12 else "dark graphite gray" if l < 0.3 else "silver gray"
                if l < 0.7 else "pale white")
    name = next(n for limit, n in _HUES if h * 360 <= limit)
    shade = ("very dark" if l < 0.15 else "deep" if l < 0.3 else "" if l < 0.6 else "light" if l < 0.8 else "pale")
    tone = "muted" if s < 0.35 else "vivid" if s > 0.7 and 0.3 < l < 0.7 else ""
    return " ".join(w for w in (shade, tone, name) if w)


def prompt(theme: Theme, idea: str = "") -> str:
    p = theme.palette.resolved()
    subject = (idea.strip() or theme.description.strip() or f"{theme.name} abstract landscape").rstrip(" .")
    mood = "dark, moody" if theme.dark else "bright, airy"
    base = list(dict.fromkeys([describe(p.background), describe(p.surface)]))
    return (f"{subject}, desktop wallpaper, wide cinematic composition, {mood}, "
            f"color palette of {' and '.join(base)}, {describe(p.accent)} highlights and glow, "
            "calm uncluttered center, soft depth of field, high detail, 8k, masterpiece")


def screen_size() -> tuple[int, int]:
    """The largest enabled output's current mode (kscreen-doctor), else 2560x1440."""
    try:
        data = json.loads(subprocess.run(["kscreen-doctor", "-j"], capture_output=True, text=True,
                                         timeout=10).stdout)
        best = None
        for o in data.get("outputs", []):
            if not o.get("enabled"):
                continue
            mode = next((m for m in o.get("modes", []) if m.get("id") == o.get("currentModeId")), None)
            if mode:
                w, h = mode["size"]["width"], mode["size"]["height"]
                if (o.get("rotation") or 1) in (2, 8):        # rotated 90/270
                    w, h = h, w
                if best is None or w * h > best[0] * best[1]:
                    best = (w, h)
        if best:
            return best
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        pass
    return DEFAULT_SCREEN


def render_size(screen: tuple[int, int]) -> tuple[int, int]:
    want = screen[0] / screen[1]
    return min(SDXL_SIZES, key=lambda s: abs(s[0] / s[1] - want))


def fit(data: bytes, screen: tuple[int, int]) -> bytes:
    """Scale up and center-crop to the screen; JPEG (a 4K PNG would be ~15 MB in every export)."""
    from PIL import Image, ImageFilter
    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        sw, sh = screen
        scale = max(sw / im.width, sh / im.height)
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        left, top = (im.width - sw) // 2, (im.height - sh) // 2
        im = im.crop((left, top, left + sw, top + sh))
        if scale > 1.2:
            im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=93, optimize=True)
        return buf.getvalue()


def generate(theme: Theme, out_dir: Path, url: str, *, idea: str = "", performance: str = "", model: str = "",
             seed: int | None = None, screen: tuple[int, int] | None = None, log=lambda s: None) -> Path:
    """Render a wallpaper and save it in out_dir. Returns its path (the caller sets theme.wallpaper)."""
    screen = screen or screen_size()
    backend = imagegen.detect(url, performance, model)
    backend.size = render_size(screen)
    if (m := backend.chosen_model()):
        log(f"model: {m}")
    seed = seed or imagegen.random_seed()
    log(f"{backend.name}: rendering the wallpaper at {backend.size[0]}x{backend.size[1]} "
        f"for a {screen[0]}x{screen[1]} screen…")
    raw = backend.generate(prompt(theme, idea), NEGATIVE, seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{theme.slug.lower()}-wallpaper-{seed}.jpg"
    path.write_bytes(fit(raw, screen))
    log(f"saved {path}")
    return path
