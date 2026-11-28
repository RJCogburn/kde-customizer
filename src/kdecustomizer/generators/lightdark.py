"""`[light_dark] auto`: Plasma switches between the theme's light and dark Look-and-Feel packages by time of day
(kdeglobals [KDE] AutomaticLookAndFeel / DefaultLightLookAndFeel / DefaultDarkLookAndFeel, Night Light schedule).

Look-and-Feel only covers colors, icons, cursors, Plasma style, window decoration and splash, so a user systemd
path unit (kdec-follow.path, watching kdeglobals) runs follow.sh, which puts the matching variant's GTK 4,
kitty, Ghostty, Alacritty and Konsole colors in place. Per-variant files: $DATA/kde-customizer/follow/<LnF id>/.
"""
from __future__ import annotations

UNIT = "kdec-follow"

FOLLOW_SH = r"""#!/usr/bin/env bash
# kde-customizer: after Plasma switched between a theme's light and dark Look-and-Feel, switch the colors of
# GTK 4 apps and terminals too. Run by kdec-follow.service whenever kdeglobals changes.
set -u
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
F="$(cd "$(dirname "$0")" && pwd)"
ID="$(kreadconfig6 --file kdeglobals --group KDE --key LookAndFeelPackage)"
V="$F/$ID"
[[ -n "$ID" && -d "$V" ]] || exit 0

put() {  # put SRC DEST: copy when DEST exists (the app is set up for it) and differs; true when copied
  # (no cmp: diffutils may be missing)
  [[ -f "$1" && -f "$2" ]] && [[ "$(cat "$1")" != "$(cat "$2")" ]] && cat "$1" > "$2"
}
put "$V/kde-customizer.css" "$CONF/gtk-4.0/kde-customizer.css" || true
if put "$V/kitty.conf" "$CONF/kitty/kde-customizer-theme.conf"; then
  pkill -USR1 -x kitty 2>/dev/null || true          # kitty reloads its config on SIGUSR1
fi
put "$V/alacritty.toml" "$CONF/alacritty/kde-customizer.toml" || true   # Alacritty reloads by itself
if [[ -f "$V/ghostty" ]]; then
  for GC in "$CONF/ghostty/config" "$CONF/ghostty/config.ghostty"; do
    [[ -f "$GC" ]] && sed -i "/^# BEGIN_KDEC_THEME/,/^# END_KDEC_THEME/s/^theme = .*/theme = $(cat "$V/ghostty")/" "$GC"
  done
fi
if [[ -f "$V/konsole" ]]; then
  P="$(cat "$V/konsole")"
  [[ "$(kreadconfig6 --file konsolerc --group 'Desktop Entry' --key DefaultProfile)" == "$P" ]] \
    || kwriteconfig6 --file konsolerc --group 'Desktop Entry' --key DefaultProfile "$P"
fi
"""


def follow_script() -> str:
    """FOLLOW_SH + Firefox/Thunderbird profiles (they read the CSS at startup: the next start has the variant)."""
    from . import mozilla
    lines = [FOLLOW_SH.rstrip("\n"), mozilla.PROFILES_FN]
    for app in ("firefox", "thunderbird"):
        roots = " ".join(f'"{r}"' for r in mozilla.ROOTS[app])
        lines += [f"while IFS= read -r P; do put \"$V/{app}.css\" \"$P/chrome/{mozilla.FILE}\" || true; "
                  f"done < <(moz_profiles {roots})"]
    return "\n".join(lines) + "\n"


def path_unit(watch: str) -> str:
    """systemd .path unit that fires when `watch` (kdeglobals) changes."""
    return "\n".join([
        "[Unit]",
        "Description=kde-customizer: follow Plasma's light/dark switch in GTK apps and terminals",
        "",
        "[Path]",
        f"PathChanged={watch}",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ])


def service_unit(script: str) -> str:
    """systemd service the .path unit starts: runs follow.sh once."""
    return "\n".join([
        "[Unit]",
        "Description=kde-customizer: follow Plasma's light/dark switch in GTK apps and terminals",
        "",
        "[Service]",
        "Type=oneshot",
        f'ExecStart=/usr/bin/env bash "{script}"',
        "",
    ])
