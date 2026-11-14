# KDE Customizer

Build complete KDE Plasma 6 themes from one small TOML file, preview them live, and install them with one
click. You can also describe a theme in plain words and let an AI design it.

![KDE Customizer: editor with live desktop preview](docs/screenshot.png)

From about seven palette colors, one theme spec generates:

- a **color scheme** for all apps
- a **Plasma style** (panels, popups, widgets) recolored to match, with blur and adaptive transparency
- a **global theme** package (icons, cursors, app style, window decoration, splash)
- a **panel layout**: position, size, floating or dock-style, and widget order
- a matching **Konsole** color scheme and profile
- **fonts**, title-bar buttons and any raw KDE setting (`[tweaks]`)
- a standalone **`install.sh`**, so a built theme can be shared and installed without this tool

## Install

Requires Plasma 6 and Python 3.11+.

```sh
git clone https://github.com/RJCogburn/kde-customizer.git
cd kde-customizer
pip install -e '.[gui]'        # add ',ai' for the Claude API provider and wallpaper downscaling
```

### AppImage

Prefer a single file? Build one (about 105 MB, bundles Python and Qt; no install needed):

```sh
packaging/appimage/build.sh              # -> dist/KDE_Customizer-<version>-x86_64.AppImage
./dist/KDE_Customizer-*.AppImage         # GUI
./dist/KDE_Customizer-*.AppImage build mytheme.toml   # any kdec command works too
```

Inside the AppImage the app uses Qt's own style instead of your Breeze style, because the bundled Qt can't
load the system's KDE style plugin. Themes it builds are unaffected.

## Use

**GUI:** `kdec-gui examples/midnight.toml`

Edit colors, panels, fonts and the rest in the tabs on the left. The preview on the right redraws as you
type and uses the theme's own icon set. **Apply to desktop** installs the theme and switches to it.

**Command line:**

```sh
kdec new mytheme.toml                  # starter spec
kdec build mytheme.toml                # -> build/<Name>/
kdec apply mytheme.toml --dry-run      # show what would change
kdec apply mytheme.toml [--layout]     # install + apply (--layout also replaces your panels)
kdec export mytheme.toml               # shareable <Name>.tar.gz including the wallpaper
kdec check mytheme.toml                # readability (contrast) and missing-theme warnings
```

Someone you share an export with only needs `tar xzf Name.tar.gz && ./Name/install.sh`.

## Design with AI

Type a request such as *“cozy autumn, warm browns, dock-style bottom panel”* or *“make the accent teal”*
into **Design with AI** (GUI) or run:

```sh
kdec ai "cozy autumn, dock-style panel" --from mytheme.toml
```

**Design from something:** attach images, PDFs (a product brochure, brand guide or mood board), Word or
text files, or a link to any of them, and the AI builds the theme from them: exact hex codes, key colors,
light or dark mood, and style cues like a dock or flat panels. In the GUI use **Attach → Files… / Link…**
or drag files and links onto the AI panel. On the command line use `--ref` (repeatable):

```sh
kdec ai "luxury explorer feel" --ref https://example.com/brochure.pdf --ref moodboard.png
```

Claude providers see PDFs page by page, visuals included. Other providers get images plus the PDF's text.

With **Match wallpaper** on, the AI looks at your wallpaper and builds the palette from it. Every result is
checked for readable contrast and for icon, cursor and Plasma themes that aren't installed. If a check
fails, the AI is asked to fix it once.

| Provider | What you need |
| --- | --- |
| **Claude Code** (default) | The `claude` CLI, signed in. Uses your Claude plan, no API key. |
| Claude API | `ANTHROPIC_API_KEY` and `pip install -e '.[ai]'` |
| OpenAI / Gemini / OpenRouter | API key env var and a model name |
| Ollama / LM Studio | A local server and a model name |

Choose the provider with the gear button in the GUI, or with `--provider` / `--model` on the command line.

**Any chat AI, no setup:** in the GUI menu use *Copy prompt for any chat AI*, paste it into the AI, then
*Paste AI reply…*. On the command line, `kdec ai "..." --prompt-only` prints the same prompt.

**Coding agents:** `kdec ai-guide` prints the full spec reference, including the themes installed on this
machine, so an agent can write theme files directly.

## Theme spec

```toml
name = "Midnight"
id = "org.kdecustomizer.midnight"
icons = "breeze-dark"
wallpaper = "wallpapers/night.jpg"

[palette]
background = "#14151f"
surface = "#1d1f2d"
foreground = "#e4e4f0"
accent = "#8b7cf6"

[plasma]
generate = true        # palette-matched Plasma style

[[panels]]
location = "bottom"
floating = true
length_mode = "fit"    # dock-style
widgets = ["org.kde.plasma.kickoff", "org.kde.plasma.icontasks", "org.kde.plasma.systemtray", "org.kde.plasma.digitalclock"]
```

See [`examples/midnight.toml`](examples/midnight.toml) for a complete spec, or run `kdec ai-guide` for
every key.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
