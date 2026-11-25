"""Turn a Theme into a self-contained build directory with its own install.sh."""
from __future__ import annotations

import shlex
import shutil
import sys
import tarfile
from dataclasses import replace
from pathlib import Path

from . import cursorset, iconset
from .generators import aurorae, colors, konsole, kvantum, layout, lookandfeel, loginscreen, plasmastyle, splash
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
    return f"kwriteconfig6 --file {shlex.quote(file)} {groups} --key {shlex.quote(key)} {shlex.quote(v)}"


def build(theme: Theme, out_root: str | Path = "build") -> Path:
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

    if theme.cursorset.generate:
        cursorset.build(theme, out / "cursors")

    # Ship the editable spec too, with the wallpaper / signature icons pointing at the bundled copies.
    portable = replace(original, wallpaper=f"wallpapers/{Path(theme.wallpaper).name}" if theme.wallpaper else "")
    if (out / "signature-icons").is_dir():
        portable.iconset = replace(original.iconset, signature_dir="signature-icons")
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

    if theme.konsole:
        (out / "konsole").mkdir()
        (out / "konsole" / f"{theme.slug}.colorscheme").write_text(konsole.colorscheme(theme))
        (out / "konsole" / f"{theme.slug}.profile").write_text(konsole.profile(theme))

    _write_install_script(theme, out)
    return out


def export(theme: Theme, dest: str | Path | None = None, build_root: str | Path = "build") -> Path:
    """Build, then pack into <Slug>.tar.gz. Recipient: extract, run ./install.sh."""
    out = build(theme, build_root)
    dest = Path(dest) if dest else Path.cwd() / f"{theme.slug}.tar.gz"
    with tarfile.open(dest, "w:gz") as tar:
        tar.add(out, arcname=theme.slug)
    return dest


def _write_install_script(theme: Theme, out: Path) -> None:
    tweaks = all_tweaks(theme)
    q = shlex.quote
    s = [
        "#!/usr/bin/env bash",
        f"# Installs and applies the '{theme.name}' theme. Generated by kde-customizer.",
        "# Usage: ./install.sh [--layout] [--no-login]",
        "#   --layout     replace your panels with the theme's",
        "#   --no-login   leave the login screen alone (it needs the admin password)",
        "set -euo pipefail",
        'DIR="$(cd "$(dirname "$0")" && pwd)"',
        'DATA="${XDG_DATA_HOME:-$HOME/.local/share}"',
        'LAYOUT=0; LOGIN=1',
        'for a in "$@"; do case "$a" in --layout) LAYOUT=1 ;; --no-login) LOGIN=0 ;; esac; done',
        "",
        'echo "==> color scheme"',
        'mkdir -p "$DATA/color-schemes"',
        'cp "$DIR"/color-schemes/*.colors "$DATA/color-schemes/"',
    ]
    if theme.konsole:
        s += ['echo "==> konsole"', 'mkdir -p "$DATA/konsole"', 'cp "$DIR"/konsole/* "$DATA/konsole/"']
    if theme.plasma.generate:
        name = theme.plasma_style_name
        s += [
            'echo "==> plasma style"',
            'mkdir -p "$DATA/plasma/desktoptheme"',
            f'rm -rf "$DATA/plasma/desktoptheme/{name}"',
            f'cp -r "$DIR/plasma/{name}" "$DATA/plasma/desktoptheme/"',
            "# drop cached renders of the old version so new colors show up",
            f'rm -f "${{XDG_CACHE_HOME:-$HOME/.cache}}"/plasma_theme_{name}*.kcache '
            f'"${{XDG_CACHE_HOME:-$HOME/.cache}}"/plasma-svgelements-{name}*',
        ]
    if theme.iconset.generate:
        name = theme.icons_name
        s += [
            'echo "==> icon theme"',
            'mkdir -p "$DATA/icons"',
            f'rm -rf "$DATA/icons/{name}"',
            f'cp -r "$DIR/icons/{name}" "$DATA/icons/"',
            'rm -f "${XDG_CACHE_HOME:-$HOME/.cache}"/icon-cache.kcache',
        ]
    if theme.cursorset.generate:
        name = theme.cursors_name
        s += [
            'echo "==> cursor theme"',
            'mkdir -p "$DATA/icons"',
            f'rm -rf "$DATA/icons/{name}"',
            f'cp -r "$DIR/cursors/{name}" "$DATA/icons/"',
        ]
    if theme.widgets.generate:
        name = theme.kvantum_name
        s += [
            'echo "==> app style (Kvantum)"',
            'CONF="${XDG_CONFIG_HOME:-$HOME/.config}"',
            'mkdir -p "$CONF/Kvantum"',
            f'rm -rf "$CONF/Kvantum/{name}"',
            f'cp -r "$DIR/kvantum/{name}" "$CONF/Kvantum/"',
            f'kwriteconfig6 --file "$CONF/Kvantum/kvantum.kvconfig" --group General --key theme {q(name)}',
        ]
    if theme.decoration.generate:
        name = theme.decoration_name
        s += [
            'echo "==> window decoration"',
            'mkdir -p "$DATA/aurorae/themes"',
            f'rm -rf "$DATA/aurorae/themes/{name}"',
            f'cp -r "$DIR/aurorae/{name}" "$DATA/aurorae/themes/"',
        ]
    if theme.wallpaper:
        s += ['echo "==> wallpaper"', f'mkdir -p "$DATA/wallpapers/{theme.slug}"',
              f'cp "$DIR"/wallpapers/* "$DATA/wallpapers/{theme.slug}/"']
    s += [
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
    if theme.widgets.generate:
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
        wp = f"$DATA/wallpapers/{theme.slug}/{Path(theme.wallpaper).name}"
        s += ['echo "==> wallpaper"', f'plasma-apply-wallpaperimage "{wp}"']
    if theme.konsole:
        s.append(f"kwriteconfig6 --file konsolerc --group 'Desktop Entry' --key DefaultProfile {q(theme.slug + '.profile')}")
    if tweaks:
        s.append('echo "==> tweaks"')
        for f, groups in tweaks.items():
            for g, kv in groups.items():
                for k, v in kv.items():
                    s.append(_kwrite(f, g, k, v))
    if theme.login_screen.generate:
        s += _login_lines(theme)
    s += [
        'echo "==> reloading KWin"',
        "qdbus6 org.kde.KWin /KWin reconfigure || true",
        'echo "Done."',
        "",
    ]
    path = out / "install.sh"
    path.write_text("\n".join(s))
    path.chmod(0o755)


def _login_lines(theme: Theme) -> list[str]:
    """Login screen: one pkexec run of login/apply.sh, skipped when nothing changed since the last one."""
    payload = ['"$DIR/login"']
    if theme.plasma.generate:
        payload.append(f'"$DIR/plasma/{theme.plasma_style_name}"')
    if theme.iconset.generate:
        payload.append(f'"$DIR/icons/{theme.icons_name}"')
    if theme.cursorset.generate:
        payload.append(f'"$DIR/cursors/{theme.cursors_name}"')
    if loginscreen.wallpaper_name(theme):
        payload.append('"$DIR/wallpapers"')
    return [
        'echo "==> login screen"',
        "if (( ! LOGIN )); then",
        '  echo "skipped (--no-login)"',
        f"elif ! getent passwd {loginscreen.GREETER_USER} >/dev/null; then",
        '  echo "Plasma Login Manager is not installed: login screen left as is"',
        "else",
        '  STATE="${XDG_STATE_HOME:-$HOME/.local/state}/kde-customizer"',
        f'  STAMP="$STATE/login-{theme.slug}"',
        f"  SUM=\"$(find {' '.join(payload)} -type f -print0 | sort -z | xargs -0 sha256sum "
        '| sed "s#  $DIR/#  #" | sha256sum | cut -d" " -f1)"',
        '  if [[ -f "$STAMP" && "$(cat "$STAMP")" == "$SUM" ]]; then',
        '    echo "already up to date"',
        '  elif pkexec bash "$DIR/login/apply.sh" "$DIR"; then',
        '    mkdir -p "$STATE"; echo "$SUM" > "$STAMP"',
        "  else",
        '    echo "login screen not updated (needs the admin password; run ./install.sh again to retry)"',
        "  fi",
        "fi",
    ]
