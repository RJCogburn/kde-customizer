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
    kind: str              # "anthropic" | "openai"
    base_url: str = ""
    key_env: str = ""      # env var holding the API key ("" = no key needed)
    model: str = ""


PRESETS: dict[str, Provider] = {
    "claude": Provider("Claude (Anthropic)", "anthropic", model=CLAUDE_MODEL),
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
  go opaque when a window is maximized. With `generate = false`, `plasma_style` names an installed style.
- `icons`, `cursors`, `plasma_style`, `widget_style`: must be INSTALLED names (list below).
- `splash`: keep "org.kde.Breeze" unless asked.
- `[decoration]` window title-bar buttons: `buttons_left` / `buttons_right` are strings of codes:
  M menu, S on-all-desktops, H help, F keep-above, B keep-below, I minimize, A maximize, X close,
  _ spacer. macOS-like = left "XIA", right "". Windows-like = left "M", right "IAX".
- `[fonts]`: "Family,size" e.g. "Inter,10"; "" leaves the user's font unchanged. Only use common fonts.
- `[[panels]]` (repeat for several): `location` top|bottom|left|right; `height` px (24–80 typical);
  `floating`; `alignment` left|center|right; `length_mode` fill|fit (fit = dock-like);
  `widgets` = ordered plasmoid ids. Common ids: org.kde.plasma.kickoff (app menu),
  org.kde.plasma.icontasks (icon-only task manager), org.kde.plasma.taskmanager (with labels),
  org.kde.plasma.pager, org.kde.plasma.marginsseparator, org.kde.plasma.panelspacer (flexible gap),
  org.kde.plasma.systemtray, org.kde.plasma.digitalclock, org.kde.plasma.showdesktop.
- `konsole = true` adds a matching terminal scheme.
- `[tweaks.<file>.<group>]` raw KDE config writes, e.g. `[tweaks.kwinrc.Plugins] blurEnabled = true`.
  Only use keys you are sure exist.
- Do NOT set `wallpaper` (the user picks the file).

## Design rules
- Readability: foreground vs background and vs surface contrast >= 4.5:1 (aim for 7+);
  accent vs background >= 3:1.
- `surface` is a subtle step from `background` (a few % lighter on dark themes, darker on light ones),
  not a different hue family.
- Keep positive/neutral/negative recognisable as green/amber/red, tuned to sit with the palette.
- If an image is attached it is the wallpaper: pull the palette from it (background from its dark/light
  areas, accent from its most characterful color) so the desktop feels like one piece.

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


def prompt_text(request: str, current: spec.Theme | None = None) -> str:
    """One self-contained prompt to paste into any chat AI."""
    return reference() + "\n---\n\n" + request_text(request, current)


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
    theme = spec.from_dict(data)
    for k, v in vars(theme.palette).items():
        if v:
            color.parse(v)
    if current is not None:
        theme.wallpaper = current.wallpaper
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
    fields = ["icons", "cursors", "widget_style"] + ([] if theme.plasma.generate else ["plasma_style"])
    for f in fields:
        names = installed.get(f, [])
        val = getattr(theme, f)
        if names and val and val.lower() not in {n.lower() for n in names}:
            out.append(f"{f} = {val!r} is not installed (installed: {', '.join(names)})")
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
            messages=messages,
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


def generate(request: str, current: spec.Theme | None, prov: Provider, *, api_key: str | None = None,
             use_wallpaper: bool = True, attempts: int = 2, log=lambda s: None) -> tuple[spec.Theme, str, list[str]]:
    """Ask the provider for a theme. Returns (theme, model's design note, remaining warnings)."""
    installed = system.summary()
    system_prompt = reference(installed)
    content: list[dict] = []
    if use_wallpaper and current is not None and current.wallpaper:
        img = _image_payload(current.wallpaper)
        if img:
            content.append({"type": "image", "source": {"type": "base64", "media_type": img[0], "data": img[1]}})
            log("attached wallpaper image")
    content.append({"type": "text", "text": request_text(request, current)})
    messages: list[dict] = [{"role": "user", "content": content}]
    call = _call_anthropic if prov.kind == "anthropic" else _call_openai

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
