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
```
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
7. GUI: live preview, panel editor, tweaks editor.

## Portability rule
Built output must not contain paths from the build machine. Wallpaper is bundled in `wallpapers/` and set by
`install.sh` via `plasma-apply-wallpaperimage "$DATA/..."`; the bundled `theme.toml` uses a relative wallpaper path.
