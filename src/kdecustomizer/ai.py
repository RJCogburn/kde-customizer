"""AI-assisted theme design. Provider-neutral core (no Qt): prompt building, reply parsing, checks.

Two ways to use it:
  * Any AI, no API key: `reference()` / `prompt_text()` produce text you paste into a chat AI or give
    to a coding agent; `parse_reply()` turns its answer back into a Theme.
  * Direct: `generate()` calls a provider — Claude through the official `anthropic` SDK, or anything
    OpenAI-compatible (OpenAI, Gemini, OpenRouter, Ollama, LM Studio) over HTTP — then validates the
    result and asks the model to fix problems once before returning.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path

from . import color, spec, system

# --- providers ----------------------------------------------------------------------

CLAUDE_MODEL = "claude-opus-5-5"


@dataclass
class Provider:
    name: str
    kind: str              # "claude-code" | "anthropic" | "openai"
    base_url: str = ""
    key_env: str = ""      # env var holding the API key ("" = no key needed)
    model: str = ""


PRESETS: dict[str, Provider] = {
    # Your Claude Code sign-in (same as the VS Code extension) — uses your Claude plan, no API key.
    "claude-code": Provider("Claude Code (your login)", "claude-code"),
    "claude": Provider("Claude API (key)", "anthropic", model=CLAUDE_MODEL),
    "openai": Provider("OpenAI", "openai", "https://api.openai.com/v1", "OPENAI_API_KEY"),
    "gemini": Provider("Google Gemini", "openai", "https://generativelanguage.googleapis.com/v1beta/openai",
                       "GEMINI_API_KEY"),
    "openrouter": Provider("OpenRouter", "openai", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama": Provider("Ollama (local)", "openai", "http://localhost:11434/v1"),
    "lmstudio": Provider("LM Studio (local)", "openai", "http://localhost:1234/v1"),
}


class AIError(RuntimeError):
    pass


# --- the reference an AI designs against ---------------------------------------------

_GUIDE = """\
You design complete KDE Plasma 6 desktop themes. A theme is ONE TOML file; a build tool turns it into a
color scheme, Plasma style, Konsole scheme, global theme package, panel layout and an install script.

## Spec (every key, with defaults)
```toml
{skeleton}
```

## What each part controls
- `[palette]` (hex `#rrggbb`) — everything is derived from these:
  - `background`: window and panel backgrounds. `surface`: title bars, buttons, headers, tooltips
    (a slightly different shade of background). `foreground`: all text.
  - `accent`: selection, focus rings, highlights, active task, progress bars. Text drawn on accent is
    automatically white or black, whichever reads better.
  - `positive` / `neutral` / `negative`: success / warning / error text; `negative` is also the close button.
  - `link`, `visited`: leave "" to derive from accent.
  - Light vs dark is inferred from `background` luminance.
- `[plasma] generate = true` builds a Plasma style recolored from the palette (recommended — panels and
  popups then match apps). `blur` = translucent blurred panels/popups; `adaptive_transparency` = panels
  go opaque when a window is maximized. Shape (generated style only): `radius` = corner radius in px of
  floating panels/popups/tooltips (0..32; 6 = Breeze, 0 = square, 12-16 = soft/modern), `opacity` = fill
  opacity 0.3..1.0 (0.85 = Breeze; lower looks glassier with blur, 1.0 = solid), `outline` = thin
  text-colored edge around panels and popups (good for flat/high-contrast designs).
  With `generate = false`, `plasma_style` names an installed style.
- `icons`, `cursors`, `plasma_style`, `widget_style`: must be INSTALLED names (list below).
- `[widgets] generate = true` builds a Kvantum app style from the palette (buttons, fields, menus, tabs,
  check boxes, sliders, scrollbars), with `radius` 0..12 px corners (4 default; 0 = sharp, 6-8 = soft).
  It needs the kvantum package on the user's machine; without it apps keep `widget_style` (keep "Breeze").
- `[cursorset] generate = true` builds a cursor theme in the palette by recoloring `base` (an installed
  cursor theme with SVG cursors: "breeze_cursors" or "Breeze_Light"; `cursors` is then ignored). `fill` =
  the pointer body: "background" (classic: dark body on dark themes, light on light), "foreground"
  (inverted, high visibility) or "accent" (colorful). Outline, spinner and badges follow the palette.
- `[login_screen] generate = true` puts the theme (colors, Plasma style, icons, cursors, fonts) on the
  Plasma Login Manager screen; `background` wallpaper (the theme's; palette color without one) | color,
  `clock` true/false. Installing it asks for the admin password, so only enable it when asked.
- `splash`: keep "org.kde.Breeze" unless asked. `[splash_screen] generate = true` (recommended) makes a
  splash in the palette: the theme name (or `text`) and an accent progress bar, `background` gradient |
  wallpaper (the theme's, dimmed — needs `wallpaper`) | solid.
- `[decoration]` window title-bar buttons: `buttons_left` / `buttons_right` are strings of codes:
  M menu, S on-all-desktops, H help, F keep-above, B keep-below, I minimize, A maximize, X close,
  _ spacer. macOS-like = left "XIA", right "". Windows-like = left "M", right "IAX".
  `generate = true` builds title bars in the palette's colors (recommended; then `library`/`theme` are
  ignored): `radius` 0..16 top corners (8 default), `title_height` 20..60 (30 default; 24-26 compact,
  34+ roomy), `title_align` left|center|right, `border` 0..12 px side/bottom frame (2 default),
  `button_style` "glyph" (symbols, round hover; close turns `negative` on hover) or "dots" (colored
  circles: close = negative, minimize = neutral, maximize = positive — pair with left "XIA").
- `[fonts]`: "Family,size" e.g. "Inter,10"; "" leaves the user's font unchanged. Only use common fonts.
- `[[panels]]` (repeat for several): `location` top|bottom|left|right; `height` px (24–80 typical);
  `floating`; `alignment` left|center|right; `length_mode` fill|fit (fit = dock-like);
  `widgets` = ordered plasmoid ids. Common ids: org.kde.plasma.kickoff (app menu),
  org.kde.plasma.icontasks (icon-only task manager), org.kde.plasma.taskmanager (with labels),
  org.kde.plasma.pager, org.kde.plasma.marginsseparator, org.kde.plasma.panelspacer (flexible gap),
  org.kde.plasma.systemtray, org.kde.plasma.digitalclock, org.kde.plasma.showdesktop.
- `konsole = true` adds a matching terminal scheme.
- `[iconset]` builds a matching icon theme: `generate = true` recolors `base` (an installed SVG icon theme,
  e.g. Papirus-Dark, breeze-dark) to the accent and replaces `icons`. Set `style` to a short visual
  description for custom signature icons (e.g. "brushed champagne-gold metal, dark graphite glass").
  Leave `signature` and `signature_dir` as they are.
- `[tweaks.<file>.<group>]` raw KDE config writes, e.g. `[tweaks.kwinrc.Plugins] blurEnabled = true`.
  Only use keys you are sure exist.
- Do NOT set `wallpaper` (the user picks the file) or `author` (the user fills that in).

## Design rules
- Readability: foreground vs background and vs surface contrast >= 4.5:1 (aim for 7+);
  accent vs background >= 3:1.
- `surface` is a subtle step from `background` (a few % lighter on dark themes, darker on light ones),
  not a different hue family.
- Keep positive/neutral/negative recognisable as green/amber/red, tuned to sit with the palette.
- Attachments are labelled. The WALLPAPER: pull the palette from it (background from its dark/light
  areas, accent from its most characterful color) so the desktop feels like one piece.
  REFERENCE material (brand guides, mood boards, screenshots, palettes, documents): build the theme from
  it — use exact hex codes it gives, its brand/key colors as accent, its mood for light vs dark, and any
  style cues (rounded/flat, dock vs full panel, fonts). References win over the wallpaper when they
  conflict, but keep the result readable against the wallpaper.

## Installed on this machine
{installed}

## Output
Reply with the complete theme as a single ```toml fenced block, then at most two short sentences on the
design. Always output every section, even unchanged ones.
"""


def reference(installed: dict[str, list[str]] | None = None) -> str:
    """The spec guide with this machine's installed themes. Give it to any AI or agent."""
    installed = installed if installed is not None else system.summary()
    inst = "\n".join(f"- {k}: {', '.join(v) if v else '(none found)'}" for k, v in installed.items())
    skeleton = spec.dumps(spec.Theme()).strip()
    return _GUIDE.format(skeleton=skeleton, installed=inst)


def request_text(request: str, current: spec.Theme | None) -> str:
    parts = []
    if current is not None:
        cur = replace(current, wallpaper="")
        parts.append("Current theme (refine it; keep `id` and `name` unless asked to change them):\n"
                     f"```toml\n{spec.dumps(cur).strip()}\n```")
    parts.append(f"Request: {request.strip() or 'Design a polished, cohesive theme.'}")
    return "\n\n".join(parts)


def prompt_text(request: str, current: spec.Theme | None = None, references: list[str] = ()) -> str:
    """One self-contained prompt to paste into any chat AI (attach any reference files yourself)."""
    note = ""
    if references:
        note = ("\n\nI'm attaching these reference files — build the theme from them: "
                + ", ".join(Path(r).name for r in references))
    return reference() + "\n---\n\n" + request_text(request, current) + note


# --- reference attachments -------------------------------------------------------------

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
TEXT_EXT = {".txt", ".md", ".toml", ".json", ".css", ".scss", ".less", ".qss", ".html", ".htm", ".svg", ".xml",
            ".yaml", ".yml", ".ini", ".conf", ".colors", ".colorscheme", ".kvconfig", ".csv", ".rtf"}
MAX_TEXT_CHARS = 150_000
MAX_PDF_BYTES = 30 * 1024 * 1024
ATTACH_FILTER = ("Images, PDFs, documents (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tif *.tiff *.pdf *.docx "
                 + " ".join(f"*{e}" for e in sorted(TEXT_EXT - {".jpg"})) + ")")


def _docx_text(path: Path) -> str:
    import zipfile
    from xml.etree import ElementTree as ET
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    paras = ["".join(t.text or "" for t in p.iter(f"{ns}t")) for p in root.iter(f"{ns}p")]
    return "\n".join(p for p in paras if p.strip())


_TYPE_EXT = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
             "image/gif": ".gif", "text/plain": ".txt", "text/html": ".html", "text/markdown": ".md",
             "image/svg+xml": ".svg",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx"}


def is_url(ref: str) -> bool:
    return bool(re.match(r"https?://", ref.strip(), re.I))


def _download(url: str, dest_dir: str) -> Path:
    """Fetch a reference URL into dest_dir, refusing anything over the PDF size limit."""
    from urllib.parse import unquote, urlparse
    req = urllib.request.Request(url, headers={"User-Agent": "kde-customizer"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read(MAX_PDF_BYTES + 1)
            ctype = (r.headers.get_content_type() or "").lower()
    except urllib.error.HTTPError as e:
        raise ValueError(f"{url}: download failed (HTTP {e.code})") from None
    except urllib.error.URLError as e:
        raise ValueError(f"{url}: download failed ({e.reason})") from None
    if len(data) > MAX_PDF_BYTES:
        raise ValueError(f"{url}: file is larger than 30 MB")
    name = Path(unquote(urlparse(url).path)).name or "download"
    if Path(name).suffix.lower() not in IMAGE_EXT | TEXT_EXT | {".pdf", ".docx"}:
        name += _TYPE_EXT.get(ctype, ".txt")
    out = Path(dest_dir, re.sub(r"[^\w.-]+", "_", name))
    out.write_bytes(data)
    return out


def load_reference(path: str) -> list[dict]:
    """Content blocks for one reference file or http(s) URL. Raises ValueError if it can't be used
    (never truncates)."""
    if is_url(path):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="kdec-ref-") as tmp:
            blocks = load_reference(str(_download(path.strip(), tmp)))  # read into memory before cleanup
        blocks[0]["text"] = blocks[0]["text"].replace("Reference file", f"Reference from {path.strip()} —", 1)
        return blocks
    p = Path(path).expanduser()
    if not p.is_file():
        raise ValueError(f"{p.name}: file not found")
    ext = p.suffix.lower()
    label = {"type": "text", "text": f'Reference file "{p.name}":'}
    if ext in IMAGE_EXT:
        img = _image_payload(str(p))
        if not img:
            raise ValueError(f"{p.name}: couldn't read this image")
        return [label, {"type": "image", "source": {"type": "base64", "media_type": img[0], "data": img[1]},
                        "_file": f"ref-{p.stem}.jpg"}]
    if ext == ".pdf":
        if p.stat().st_size > MAX_PDF_BYTES:
            raise ValueError(f"{p.name}: PDF is larger than 30 MB — export just the relevant pages")
        data = base64.b64encode(p.read_bytes()).decode()
        return [label, {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                        "data": data}, "_file": f"ref-{p.name}"}]
    if ext == ".docx":
        text = _docx_text(p)
    else:
        raw = p.read_bytes()
        if ext not in TEXT_EXT and b"\0" in raw[:4096]:
            raise ValueError(f"{p.name}: unsupported file type — use an image, PDF, .docx or text file")
        text = raw.decode("utf-8", errors="replace")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"{p.name}: too long ({len(text):,} characters; limit {MAX_TEXT_CHARS:,}) — "
                         "trim it to the relevant part")
    return [{"type": "text", "text": f'Reference file "{p.name}":\n```\n{text}\n```'}]


def _clean(block: dict) -> dict:
    """Drop our private `_` keys before sending a block to an API."""
    return {k: v for k, v in block.items() if not k.startswith("_")}


def _pdf_text(b64: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise AIError("this provider can't read PDFs directly and pypdf isn't installed — "
                      "pip install pypdf, or use a Claude provider") from None
    reader = PdfReader(io.BytesIO(base64.b64decode(b64)))
    text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    if len(text) > MAX_TEXT_CHARS:
        raise AIError(f"PDF text is too long for this provider ({len(text):,} characters) — "
                      "use a Claude provider or a shorter PDF")
    return text or "(this PDF has no extractable text — it is probably scanned images)"


# --- reply parsing and checks ----------------------------------------------------------

def parse_reply(text: str, current: spec.Theme | None = None) -> spec.Theme:
    """Extract the TOML theme from an AI reply. Raises ValueError with a fixable message."""
    m = re.findall(r"```(?:toml)?\s*\n(.*?)```", text, re.S)
    body = max(m, key=len) if m else text
    try:
        data = tomllib.loads(body)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"reply is not valid TOML: {e}") from None
    data.pop("wallpaper", None)
    data.pop("author", None)  # personal data is the user's to fill in; models may guess it from their account
    theme = spec.from_dict(data)
    for k, v in vars(theme.palette).items():
        if v:
            color.parse(v)
    if current is not None:
        theme.wallpaper = current.wallpaper
        theme.author = current.author
        theme.iconset.signature = current.iconset.signature        # generated files are the user's
        theme.iconset.signature_dir = current.iconset.signature_dir
    return theme


def check(theme: spec.Theme, installed: dict[str, list[str]] | None = None) -> list[str]:
    """Problems worth fixing: unreadable colors, themes that aren't installed."""
    installed = installed if installed is not None else system.summary()
    p = theme.palette.resolved()
    out: list[str] = []
    for label, a, b, need in [("foreground on background", p.foreground, p.background, 4.5),
                              ("foreground on surface", p.foreground, p.surface, 4.5),
                              ("accent on background", p.accent, p.background, 3.0)]:
        r = color.contrast(a, b)
        if r < need:
            out.append(f"{label} contrast is {r:.1f}:1 (needs >= {need}:1)")
    fields = (["widget_style"] + ([] if theme.iconset.generate else ["icons"])
              + ([] if theme.cursorset.generate else ["cursors"])
              + ([] if theme.plasma.generate else ["plasma_style"]))
    for f in fields:
        names = installed.get(f, [])
        val = getattr(theme, f)
        if names and val and val.lower() not in {n.lower() for n in names}:
            out.append(f"{f} = {val!r} is not installed (installed: {', '.join(names)})")
    if theme.splash_screen.generate and theme.splash_screen.background == "wallpaper" and not theme.wallpaper:
        out.append('splash_screen.background = "wallpaper" but no wallpaper is set: the splash uses the gradient')
    if theme.widgets.generate and not system.kvantum_installed():
        out.append("widgets.generate needs Kvantum, which is not installed here: apps will keep "
                   f"{theme.widget_style!r} (install the kvantum package)")
    if theme.login_screen.generate and not system.plasma_login_installed():
        out.append("login_screen.generate needs Plasma Login Manager, which is not installed here: "
                   "the login screen is left as is")
    if theme.cursorset.generate:
        from .cursorset import scalable_themes
        bases = scalable_themes()
        if theme.cursorset.base.lower() not in {b.lower() for b in bases}:
            out.append(f"cursorset.base = {theme.cursorset.base!r} is not an installed cursor theme with SVG "
                       f"cursors (usable: {', '.join(bases) or 'none'})")
    if theme.iconset.generate:
        from .iconset import find_theme_dir
        if find_theme_dir(theme.iconset.base) is None:
            out.append(f"iconset.base = {theme.iconset.base!r} is not installed (installed: "
                       f"{', '.join(installed.get('icons', []))})")
    return out


# --- calling a provider ------------------------------------------------------------

def _image_payload(path: str) -> tuple[str, str] | None:
    """(media_type, base64) downscaled to <=1568px so it fits every provider's limits."""
    p = Path(path).expanduser()
    if not p.is_file():
        return None
    try:
        from PIL import Image
    except ImportError:
        if p.stat().st_size > 3_500_000 or p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            return None
        mt = {".png": "image/png", ".webp": "image/webp"}.get(p.suffix.lower(), "image/jpeg")
        return mt, base64.b64encode(p.read_bytes()).decode()
    with Image.open(p) as im:
        im = im.convert("RGB")
        im.thumbnail((1568, 1568))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    return "image/jpeg", base64.b64encode(buf.getvalue()).decode()


def _call_anthropic(prov: Provider, system_prompt: str, messages: list[dict], api_key: str | None) -> str:
    try:
        import anthropic
    except ImportError:
        raise AIError("Claude needs the Anthropic SDK: pip install 'kdecustomizer[ai]'") from None
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    try:
        resp = client.beta.messages.create(
            model=prov.model or CLAUDE_MODEL,
            max_tokens=16000,
            system=system_prompt,
            messages=[{"role": m["role"], "content": m["content"] if isinstance(m["content"], str)
                       else [_clean(b) for b in m["content"]]} for m in messages],
            output_config={"effort": "medium"},
            # On a safety decline, the API retries on a fallback model inside the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError:
        raise AIError("Claude: not signed in — set ANTHROPIC_API_KEY (or an API key in AI settings)") from None
    except anthropic.RateLimitError:
        raise AIError("Claude: rate limited — try again in a minute") from None
    except anthropic.APIStatusError as e:
        raise AIError(f"Claude: API error {e.status_code}: {e.message}") from None
    except anthropic.APIConnectionError:
        raise AIError("Claude: could not connect — check your network") from None
    if resp.stop_reason == "refusal":
        raise AIError("Claude declined this request")
    return "".join(b.text for b in resp.content if b.type == "text")


def _call_claude_code(prov: Provider, system_prompt: str, messages: list[dict], api_key: str | None) -> str:
    """Run the `claude` CLI headless (-p). It uses the user's Claude Code login, not an API key.

    -p is single-shot, so the conversation (incl. fix-up rounds) is flattened into one prompt. Images and
    PDFs (wallpaper, references) are written to a private temp dir; the only tool allowed is Read, and only
    when there are such files.
    """
    import shutil
    import subprocess
    import tempfile

    exe = shutil.which("claude")
    if not exe:
        raise AIError("Claude Code isn't installed — install it, run `claude` once to sign in, then retry")
    with tempfile.TemporaryDirectory(prefix="kdec-ai-") as tmp:
        parts: list[str] = []
        files: dict[str, str] = {}  # file name -> base64 data (first message only; retries repeat it)
        for m in messages:
            blocks = [{"type": "text", "text": m["content"]}] if isinstance(m["content"], str) else m["content"]
            texts = []
            for b in blocks:
                if b["type"] in ("image", "document"):
                    name = re.sub(r"[^\w.-]+", "_", b.get("_file") or f"attachment{len(files)}")
                    if name in files:
                        name = f"{len(files)}-{name}"
                    files[name] = b["source"]["data"]
                    Path(tmp, name).write_bytes(base64.b64decode(b["source"]["data"]))
                    texts.append(f"(file ./{name} — open it with the Read tool)")
                elif b["type"] == "text":
                    texts.append(b["text"])
            who = "Me" if m["role"] == "user" else "You (earlier)"
            parts.append(f"[{who}]\n" + "\n\n".join(texts))
        prompt = "\n\n".join(parts) if len(parts) > 1 else "\n\n".join(parts).split("\n", 1)[1]

        cmd = [exe, "-p", "--output-format", "json", "--system-prompt", system_prompt,
               "--no-session-persistence", "--strict-mcp-config", "--max-turns", str(4 + 4 * len(files))]  # long PDFs take several Reads
        cmd += ["--tools", "Read", "--allowedTools", "Read"] if files else ["--tools", ""]
        if prov.model:
            cmd += ["--model", prov.model]
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=tmp, env=env, timeout=600)
        except subprocess.TimeoutExpired:
            raise AIError("Claude Code took longer than 10 minutes — try a simpler request") from None
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        msg = (r.stderr or r.stdout).strip()[:400]
        raise AIError(f"Claude Code failed: {msg or f'exit code {r.returncode}'}") from None
    if data.get("is_error") or data.get("subtype") != "success":
        detail = data.get("result") or data.get("subtype") or "unknown error"
        if "login" in str(detail).lower() or "auth" in str(detail).lower():
            detail = f"{detail} — run `claude` in a terminal and sign in"
        raise AIError(f"Claude Code: {detail}")
    return data.get("result", "")


def _to_openai(system_prompt: str, messages: list[dict]) -> list[dict]:
    out = [{"role": "system", "content": system_prompt}]
    for m in messages:
        if isinstance(m["content"], str):
            out.append(m)
            continue
        parts = []
        for b in m["content"]:
            if b["type"] == "text":
                parts.append({"type": "text", "text": b["text"]})
            elif b["type"] == "image":
                src = b["source"]
                parts.append({"type": "image_url",
                              "image_url": {"url": f"data:{src['media_type']};base64,{src['data']}"}})
            elif b["type"] == "document":  # no portable PDF input in the OpenAI format: send its text
                parts.append({"type": "text", "text": f"(text extracted from the PDF)\n```\n"
                                                      f"{_pdf_text(b['source']['data'])}\n```"})
        out.append({"role": m["role"], "content": parts})
    return out


def _call_openai(prov: Provider, system_prompt: str, messages: list[dict], api_key: str | None) -> str:
    if not prov.model:
        raise AIError(f"{prov.name}: choose a model name in AI settings")
    key = api_key or (os.environ.get(prov.key_env, "") if prov.key_env else "")
    if prov.key_env and not key:
        raise AIError(f"{prov.name}: set {prov.key_env} (or an API key in AI settings)")
    body = json.dumps({"model": prov.model, "messages": _to_openai(system_prompt, messages)}).encode()
    req = urllib.request.Request(prov.base_url.rstrip("/") + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {key}"} if key else {})})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise AIError(f"{prov.name}: HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise AIError(f"{prov.name}: could not connect to {prov.base_url} ({e.reason})") from None
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise AIError(f"{prov.name}: unexpected response: {str(data)[:300]}") from None


def call_provider(prov: Provider, system_prompt: str, messages: list[dict], api_key: str | None = None) -> str:
    """One round-trip to any provider. `messages` use Anthropic-style content blocks (text/image/document)."""
    fn = {"claude-code": _call_claude_code, "anthropic": _call_anthropic}.get(prov.kind, _call_openai)
    return fn(prov, system_prompt, messages, api_key)


def generate(request: str, current: spec.Theme | None, prov: Provider, *, api_key: str | None = None,
             use_wallpaper: bool = True, references: list[str] = (), attempts: int = 2,
             log=lambda s: None) -> tuple[spec.Theme, str, list[str]]:
    """Ask the provider for a theme. Returns (theme, model's design note, remaining warnings).

    `references`: images, PDFs, .docx or text files to build the theme from (brand guide, mood board…).
    """
    installed = system.summary()
    system_prompt = reference(installed)
    content: list[dict] = []
    if use_wallpaper and current is not None and current.wallpaper:
        img = _image_payload(current.wallpaper)
        if img:
            content += [{"type": "text", "text": "WALLPAPER:"},
                        {"type": "image", "source": {"type": "base64", "media_type": img[0], "data": img[1]},
                         "_file": "wallpaper.jpg"}]
            log("attached wallpaper image")
    if references:
        content.append({"type": "text", "text": "REFERENCE material — build the theme from this:"})
        for r in references:
            try:
                content += load_reference(r)
            except ValueError as e:
                raise AIError(str(e)) from None
        log(f"attached {len(references)} reference file{'s' if len(references) != 1 else ''}")
    content.append({"type": "text", "text": request_text(request, current)})
    messages: list[dict] = [{"role": "user", "content": content}]
    call = call_provider

    theme: spec.Theme | None = None
    problems: list[str] = []
    reply = ""
    for i in range(attempts):
        log(f"asking {prov.name}{' (fixing issues)' if i else ''}…")
        reply = call(prov, system_prompt, messages, api_key)
        try:
            candidate = parse_reply(reply, current)
        except ValueError as e:
            problems = [str(e)]
            log(f"reply rejected: {e}")
        else:
            theme = candidate
            problems = check(theme, installed)
            if not problems:
                break
            log("issues: " + "; ".join(problems))
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": "Fix these problems and reply with the full corrected "
                                                 "theme:\n- " + "\n- ".join(problems)}]
    if theme is None:
        raise AIError("the AI did not return a usable theme: " + "; ".join(problems))
    note = re.sub(r"```.*?```", "", reply, flags=re.S).strip()
    return theme, note, problems
