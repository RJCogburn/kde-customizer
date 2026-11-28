"""Turn a Theme into a self-contained build directory with its own install.sh."""
from __future__ import annotations

import json
import shlex
import shutil
import sys
import tarfile
from dataclasses import replace
from pathlib import Path

from . import cursorset, iconset
from .generators import (
    apps, aurorae, bootsplash, colors, gtk, konsole, kvantum, layout, lightdark, lookandfeel, loginscreen, mozilla,
    plasmastyle, restore, splash,
)
from .spec import Theme, save

_FONT_KEYS = {  # Fonts field -> (file, group, key)
    "general": ("kdeglobals", "General", "font"),
    "fixed": ("kdeglobals", "General", "fixed"),
    "small": ("kdeglobals", "General", "smallestReadableFont"),
    "toolbar": ("kdeglobals", "General", "toolBarFont"),
    "menu": ("kdeglobals", "General", "menuFont"),
    "window_title": ("kdeglobals", "WM", "activeFont"),
}


def all_tweaks(theme: Theme) -> dict[str, dict[str, dict[str, object]]]:
    """User tweaks + settings derived from the spec that Look-and-Feel can't apply itself."""
    t: dict[str, dict[str, dict[str, object]]] = {}

    def put(f, g, k, v):
        t.setdefault(f, {}).setdefault(g, {})[k] = v

    d = theme.decoration
    put("kwinrc", "org.kde.kdecoration2", "ButtonsOnLeft", d.buttons_left)
    put("kwinrc", "org.kde.kdecoration2", "ButtonsOnRight", d.buttons_right)
    if theme.splash_screen.generate:
        # same reason as below: LnF skips its defaults when re-applying the same global theme
        put("ksplashrc", "KSplash", "Engine", "KSplashQML")
        put("ksplashrc", "KSplash", "Theme", theme.splash_name)
    if d.generate:
        # LnF sets these too, but only when the global theme changes; this re-applies on every install.
        lib, deco = theme.decoration_kwin
        put("kwinrc", "org.kde.kdecoration2", "library", lib)
        put("kwinrc", "org.kde.kdecoration2", "theme", deco)
    if theme.light_dark.auto:
        from . import variant
        light, dark = variant.pair(theme)
        put("kdeglobals", "KDE", "DefaultLightLookAndFeel", light.id)
        put("kdeglobals", "KDE", "DefaultDarkLookAndFeel", dark.id)
        put("kdeglobals", "KDE", "AutomaticLookAndFeel", True)
    for field, (f, g, k) in _FONT_KEYS.items():
        val = getattr(theme.fonts, field)
        if val:
            put(f, g, k, konsole._qfont(val))
    for f, groups in theme.tweaks.items():
        for g, kv in groups.items():
            for k, v in kv.items():
                put(f, g, k, v)
    return t


def _kwrite(file: str, group: str, key: str, value: object) -> str:
    v = ("true" if value else "false") if isinstance(value, bool) else str(value)
    groups = " ".join(f"--group {shlex.quote(g)}" for g in group.split("/"))
    # --notify: running apps that watch their config (Plasma, screen locker, notifications) reload it now
    return f"kwriteconfig6 --notify --file {shlex.quote(file)} {groups} --key {shlex.quote(key)} {shlex.quote(v)}"


def build(theme: Theme, out_root: str | Path = "build") -> Path:
    """Write the complete theme into <out_root>/<Slug>/: Look-and-Feel package, color scheme, every generated part, the
    bundled wallpaper and icon folders, a portable theme.toml, install.sh and restore-point.sh. Returns that folder."""
    original = theme
    if theme.cursorset.generate and not cursorset.base_available(theme):
        # e.g. a shared spec built on a machine without the base: fall back to the named installed cursors
        print(f"warning: [cursorset] base '{theme.cursorset.base}' with SVG cursors is not installed here; "
              f"using cursors = '{theme.cursors}' instead", file=sys.stderr)
        theme = replace(theme, cursorset=replace(theme.cursorset, generate=False))
    out = Path(out_root) / theme.slug
    if out.exists():
        shutil.rmtree(out)
    lnf = out / "lookandfeel" / theme.id
    (lnf / "contents/layouts").mkdir(parents=True)
    (out / "color-schemes").mkdir()

    if theme.wallpaper:
        src = Path(theme.wallpaper).expanduser()
        if not src.is_file():
            raise FileNotFoundError(f"wallpaper not found: {src}")
        (out / "wallpapers").mkdir()
        shutil.copy2(src, out / "wallpapers" / src.name)

    from . import previews
    previews.render(theme, lnf / "contents/previews")      # System Settings' pictures (else Breeze's are shown)
    (lnf / "metadata.json").write_text(lookandfeel.metadata(theme))
    (lnf / "contents/defaults").write_text(lookandfeel.defaults(theme))
    (lnf / "contents/layouts/org.kde.plasma.desktop-layout.js").write_text(layout.generate(theme))
    (out / "layout.js").write_text(layout.generate(theme))
    if theme.splash_screen.generate:
        (lnf / "contents/splash").mkdir(parents=True)
        (lnf / "contents/splash/Splash.qml").write_text(splash.qml(theme))
        if bg := splash.background_file(theme):
            (lnf / "contents/splash/images").mkdir()
            shutil.copy2(Path(theme.wallpaper).expanduser(), lnf / "contents/splash/images" / bg)

    if theme.iconset.generate:
        iconset.build(theme, out / "icons")
        sig = Path(theme.iconset.signature_dir) if theme.iconset.signature_dir else None
        if sig and sig.is_dir():  # bundle the generated originals so the shared spec rebuilds the same
            shutil.copytree(sig, out / "signature-icons")
        own = Path(theme.iconset.custom_dir) if theme.iconset.custom_dir else None
        if own and own.is_dir():  # the user's own icons, likewise
            shutil.copytree(own, out / "custom-icons", ignore=shutil.ignore_patterns(".*"))

    if theme.cursorset.generate:
        cursorset.build(theme, out / "cursors")

    # Ship the editable spec too, with the wallpaper / signature icons pointing at the bundled copies.
    portable = replace(original, wallpaper=f"wallpapers/{Path(theme.wallpaper).name}" if theme.wallpaper else "")
    # folders that weren't bundled are dropped: the shared spec must not point into this machine
    portable.iconset = replace(original.iconset,
                               signature_dir="signature-icons" if (out / "signature-icons").is_dir() else "",
                               custom_dir="custom-icons" if (out / "custom-icons").is_dir() else "")
    save(portable, out / "theme.toml")
    (out / "color-schemes" / f"{theme.slug}.colors").write_text(colors.generate(theme))

    if theme.plasma.generate:
        ps = out / "plasma" / theme.plasma_style_name
        ps.mkdir(parents=True)
        (ps / "metadata.json").write_text(plasmastyle.metadata(theme))
        (ps / "colors").write_text(plasmastyle.colors(theme))
        (ps / "plasmarc").write_text(plasmastyle.plasmarc(theme))
        for rel, text in plasmastyle.svgs(theme).items():
            (ps / rel).parent.mkdir(parents=True, exist_ok=True)
            (ps / rel).write_text(text)

    if theme.decoration.generate:
        deco = out / "aurorae" / theme.decoration_name
        deco.mkdir(parents=True)
        for name, text in aurorae.files(theme).items():
            (deco / name).write_text(text)

    if theme.widgets.generate:
        kv = out / "kvantum" / theme.kvantum_name
        kv.mkdir(parents=True)
        for name, text in kvantum.files(theme).items():
            (kv / name).write_text(text)

    if theme.login_screen.generate:
        (out / "login").mkdir()
        for name, text in [("greeter.sh", loginscreen.greeter_script(theme, _FONT_KEYS, konsole._qfont)),
                           ("apply.sh", loginscreen.root_script(theme))]:
            (out / "login" / name).write_text(text)
            (out / "login" / name).chmod(0o755)

    if theme.boot_splash.generate:
        bdir = out / "boot" / bootsplash.name(theme)
        bdir.mkdir(parents=True)
        for fname, data in bootsplash.files(theme).items():
            (bdir / fname).write_bytes(data) if isinstance(data, bytes) else (bdir / fname).write_text(data)
        (out / "boot" / "apply.sh").write_text(bootsplash.apply_script(theme))
        (out / "boot" / "apply.sh").chmod(0o755)

    for rel, data in {**apps.files(theme), **mozilla.files(theme)}.items():
        f = out / "apps" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data) if isinstance(data, bytes) else f.write_text(data)

    if theme.gtk.generate:
        (out / "gtk").mkdir()
        (out / "gtk" / gtk.FILE).write_text(gtk.css(theme))

    if theme.konsole:
        (out / "konsole").mkdir()
        (out / "konsole" / f"{theme.slug}.colorscheme").write_text(konsole.colorscheme(theme))
        (out / "konsole" / f"{theme.slug}.profile").write_text(konsole.profile(theme))

    if theme.light_dark.auto:
        _build_variant(theme, out)

    _write_install_script(theme, out, spec_hash(original))
    return out


# what install.sh takes from the variant's build (the rest would only duplicate the theme's own)
_VARIANT_KEEP = {"lookandfeel", "color-schemes", "plasma", "icons", "cursors", "aurorae", "gtk", "apps", "konsole"}


def _build_variant(theme: Theme, out: Path) -> None:
    """[light_dark] auto: the opposite variant in out/variant/<VSlug>/, plus the follow hook in out/follow/."""
    from . import variant
    vt = variant.opposite(theme)
    vout = build(vt, out / "variant")
    if theme.wallpaper:     # only the theme's own wallpaper package is installed: point the variant at it
        d = vout / "lookandfeel" / vt.id / "contents/defaults"
        d.write_text(d.read_text().replace(f"[Wallpaper]\nImage={vt.slug}\n", f"[Wallpaper]\nImage={theme.slug}\n"))
    for p in vout.iterdir():
        if p.name not in _VARIANT_KEEP:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    f = out / "follow"
    f.mkdir()
    (f / "follow.sh").write_text(lightdark.follow_script())
    (f / f"{lightdark.UNIT}.path").write_text(lightdark.path_unit("@CONF@/kdeglobals"))
    (f / f"{lightdark.UNIT}.service").write_text(lightdark.service_unit("@DATA@/kde-customizer/follow/follow.sh"))


def export(theme: Theme, dest: str | Path | None = None, build_root: str | Path = "build") -> Path:
    """Build, then pack into <Slug>.tar.gz. Recipient: extract, run ./install.sh."""
    out = build(theme, build_root)
    dest = Path(dest) if dest else Path.cwd() / f"{theme.slug}.tar.gz"
    with tarfile.open(dest, "w:gz") as tar:
        tar.add(out, arcname=theme.slug)
    return dest


# Parts install.sh can leave alone this time: key -> (shell variable, option, what it leaves alone).
# Skipped = untouched (not undone), unlike switching a part off in the spec.
SKIP_PARTS = {
    "wallpaper": ("WALLPAPER", "--no-wallpaper", "the wallpaper"),
    "gtk": ("GTK", "--no-gtk", "GTK 4 / libadwaita app colors"),
    "terminals": ("TERMINALS", "--no-terminals", "kitty, Ghostty, WezTerm and Alacritty colors"),
    "browsers": ("BROWSERS", "--no-browsers", "Firefox and Thunderbird colors"),
    "vscode": ("VSCODE", "--no-vscode", "the VS Code color theme"),
    "tweaks": ("TWEAKS", "--no-tweaks", "the theme's tweaks (effects, window behavior…)"),
    "login": ("LOGIN", "--no-login", "the login screen (it needs the admin password)"),
    "boot": ("BOOT", "--no-boot", "the boot splash (admin password + initramfs rebuild)"),
}


def skip_args(keys) -> list[str]:
    """install.sh options for the parts to leave alone."""
    return [SKIP_PARTS[k][1] for k in keys]


def _skippable(key: str, label: str, lines: list[str]) -> list[str]:
    """Run `lines` unless install.sh got this part's --no-… option."""
    if not lines:
        return []
    var, flag, _ = SKIP_PARTS[key]
    return [f"if (( {var} )); then", *lines, "else", f'  echo "==> {label}"', f'  echo "skipped ({flag})"', "fi"]


def _write_install_script(theme: Theme, out: Path, fingerprint: str = "") -> None:
    """Write install.sh (and restore-point.sh) into the build. install.sh runs these steps in order; each helper
    returns its bash lines. `fingerprint` = spec_hash of the theme as written (before build-time fallbacks)."""
    s = _header_lines(theme)
    s += _copy_lines(theme)
    s += _skippable("gtk", "GTK 4 / libadwaita apps", _gtk_lines(theme))
    s += _skippable("terminals", "terminals", _terminal_lines(theme))
    s += _skippable("browsers", "Firefox / Thunderbird", _mozilla_lines(theme))
    s += _skippable("vscode", "VS Code", _vscode_lines(theme))
    if theme.wallpaper:
        s += _skippable("wallpaper", "wallpaper", _wallpaper_lines(theme))
    s += _variant_lines(theme)
    s += _apply_lines(theme)
    s += _settings_lines(theme)
    s += _follow_lines(theme)
    if theme.login_screen.generate or theme.boot_splash.generate:
        s += _system_lines(theme, out)
    s += [
        'echo "==> reloading KWin"',
        "qdbus6 org.kde.KWin /KWin reconfigure || true",
        "# which version of the theme file this is (the app shows when the file has changed since)",
        'mkdir -p "${XDG_STATE_HOME:-$HOME/.local/state}/kde-customizer"',
        f'echo {fingerprint or spec_hash(theme)} > "${{XDG_STATE_HOME:-$HOME/.local/state}}/kde-customizer/'
        f'installed-{theme.slug}"',
        'echo "Done."',
        "",
    ]
    path = out / "install.sh"
    path.write_text("\n".join(s))
    path.chmod(0o755)
    rp = out / "restore-point.sh"
    rp.write_text(restore.script(theme))
    rp.chmod(0o755)


def _header_lines(theme: Theme) -> list[str]:
    """Shebang, usage, paths, option parsing (--layout, --no-…), then the restore point."""
    usage = [f"#   {flag:<15} leave alone {what}" for _, flag, what in SKIP_PARTS.values()]
    return [
        "#!/usr/bin/env bash",
        f"# Installs and applies the '{theme.name}' theme. Generated by kde-customizer.",
        "# Usage: ./install.sh [--layout] [--no-…]",
        "#   --layout          replace your panels with the theme's",
        *usage,
        "set -euo pipefail",
        'DIR="$(cd "$(dirname "$0")" && pwd)"',
        'DATA="${XDG_DATA_HOME:-$HOME/.local/share}"',
        'CONF="${XDG_CONFIG_HOME:-$HOME/.config}"',
        "LAYOUT=0; " + " ".join(f"{var}=1;" for var, _, _ in SKIP_PARTS.values()),
        'for a in "$@"; do',
        '  case "$a" in',
        "    --layout) LAYOUT=1 ;;",
        *[f"    {flag}) {var}=0 ;;" for var, flag, _ in SKIP_PARTS.values()],
        '    *) echo "unknown option: $a (ignored)" >&2 ;;',
        "  esac",
        "done",
        "",
        "# record the desktop as it is now; `kdec revert` (or the printed restore.sh) puts it back",
        'if (( LAYOUT )); then bash "$DIR/restore-point.sh" --layout || true; '
        'else bash "$DIR/restore-point.sh" || true; fi',
        "",
    ]


def _replace_dir(label: str, src: str, dest: str, name: str) -> list[str]:
    """Copy build folder $DIR/<src>/<name> to <dest>/<name>, replacing an older copy."""
    return [f'echo "==> {label}"', f'mkdir -p "{dest}"', f'rm -rf "{dest}/{name}"',
            f'cp -r "$DIR/{src}/{name}" "{dest}/"']


def _copy_lines(theme: Theme) -> list[str]:
    """Copy the generated parts into the user's folders (color scheme, Konsole, Plasma style, icons, cursors,
    Kvantum, title bars). Nothing is switched on yet."""
    q = shlex.quote
    s = ['echo "==> color scheme"', 'mkdir -p "$DATA/color-schemes"',
         'cp "$DIR"/color-schemes/*.colors "$DATA/color-schemes/"']
    if theme.konsole:
        s += ['echo "==> konsole"', 'mkdir -p "$DATA/konsole"', 'cp "$DIR"/konsole/* "$DATA/konsole/"']
    if theme.plasma.generate:
        name = theme.plasma_style_name
        s += _replace_dir("plasma style", "plasma", "$DATA/plasma/desktoptheme", name)
        s += ["# drop cached renders of the old version so new colors show up",
              f'rm -f "${{XDG_CACHE_HOME:-$HOME/.cache}}"/plasma_theme_{name}*.kcache '
              f'"${{XDG_CACHE_HOME:-$HOME/.cache}}"/plasma-svgelements-{name}*']
    if theme.iconset.generate:
        s += _replace_dir("icon theme", "icons", "$DATA/icons", theme.icons_name)
        s.append('rm -f "${XDG_CACHE_HOME:-$HOME/.cache}"/icon-cache.kcache')
    if theme.cursorset.generate:
        s += _replace_dir("cursor theme", "cursors", "$DATA/icons", theme.cursors_name)
    if theme.widgets.generate:
        name = theme.kvantum_name
        s += _replace_dir("app style (Kvantum)", "kvantum", "$CONF/Kvantum", name)
        s.append(f'kwriteconfig6 --file "$CONF/Kvantum/kvantum.kvconfig" --group General --key theme {q(name)}')
    if theme.decoration.generate:
        s += _replace_dir("window decoration", "aurorae", "$DATA/aurorae/themes", theme.decoration_name)
    return s


def _wallpaper_lines(theme: Theme) -> list[str]:
    """Install the wallpaper as a Plasma wallpaper package, ~/.local/share/wallpapers/<Slug>/ = metadata.json +
    contents/images/<W>x<H>.<ext>. The global theme names it ([Wallpaper] Image=<Slug>), so Plasma uses it for new
    desktops too; a plain image there isn't a package and Plasma fell back to Breeze's."""
    from . import previews
    src = Path(theme.wallpaper).name
    meta = json.dumps({"KPlugin": {"Id": theme.slug, "Name": theme.name,
                                   "Authors": [{"Name": theme.author or "Unknown"}],
                                   "Description": f"Wallpaper of the {theme.name} theme"},
                       "KPackageStructure": "Wallpaper/Images"})
    pkg = f'"$DATA/wallpapers/{theme.slug}"'
    return ['echo "==> wallpaper"',
            f'rm -rf {pkg}', f'mkdir -p {pkg}/contents/images',
            f'cp "$DIR/wallpapers/"{shlex.quote(src)} '
            f'{pkg}/contents/images/{previews.wallpaper_file_name(theme.wallpaper)}',
            f"printf '%s\\n' {shlex.quote(meta)} > {pkg}/metadata.json"]


def _apply_lines(theme: Theme) -> list[str]:
    """Install and apply the global theme, then make running apps pick up each part now (Kvantum only where it's
    installed; icons, cursors, Plasma style, wallpaper, Konsole profile)."""
    q = shlex.quote
    s = [
        'echo "==> global theme package"',
        f'kpackagetool6 -t Plasma/LookAndFeel -u "$DIR/lookandfeel/{theme.id}" 2>/dev/null \\',
        f'  || kpackagetool6 -t Plasma/LookAndFeel -i "$DIR/lookandfeel/{theme.id}"',
        'echo "==> applying"',
        'if (( LAYOUT )); then',
        f"  plasma-apply-lookandfeel -a {q(theme.id)} --resetLayout",
        "else",
        f"  plasma-apply-lookandfeel -a {q(theme.id)}",
        "fi",
        f"plasma-apply-colorscheme {q(theme.slug)} || true",
    ]
    if theme.widgets.generate and theme.light_dark.auto:
        s.append(f'echo "light/dark switching: apps use {theme.widget_style} (it follows the colors; '
                 "a Kvantum style can't switch with them)\"")
    elif theme.widgets.generate:
        # LnF set the fallback style; switch to Kvantum only where it's installed.
        s += [
            "if command -v kvantummanager >/dev/null 2>&1 \\",
            "   || ls /usr/lib/qt6/plugins/styles/libkvantum.so /usr/lib64/qt6/plugins/styles/libkvantum.so \\",
            "         /usr/lib/*/qt6/plugins/styles/libkvantum.so >/dev/null 2>&1; then",
            "  kwriteconfig6 --file kdeglobals --group KDE --key widgetStyle kvantum",
            "  # tell running KDE apps the style changed (KGlobalSettings::StyleChanged = 2)",
            "  dbus-send --session --type=signal /KGlobalSettings org.kde.KGlobalSettings.notifyChange "
            "int32:2 int32:0 || true",
            "else",
            f'  echo "Kvantum is not installed: apps keep the {theme.widget_style} style. '
            'Install kvantum and run this again."',
            "fi",
        ]
    if theme.iconset.generate:
        # Re-announce the icon theme so running apps reload it even when only its files changed.
        s += ["CHANGEICONS=\"$(ls /usr/lib/plasma-changeicons /usr/lib/*/plasma-changeicons "
              "/usr/libexec/plasma-changeicons 2>/dev/null | head -n1 || true)\"",
              f'if [[ -n "$CHANGEICONS" ]]; then "$CHANGEICONS" {q(theme.icons_name)} || true; fi']
    if theme.cursorset.generate:
        # LnF sets it only when the global theme changes; this also makes KWin reload it now
        s.append(f"plasma-apply-cursortheme {q(theme.cursors_name)} || true")
    if theme.plasma.generate:
        # LnF already sets plasmarc; this makes a running shell reload the style immediately.
        s.append(f"plasma-apply-desktoptheme {q(theme.plasma_style_name)} || true")
    if theme.wallpaper:
        # the package (not its image file): Plasma then picks the image size nearest each screen
        s += ["if (( WALLPAPER )); then", 'echo "==> wallpaper"',
              f'plasma-apply-wallpaperimage "$DATA/wallpapers/{theme.slug}"', "fi"]
    if theme.konsole:
        s.append(f"kwriteconfig6 --file konsolerc --group 'Desktop Entry' --key DefaultProfile "
                 f"{q(theme.slug + '.profile')}")
    return s


def _settings_lines(theme: Theme) -> list[str]:
    """Config keys Look-and-Feel can't set: "settings" from the spec (fonts, title bar buttons, splash,
    light/dark) are always written; the theme's own [tweaks] can be left out with --no-tweaks."""
    if not all_tweaks(theme):
        return []

    def writes(tweaks) -> list[str]:
        return [_kwrite(f, g, k, v) for f, groups in tweaks.items() for g, kv in groups.items() for k, v in kv.items()]
    s = ['echo "==> settings"', *writes(all_tweaks(replace(theme, tweaks={})))]
    own = writes(theme.tweaks)
    if own:
        s += _skippable("tweaks", "tweaks", ['echo "==> tweaks"', *own])
    return s


def _mozilla_lines(theme: Theme) -> list[str]:
    """Firefox/LibreWolf/Thunderbird profiles: our CSS imported from chrome/userChrome.css (+ the pref enabling it);
    an app switched off gets its import and file removed."""
    imp = shlex.quote(mozilla.IMPORT)
    s = [mozilla.PROFILES_FN]
    for app in ("firefox", "thunderbird"):
        roots = " ".join(f'"{r}"' for r in mozilla.ROOTS[app])
        s += ["while IFS= read -r P; do", '  UC="$P/chrome/userChrome.css"']
        if getattr(theme.apps, app):
            s += [
                f'  echo "==> {app}: ${{P##*/}} (restart it to see the colors)"',
                '  mkdir -p "$P/chrome"',
                f'  cp "$DIR/apps/{app}/{mozilla.FILE}" "$P/chrome/"',
                '  touch "$UC"',
                f'  if ! grep -qxF {imp} "$UC"; then',
                "    # @import must come before any rule: after the last existing @import, else first",
                f"    awk -v imp={imp} '{{ l[NR] = $0; if ($0 ~ /^[[:space:]]*@import/) last = NR }} "
                "END { if (!last) print imp; for (i = 1; i <= NR; i++) { print l[i]; if (i == last) print imp } }' "
                '"$UC" > "$UC.tmp"; cat "$UC.tmp" > "$UC"; rm -f "$UC.tmp"',
                "  fi",
                "  grep -qs 'legacyUserProfileCustomizations.stylesheets' \"$P/user.js\" || "
                f"echo {shlex.quote(mozilla.PREF + ' // kde-customizer')} >> \"$P/user.js\"",
            ]
        else:
            s += [f'  if [[ -f "$UC" ]] && grep -qxF {imp} "$UC"; then grep -vxF {imp} "$UC" > "$UC.tmp" || true; '
                  'cat "$UC.tmp" > "$UC"; rm -f "$UC.tmp"; fi',
                  f'  rm -f "$P/chrome/{mozilla.FILE}"']
        s += [f"done < <(moz_profiles {roots})"]
    return s


def _variant_lines(theme: Theme) -> list[str]:
    """[light_dark] auto: install the opposite variant's parts (not applied: Plasma switches to it by schedule)."""
    if not theme.light_dark.auto:
        return []
    from . import variant
    vt = variant.opposite(theme)
    v = f'"$DIR/variant/{vt.slug}"'
    s = [f'echo "==> light/dark variant: {vt.name}"',
         f'cp {v}/color-schemes/*.colors "$DATA/color-schemes/"']
    for on, kind, name, dest in [(vt.plasma.generate, "plasma", vt.plasma_style_name, "$DATA/plasma/desktoptheme"),
                                 (vt.iconset.generate, "icons", vt.icons_name, "$DATA/icons"),
                                 (vt.cursorset.generate, "cursors", vt.cursors_name, "$DATA/icons"),
                                 (vt.decoration.generate, "aurorae", vt.decoration_name, "$DATA/aurorae/themes")]:
        if on:
            s += [f'if [[ -d {v}/{kind}/{name} ]]; then mkdir -p "{dest}"; rm -rf "{dest}/{name}"; '
                  f'cp -r {v}/{kind}/{name} "{dest}/"; fi']
    if vt.plasma.generate:
        s.append(f'rm -f "${{XDG_CACHE_HOME:-$HOME/.cache}}"/plasma_theme_{vt.plasma_style_name}*.kcache')
    if vt.konsole:
        s += ['mkdir -p "$DATA/konsole"', f'cp {v}/konsole/* "$DATA/konsole/"']
    s += [f'kpackagetool6 -t Plasma/LookAndFeel -u {v}/lookandfeel/{vt.id} 2>/dev/null \\',
          f'  || kpackagetool6 -t Plasma/LookAndFeel -i {v}/lookandfeel/{vt.id}']
    return s


def _follow_lines(theme: Theme) -> list[str]:
    """[light_dark] auto: the kdec-follow user unit keeps GTK/terminal colors in step with Plasma's switch.
    Without it: Plasma's own switching is turned off (it would replace this theme at sunset) and the unit removed."""
    unit = lightdark.UNIT
    sysd = '"$CONF/systemd/user"'
    has_systemd = "command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1"
    if not theme.light_dark.auto:
        return [
            'if [[ "$(kreadconfig6 --file kdeglobals --group KDE --key AutomaticLookAndFeel)" == true ]]; then',
            '  echo "==> light/dark switching off (this theme has no light/dark pair)"',
            "  kwriteconfig6 --notify --file kdeglobals --group KDE --key AutomaticLookAndFeel false",
            "fi",
            f'if [[ -f {sysd}/{unit}.path ]]; then',
            f"  {{ {has_systemd}; }} && systemctl --user disable --now {unit}.path >/dev/null 2>&1 || true",
            f'  rm -f {sysd}/{unit}.path {sysd}/{unit}.service; rm -rf "$DATA/kde-customizer/follow"',
            "fi",
        ]
    from . import variant
    vt = variant.opposite(theme)
    s = ['echo "==> light/dark: GTK and terminal colors follow the switch"',
         'F="$DATA/kde-customizer/follow"', 'mkdir -p "$F"',
         'cp "$DIR/follow/follow.sh" "$F/"']
    for t, src in [(theme, '"$DIR"'), (vt, f'"$DIR/variant/{vt.slug}"')]:
        d = f'"$F/{t.id}"'
        s += [f"rm -rf {d}; mkdir -p {d}"]
        # a part skipped this time (--no-gtk…) gets no follow file, so the switch leaves it alone too
        if t.gtk.generate:
            s.append(f"if (( GTK )); then cp {src}/gtk/{gtk.FILE} {d}/; fi")
        if t.apps.kitty:
            s.append(f"if (( TERMINALS )); then cp {src}/apps/kitty/{t.slug}.conf {d}/kitty.conf; fi")
        if t.apps.alacritty:
            s.append(f"if (( TERMINALS )); then cp {src}/apps/alacritty/kde-customizer.toml {d}/alacritty.toml; fi")
        if t.apps.ghostty:
            s += [f"if (( TERMINALS )); then echo {shlex.quote(t.slug)} > {d}/ghostty; fi",
                  f'if (( TERMINALS )) && [[ -d "$CONF/ghostty" ]]; then mkdir -p "$CONF/ghostty/themes"; '
                  f'cp {src}/apps/ghostty/{t.slug} "$CONF/ghostty/themes/"; fi']
        if t.konsole:
            s.append(f"echo {shlex.quote(t.slug + '.profile')} > {d}/konsole")
        for app in ("firefox", "thunderbird"):
            if getattr(t.apps, app):
                s.append(f"if (( BROWSERS )); then cp {src}/apps/{app}/{mozilla.FILE} {d}/{app}.css; fi")
    s += [
        f"if {has_systemd}; then",
        f"  mkdir -p {sysd}",
        f'  for u in {unit}.path {unit}.service; do',
        '    sed -e "s#@CONF@#$CONF#g" -e "s#@DATA@#$DATA#g" "$DIR/follow/$u" > ' + sysd + '/"$u"',
        "  done",
        "  systemctl --user daemon-reload",
        f"  systemctl --user enable --now {unit}.path >/dev/null 2>&1 || echo \"  could not enable {unit}.path\"",
        "else",
        '  echo "  no systemd user session: GTK/terminal colors stay as installed when Plasma switches"',
        "fi",
    ]
    return s


def system_payload(theme: Theme) -> dict[str, list[str]]:
    """Login screen / boot splash: the build folders each one's root script copies (relative to the build)."""
    out: dict[str, list[str]] = {}
    if theme.login_screen.generate:
        login = ["login"]
        if theme.plasma.generate:
            login.append(f"plasma/{theme.plasma_style_name}")
        if theme.iconset.generate:
            login.append(f"icons/{theme.icons_name}")
        if theme.cursorset.generate:
            login.append(f"cursors/{theme.cursors_name}")
        if loginscreen.wallpaper_name(theme):
            login.append("wallpapers")
        out["login"] = login
    if theme.boot_splash.generate:
        out["boot"] = ["boot"]
    return out


def tree_hash(out: Path, rels: list[str]) -> str:
    """sha256 over every file below these build paths (names + contents), in a fixed order."""
    import hashlib
    import os
    root = str(out)
    files: list[str] = []
    for r in rels:                       # os.walk + strings: cursor/icon trees have hundreds of files
        top = os.path.join(root, r)
        if os.path.isfile(top):
            files.append(r)
        for d, _dirs, names in os.walk(top):
            rel_d = os.path.relpath(d, root)
            files += [os.path.join(rel_d, n) for n in names if os.path.isfile(os.path.join(d, n))]
    h = hashlib.sha256()
    for rel in sorted(files):
        with open(os.path.join(root, rel), "rb") as f:
            h.update(rel.encode() + b"\0" + hashlib.file_digest(f, "sha256").digest())
    return h.hexdigest()


def system_stamps(theme: Theme, out: Path) -> dict[str, str]:
    """{"login"|"boot": hash of what would be installed} for a built theme."""
    return {key: tree_hash(out, rels) for key, rels in system_payload(theme).items()}


def spec_hash(theme: Theme) -> str:
    """Fingerprint of a theme as written in its spec, plus the files it uses (wallpaper, icon folders: names, sizes,
    times). install.sh records it, so the GUI can tell when a theme file has changed since it was installed."""
    import copy
    import hashlib
    import tomllib
    from .spec import dumps, fix_id, from_dict
    t = copy.deepcopy(theme)
    fix_id(t)
    files: list[Path] = []
    for obj, attr in ((t, "wallpaper"), (t.iconset, "signature_dir"), (t.iconset, "custom_dir")):
        val = getattr(obj, attr)
        if val:
            p = Path(val).expanduser().resolve()
            setattr(obj, attr, str(p))
            files += [p] if p.is_file() else sorted(f for f in p.rglob("*") if f.is_file()) if p.is_dir() else []
    h = hashlib.sha256(dumps(from_dict(tomllib.loads(dumps(t)))).encode())
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        h.update(f"{f}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


def state_dir() -> Path:
    import os
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "kde-customizer"


def installed_stamp(theme: Theme, key: str) -> str:
    """The hash install.sh recorded the last time this part was installed ("" = never)."""
    try:
        return (state_dir() / f"{key}-{theme.slug}").read_text().strip()
    except OSError:
        return ""


def unchanged_system_parts(theme: Theme, out: Path) -> set[str]:
    """Login/boot parts whose files are the same as last time: install.sh skips them (no password prompt)."""
    return {k for k, v in system_stamps(theme, out).items() if v == installed_stamp(theme, k)}


def _system_lines(theme: Theme, out: Path) -> list[str]:
    """Login screen + boot splash: one pkexec run for whichever changed since last time (hash stamps)."""
    sums = system_stamps(theme, out)

    def part(key: str, label: str, flag: str, skip_flag: str, available: str, missing: str):
        """Bash for one system-wide part: skipped / not available / already up to date (same hash as last time) /
        queued for the single pkexec run."""
        return [
            f'echo "==> {label}"',
            f"if (( ! {flag} )); then",
            f'  echo "skipped ({skip_flag})"',
            f"elif ! {{ {available}; }}; then      # grouped: `! a || b` would negate only a",
            f'  echo "{missing}"',
            "else",
            f'  SUM={sums[key]}      # hash of its files (build.tree_hash)',
            f'  if [[ -f "$STATE/{key}-{theme.slug}" && "$(cat "$STATE/{key}-{theme.slug}")" == "$SUM" ]]; then',
            '    echo "already up to date"',
            "  else",
            f'    PARTS+=({key}); SUMS+=("$SUM")',
            "  fi",
            "fi",
        ]

    s = ['STATE="${XDG_STATE_HOME:-$HOME/.local/state}/kde-customizer"', "PARTS=(); SUMS=()"]
    if theme.login_screen.generate:
        s += part("login", "login screen", "LOGIN", "--no-login",
                  "getent passwd plasmalogin >/dev/null || getent passwd sddm >/dev/null",
                  "Neither Plasma Login Manager nor SDDM is installed: login screen left as is")
    if theme.boot_splash.generate:
        s += part("boot", "boot splash", "BOOT", "--no-boot", "command -v plymouth-set-default-theme >/dev/null",
                  "Plymouth is not installed: boot splash left as is")
    s += [
        "if (( ${#PARTS[@]} )); then",
        '  echo "==> asking for the admin password (${PARTS[*]})"',
        "  # one prompt for every part that changed; each part's apply.sh runs as root",
        """  if pkexec bash -c 'set -e; d="$1"; shift; for p in "$@"; do bash "$d/$p/apply.sh" "$d"; done' """
        'kdec "$DIR" "${PARTS[@]}"; then',
        '    mkdir -p "$STATE"',
        '    for i in "${!PARTS[@]}"; do echo "${SUMS[$i]}" > "$STATE/${PARTS[$i]}-' + theme.slug + '"; done',
        "  else",
        '    echo "not updated: ${PARTS[*]} (needs the admin password; run ./install.sh again to retry)"',
        "  fi",
        "fi",
    ]
    return s



def _gtk_lines(theme: Theme) -> list[str]:
    """GTK 4 / libadwaita: our CSS imported from gtk-4.0/gtk.css — or, when off, our import removed again."""
    imp = shlex.quote(gtk.IMPORT)
    lines = [
        'echo "==> GTK 4 / libadwaita apps"',
        'G="$CONF/gtk-4.0/gtk.css"',
    ]
    if not theme.gtk.generate:
        return lines + [
            "# not part of this theme: undo a previous kde-customizer theme's colors",
            f'if [[ -f "$G" ]] && grep -qxF {imp} "$G"; then grep -vxF {imp} "$G" > "$G.tmp" || true; '
            'cat "$G.tmp" > "$G"; rm -f "$G.tmp"; fi',
            f'rm -f "$CONF/gtk-4.0/{gtk.FILE}"',
        ]
    lines += [
        'mkdir -p "$CONF/gtk-4.0"',
        f'cp "$DIR/gtk/{gtk.FILE}" "$CONF/gtk-4.0/"',
        'touch "$G"',
        f'if ! grep -qxF {imp} "$G"; then',
        "  # after the last @import (imports must come first; KDE's own colors.css import stays ahead of ours)",
        f"  awk -v imp={imp} '{{ l[NR] = $0; if ($0 ~ /^[[:space:]]*@import/) last = NR }} "
        "END { if (!last) print imp; for (i = 1; i <= NR; i++) { print l[i]; if (i == last) print imp } }' "
        '"$G" > "$G.tmp"',
        '  cat "$G.tmp" > "$G"; rm -f "$G.tmp"      # keeps gtk.css itself (it may be a symlink)',
        "fi",
    ]
    if theme.gtk.flatpak:
        lines += ["# Flatpak apps only see ~/.config/gtk-4.0 with this (read-only) permission",
                  "command -v flatpak >/dev/null 2>&1 && "
                  "flatpak override --user --filesystem=xdg-config/gtk-4.0:ro || true"]
    return lines


ALACRITTY_IMPORT = '"~/.config/alacritty/kde-customizer.toml"'


def _block(file: str, body: str) -> list[str]:
    """(Re)write our marked block at the end of a config file (later lines win in kitty/Ghostty)."""
    return [
        f'touch {file}',
        f"sed -i '/^# BEGIN_KDEC_THEME/,/^# END_KDEC_THEME/d' {file}",
        f"printf '\\n# BEGIN_KDEC_THEME (kde-customizer; delete this block to undo)\\n{body}\\n# END_KDEC_THEME\\n'"
        f" >> {file}",
    ]


def _unblock(file: str) -> str:
    return f"[[ -f {file} ]] && sed -i '/^# BEGIN_KDEC_THEME/,/^# END_KDEC_THEME/d' {file} || true"


def _terminal_lines(theme: Theme) -> list[str]:
    """kitty, Alacritty, WezTerm, Ghostty — only where installed; an app switched off is undone."""
    a, slug = theme.apps, theme.slug
    imp = ALACRITTY_IMPORT
    s: list[str] = []

    # kitty: theme file + include at the end of kitty.conf
    s += ['if command -v kitty >/dev/null 2>&1 || [[ -d "$CONF/kitty" ]]; then']
    if a.kitty:
        s += ['  echo "==> kitty"',
              '  mkdir -p "$CONF/kitty/themes"',
              f'  cp "$DIR/apps/kitty/{slug}.conf" "$CONF/kitty/themes/"',
              f'  cp "$DIR/apps/kitty/{slug}.conf" "$CONF/kitty/kde-customizer-theme.conf"']
        s += ["  " + x for x in _block('"$CONF/kitty/kitty.conf"', "include kde-customizer-theme.conf")]
    else:
        s += ["  " + _unblock('"$CONF/kitty/kitty.conf"'), '  rm -f "$CONF/kitty/kde-customizer-theme.conf"']
    s += ["fi"]

    # Ghostty: themes/<Slug> + `theme = <Slug>` at the end of its config
    s += ['if command -v ghostty >/dev/null 2>&1 || [[ -d "$CONF/ghostty" ]]; then',
          '  GC="$CONF/ghostty/config"; [[ -f "$CONF/ghostty/config.ghostty" ]] && GC="$CONF/ghostty/config.ghostty"']
    if a.ghostty:
        s += ['  echo "==> Ghostty"', '  mkdir -p "$CONF/ghostty/themes"',
              f'  cp "$DIR/apps/ghostty/{slug}" "$CONF/ghostty/themes/"']
        s += ["  " + x for x in _block('"$GC"', f"theme = {slug}")]
    else:
        s += ["  " + _unblock('"$GC"')]
    s += ["fi"]

    # WezTerm: the color scheme only (its config is Lua)
    if a.wezterm:
        s += ['if command -v wezterm >/dev/null 2>&1 || [[ -d "$CONF/wezterm" ]]; then',
              '  echo "==> WezTerm"', '  mkdir -p "$CONF/wezterm/colors"',
              f'  cp "$DIR/apps/wezterm/{slug}.toml" "$CONF/wezterm/colors/"',
              f"  echo \"  select it in wezterm.lua: config.color_scheme = '{theme.name}'\"",
              "fi"]

    # Alacritty: the importing file overrides imports, so its own [colors.*] tables are commented out (marked)
    A = '"$CONF/alacritty/alacritty.toml"'
    s += ['if command -v alacritty >/dev/null 2>&1 || [[ -d "$CONF/alacritty" ]]; then']
    if a.alacritty:
        s += [
            '  echo "==> Alacritty"',
            '  mkdir -p "$CONF/alacritty"',
            '  cp "$DIR/apps/alacritty/kde-customizer.toml" "$CONF/alacritty/"',
            f"  IMP={shlex.quote(imp)}",
            f"  if [[ ! -s {A} ]]; then",
            f'    printf "[general]\\nimport = [%s]\\n" "$IMP" > {A}',
            "  else",
            f'    [[ -f {A}.kdec-backup ]] || cp {A} {A}.kdec-backup',
            "    # comment out [colors.*] / [[colors.*]] tables (ours replace them); [colors] itself stays",
            "    awk '/^[[:space:]]*\\[/ { c = ($0 ~ /^[[:space:]]*\\[\\[?colors\\./) } "
            "c && !/^#kdec# / { $0 = \"#kdec# \" $0 } { print }' " + A + f" > {A}.tmp",
            f'    cat {A}.tmp > {A}; rm -f {A}.tmp',
            f'    if grep -qF "kde-customizer.toml" {A}; then :',
            f"    elif grep -qE '^[[:space:]]*import[[:space:]]*=[[:space:]]*\\[' {A}; then",
            "      # add ours first in the existing array (later imports and the file itself override it)",
            f"      sed -i -E \"0,/^[[:space:]]*import[[:space:]]*=[[:space:]]*\\[/s##import = [$IMP, #\" {A}",
            f"    elif grep -qE '^[[:space:]]*\\[general\\]' {A}; then",
            "      awk -v imp=\"$IMP\" '{ print } !d && /^[[:space:]]*\\[general\\][[:space:]]*$/ "
            "{ print \"import = [\" imp \"]\"; d = 1 }' " + A + f" > {A}.tmp",
            f'      cat {A}.tmp > {A}; rm -f {A}.tmp',
            "    else",
            "      # a [general] table before the first table (top-level keys must stay above any table)",
            "      awk -v imp=\"$IMP\" '!d && /^[[:space:]]*\\[/ "
            "{ print \"[general]\\nimport = [\" imp \"]\\n\"; d = 1 } "
            "{ print } END { if (!d) print \"\\n[general]\\nimport = [\" imp \"]\" }' " + A + f" > {A}.tmp",
            f'      cat {A}.tmp > {A}; rm -f {A}.tmp',
            "    fi",
            "  fi",
        ]
    else:
        s += [
            f"  if [[ -f {A} ]]; then",
            f"    sed -i -E -e 's/^#kdec# //' -e 's#\"~/\\.config/alacritty/kde-customizer\\.toml\",? ?##' "
            f"-e '/^import = \\[\\]$/d' {A}",
            "  fi",
            '  rm -f "$CONF/alacritty/kde-customizer.toml"',
        ]
    s += ["fi"]
    return s


def _vscode_lines(theme: Theme) -> list[str]:
    """VS Code family: install the extension; the theme is picked in Color Theme (settings.json is left alone)."""
    s: list[str] = []
    if theme.apps.vscode:
        s += ['for C in code codium code-oss; do',
              '  if command -v "$C" >/dev/null 2>&1; then',
              '    echo "==> $C"',
              f'    "$C" --install-extension "$DIR/apps/vscode/{apps.vscode_id(theme)}.vsix" '
              '--force >/dev/null 2>&1 \\',
              f'      && echo "  installed: pick \\"{theme.name}\\" in Preferences > Color Theme" '
              '|| echo "  could not install the extension"',
              "  fi",
              "done"]
    return s
