# KDE Customizer

Builds complete KDE Plasma 6 themes from a single TOML spec, and installs/applies them.
Target system: Plasma 6.8, Qt 6, Python 3.11+ (dev box runs 3.14, CachyOS).

## Architecture
- `src/kdecustomizer/spec.py` — `Theme` dataclasses = the spec. TOML in (`tomllib`), TOML out (tiny hand-rolled writer).
- `color.py` — hex/RGB helpers; `shift()` moves a color away from the background (lighter on dark themes).
- `generators/` — one module per output artifact, each a pure function `Theme -> str`. No I/O.
- `build.py` — writes everything to `build/<Slug>/` **plus a standalone `install.sh`**. Installing/applying always goes
  through that script (CLI and GUI both run it), so built themes are shareable without this tool.
- `cli.py` (`kdec`) and `gui/app.py` (`kdec-gui`, PySide6) are thin front ends — keep logic in core modules.
- `system.py` — lists installed icon/cursor/Plasma/widget styles (editor dropdowns + AI prompt).
- `ai.py` — provider-neutral AI design. Default provider `claude-code` runs `claude -p` (user's Claude Code login,
  no API key; API-key env vars are stripped; only the Read tool, for a temp wallpaper copy). `reference()` (spec guide + installed themes), `parse_reply()`,
  `check()` (contrast + not-installed), `generate()` (Claude via `anthropic` SDK; others via OpenAI-compatible
  `/chat/completions` with urllib; one automatic fix-up round when `check()` complains).

## Icons
- `iconset.py` — generated icon theme `<Slug>-Icons`: recolors the base theme's folder/place SVGs (hex fills
  near the base's dominant folder hue -> accent, HLS shift) and `Inherits=` the base. Papirus color variants
  (`folder-red*`…) and symbolic icons are skipped. Any icon name present in our theme must exist in all the
  base's sizes for it, or KDE won't fall back to the base for missing sizes.
- `signature.py` — 14 `SLOTS` made custom: `svg` (AI JSON of SVGs, sanitized), `image` (local image AI), or
  `import`. Stored in `<spec dir>/<slug>-icons/{svg,png}/<slot>.*`; they replace recolored versions.
- `imagegen.py` — Fooocus (Gradio 3 queue over a stdlib websocket; settings matched by label), ComfyUI,
  A1111/Forge. `to_icon()` cuts the background (rembg if installed, else edge flood fill).
  Running image gens uses the user's GPU — test with `--only` and a couple of icons.

## GUI
`gui/app.py` = editor tabs (left) + `gui/preview.py` live preview (right) + `gui/ai_panel.py` on top.
The preview paints a mock desktop on a fixed 1280x800 canvas from `colors.scheme()` / `konsole.ansi()` — the
same functions the generators use, so never derive colors in the GUI. Icons come from the theme's icon set via
`IconCache` (temporarily switches `QIcon.themeName`). AI work runs in a QThread; connect worker signals to
bound methods of a widget (lambdas would run on the worker thread). AI provider settings live in QSettings
(`~/.config/kdecustomizer/kdec-gui.conf`).
Offscreen screenshots for checking UI changes: `QT_QPA_PLATFORM=offscreen`, `w.grab().save(...)`.

## What Look-and-Feel can and can't do
`plasma-apply-lookandfeel` only applies the keys in `contents/defaults` (colors, widget style, icons, plasma style,
cursors, decoration, splash) and the layout JS with `--resetLayout`. Anything else (fonts, decoration buttons,
KWin effects, arbitrary `tweaks`) is written by `install.sh` with `kwriteconfig6`, then `qdbus6 org.kde.KWin /KWin reconfigure`.

## Commands
```
pip install -e '.[gui]'          # or run with PYTHONPATH=src python -m kdecustomizer.cli
kdec new mytheme.toml
kdec build examples/midnight.toml          # -> build/Midnight/
kdec apply examples/midnight.toml [--layout] [--dry-run]
kdec export examples/midnight.toml [out.tar.gz]  # shareable archive: build + wallpaper + theme.toml; recipient runs ./install.sh
kdec layout examples/midnight.toml         # live panel/wallpaper script via plasmashell evaluateScript
kdec-gui examples/midnight.toml
kdec check mytheme.toml                    # contrast + installed-theme warnings
kdec ai "warm autumn, dock panel" [--from mytheme.toml] [--provider claude-code(default)|claude|openai|gemini|openrouter|ollama|lmstudio --model M]
kdec ai "..." --prompt-only                # prompt to paste into any chat AI
kdec ai-guide                              # spec guide for coding agents — read it before writing a theme spec
```
AI extras: `pip install -e '.[ai]'` (anthropic SDK + Pillow). Never run `kdec ai` against a real provider in
tests (it bills); use a local fake server on `--base-url` / `ANTHROPIC_BASE_URL`.
`apply` changes the live desktop — use `--dry-run` when testing generator changes.

## Plasma style (`[plasma] generate = true`)
`generators/plasmastyle.py` → `build/<Slug>/plasma/<Slug>/` = `metadata.json` + `colors` + `plasmarc`, **no SVGs** — same
trick as stock Breeze Dark: missing SVGs fall back to `default`, whose `ColorScheme-*` classes read the theme's `colors`.
`plasmarc` carries Blur/Contrast/AdaptiveTransparency hints. `install.sh` copies it to `$DATA/plasma/desktoptheme/`
and deletes `~/.cache/plasma_theme_<Slug>*` so re-installs pick up new colors. `Theme.plasma_style_name` is what LnF sets.

## Roadmap (not built yet)
1. **Plasma style shapes** — ship our own SVGs (corner radius, panel outline/opacity) on top of the colors-only style.
2. **Aurorae window decoration** — SVG titlebar/buttons from palette.
3. **Kvantum theme** — `.kvconfig` + `.svg`; set `widget_style = "kvantum"`, write `~/.config/Kvantum/kvantum.kvconfig`.
4. **Icons** — recolor an existing icon theme (folder colors from accent) into a new inherited theme.
5. **Cursors, SDDM, splash** — SDDM needs root (pkexec); splash = QML package in the LnF.
6. **Snapshot** — `kdec snapshot` to read the current desktop config into a spec.
7. GUI: tweaks editor; preview of the Kickoff menu / dialogs.

## Portability rule
Built output must not contain paths from the build machine. Wallpaper is bundled in `wallpapers/` and set by
`install.sh` via `plasma-apply-wallpaperimage "$DATA/..."`; the bundled `theme.toml` uses a relative wallpaper path.
