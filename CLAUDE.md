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

## Window decoration (`[decoration] generate = true`)
`generators/aurorae.py` → `build/<Slug>/aurorae/<Slug>-Decoration/` (installed to `$DATA/aurorae/themes/`):
`decoration.svg` (FrameSvg, prefixes `decoration-` / `decoration-inactive-`), one SVG per button with
`active|hover|pressed|inactive|deactivated-center`, `<name>rc` (sizes, title colors), metadata. The frame
covers shadow padding + title bar + borders; pieces may reach under the client window, only their bounding sizes
matter, and the stretched middle must be constant. KWin name: `__aurorae__svg__<Slug>-Decoration`
(`Theme.decoration_kwin`). Colors are plain hex from `colors.scheme()["WM"]` (Aurorae isn't recolored).
The engine's QML is in `/usr/share/kwin/aurorae/` — read it for element names and layout.

## App style (`[widgets] generate = true`)
`generators/kvantum.py` → `build/<Slug>/kvantum/<Slug>/<Slug>.{kvconfig,svg}` (installed to `~/.config/Kvantum/`).
kvconfig = one section per widget (element names, `frame.*` thickness — frame pieces are scaled to it — and text
colors); SVG = `<el>-<state>` interior + `<el>-<state>-top|…|bottomright` frame per state (normal, focused = hover,
pressed, toggled, disabled), plus indicators (arrows, checkbox/radio, slidercursor). An empty element = draw
nothing. Colors all come from `colors.scheme()`. LnF sets `widget_style` (the fallback); `install.sh` switches
kdeglobals to `kvantum` only if Kvantum is installed. Test with the real plugin, without touching the user's
config: copy the build into `<tmp>/Kvantum/`, then run `/usr/bin/python3` (system PySide6 — the venv's Qt can't
load the system plugin) with `XDG_CONFIG_HOME=<tmp> QT_STYLE_OVERRIDE=kvantum QT_QPA_PLATFORM=offscreen`.
Reference themes: `/usr/share/Kvantum/` (KvFlat is the closest to ours).

## Splash screen (`[splash_screen] generate = true`)
`generators/splash.py` → `contents/splash/Splash.qml` in the LnF (+ `images/background.*` = the wallpaper, when
`background = "wallpaper"`), and ksplashrc `Theme` = the LnF id (`Theme.splash_name`). ksplashqml raises the root's
`stage` 1→6; ours fades in from stage 2 and fills a bar with stage/6. Only QtQuick + Kirigami. Render offscreen with
`/usr/bin/python3` (system PySide6 has Kirigami): QQuickView on Splash.qml, set `stage`, `grabWindow()`.
`ksplashqml --test <lnf id>` shows it for real (full screen, a few seconds).

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
`plasmarc` carries Blur/Contrast/AdaptiveTransparency hints.
Shapes: when `[plasma] radius/opacity/outline` differ from Breeze (6 / 0.85 / false), `plasmastyle.svgs()` also
writes FrameSvg SVGs (`dialogs/background`, `widgets/{panel-background,tooltip,background}`, in base,
`translucent/` and `solid/`): nine frame pieces + `hint-*-margin` + `mask-*` + `shadow-*` (+ panel `thick-*`).
FrameSvg only reads each element's bounding size, so pieces sit side by side on the canvas with no transforms.
Check shape changes by tiling the pieces with `QSvgRenderer.render(p, id, rect)` offscreen. `install.sh` copies it to `$DATA/plasma/desktoptheme/`
and deletes `~/.cache/plasma_theme_<Slug>*` so re-installs pick up new colors. `Theme.plasma_style_name` is what LnF sets.

## Roadmap (not built yet)
1. **Cursors, SDDM** — SDDM needs root (pkexec).
2. **Snapshot** — `kdec snapshot` to read the current desktop config into a spec.
3. GUI: tweaks editor; preview of the Kickoff menu / dialogs.

## Packaging / releases
`packaging/appimage/build.sh` (python-appimage -> `trim-runtime.sh` -> AppImage; leaves `build/appdir`) then
`packaging/build-packages.sh` (stages `build/pkgroot` -> .tar.gz + nfpm .deb/.rpm with the bundled runtime in
/opt/kde-customizer). `packaging/aur/PKGBUILD` builds from source against Arch's pyside6. CI:
`.github/workflows/release.yml` on `v*` tags (build, makepkg, install tests on 7 distros, attach to release; the
makepkg result is attached too as the Arch package, since the AUR has no account for this yet).
Release = bump version in `pyproject.toml` + `src/kdecustomizer/__init__.py` + `packaging/aur/PKGBUILD`, tag.
`trim-runtime.sh` must leave every Qt lib resolving inside the bundle — it checks with ldd.

## Portability rule
Built output must not contain paths from the build machine. Wallpaper is bundled in `wallpapers/` and set by
`install.sh` via `plasma-apply-wallpaperimage "$DATA/..."`; the bundled `theme.toml` uses a relative wallpaper path.
