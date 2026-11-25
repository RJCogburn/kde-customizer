"""Firefox (and LibreWolf) and Thunderbird in the palette: `<profile>/chrome/kde-customizer.css`, imported from the
profile's userChrome.css (which needs `toolkit.legacyUserProfileCustomizations.stylesheets`, set in user.js).

The browser chrome is drawn from CSS custom properties; ours are `!important` on :root so they also beat an
active add-on theme (Firefox sets those inline on the root element). Colors come from colors.scheme(), the same
roles the KDE color scheme uses. Firefox needs a restart to load userChrome.css.
"""
from __future__ import annotations

from ..color import RGB, mix, shift, to_hex
from ..spec import Theme
from . import colors as colors_gen
from .gtk import _on, _readable

FILE = "kde-customizer.css"
IMPORT = f'@import "{FILE}";'
PREF = 'user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);'

# app -> profile roots (each holds profiles.ini) relative to $HOME, or $CONF/...
ROOTS = {
    "firefox": ["$HOME/.mozilla/firefox", "$CONF/mozilla/firefox",
                "$HOME/.var/app/org.mozilla.firefox/.mozilla/firefox",
                "$HOME/.var/app/org.mozilla.firefox/config/mozilla/firefox",
                "$HOME/.librewolf", "$HOME/.var/app/io.gitlab.librewolf-community/.librewolf"],
    "thunderbird": ["$HOME/.thunderbird", "$CONF/thunderbird",
                    "$HOME/.var/app/org.mozilla.Thunderbird/.thunderbird"],
}

# bash: profiles listed in ROOT/profiles.ini (relative or absolute Path=), one per line
PROFILES_FN = r"""moz_profiles() {
  local root p
  for root in "$@"; do
    [[ -f "$root/profiles.ini" ]] || continue
    grep -E '^Path=' "$root/profiles.ini" | cut -d= -f2- | while IFS= read -r p; do
      [[ "$p" == /* ]] || p="$root/$p"
      [[ -d "$p" ]] && printf '%s\n' "$p"
    done
  done
}"""


def _hex(c: RGB | str) -> str:
    return c if isinstance(c, str) else to_hex(c)


def colors(theme: Theme) -> dict[str, str]:
    s = colors_gen.scheme(theme)
    p = theme.palette.resolved()
    dark = theme.dark
    win, view, head, sel, btn = (s["Colors:Window"], s["Colors:View"], s["Colors:Header"],
                                 s["Colors:Selection"], s["Colors:Button"])
    frame = head["BackgroundNormal"]
    toolbar = win["BackgroundNormal"]
    field = view["BackgroundNormal"]
    fg = win["ForegroundNormal"]
    return {
        "frame": _hex(frame), "frame-fg": _hex(head["ForegroundNormal"]),
        "frame-inactive": _hex(shift(frame, 0.03, not dark)),
        "toolbar": _hex(toolbar), "toolbar-fg": _hex(fg),
        "tab-selected": _hex(toolbar), "tab-selected-fg": _hex(fg),
        "field": _hex(field), "field-fg": _hex(view["ForegroundNormal"]),
        "field-border": _hex(mix(field, fg, 0.18)),
        "field-focus": _hex(shift(field, 0.03, dark)),
        "accent": _hex(sel["BackgroundNormal"]), "accent-fg": _hex(sel["ForegroundNormal"]),
        "accent-text": _readable(p.accent, field, dark),
        "hover": _hex(mix(toolbar, fg, 0.10)), "active": _hex(mix(toolbar, fg, 0.18)),
        "panel": _hex(view["BackgroundNormal"]), "panel-fg": _hex(view["ForegroundNormal"]),
        "panel-border": _hex(mix(view["BackgroundNormal"], fg, 0.15)),
        "sidebar": _hex(p.surface), "sidebar-fg": _hex(fg),
        "separator": _hex(mix(toolbar, fg, 0.12)),
        "button": _hex(btn["BackgroundNormal"]), "button-fg": _hex(btn["ForegroundNormal"]),
        "on-accent": _on(sel["BackgroundNormal"]),
        "attention": _readable(p.neutral, toolbar, dark),
    }


def firefox_css(theme: Theme) -> str:
    c = colors(theme)
    v = {
        # window frame / tab strip
        "--lwt-accent-color": c["frame"], "--lwt-accent-color-inactive": c["frame-inactive"],
        "--lwt-text-color": c["frame-fg"], "--toolbox-bgcolor": c["frame"],
        "--toolbox-bgcolor-inactive": c["frame-inactive"], "--toolbox-textcolor": c["frame-fg"],
        "--toolbox-textcolor-inactive": c["frame-fg"], "--tabs-navbar-separator-color": c["separator"],
        # toolbars + selected tab
        "--toolbar-bgcolor": c["toolbar"], "--toolbar-color": c["toolbar-fg"],
        "--tab-selected-bgcolor": c["tab-selected"], "--tab-selected-textcolor": c["tab-selected-fg"],
        "--lwt-selected-tab-background-color": c["tab-selected"],
        "--tab-loading-fill": c["accent"], "--tab-attention-icon-color": c["attention"],
        "--toolbarbutton-hover-background": c["hover"], "--toolbarbutton-active-background": c["active"],
        "--chrome-content-separator-color": c["separator"],
        # address bar
        "--toolbar-field-background-color": c["field"], "--toolbar-field-color": c["field-fg"],
        "--toolbar-field-border-color": c["field-border"],
        "--toolbar-field-focus-background-color": c["field-focus"], "--toolbar-field-focus-color": c["field-fg"],
        "--toolbar-field-focus-border-color": c["accent"],
        "--urlbarView-highlight-background": c["accent"], "--urlbarView-highlight-color": c["accent-fg"],
        "--urlbarView-action-color": c["accent-text"],
        # menus, panels, sidebar, accents
        "--arrowpanel-background": c["panel"], "--arrowpanel-color": c["panel-fg"],
        "--arrowpanel-border-color": c["panel-border"],
        "--panel-separator-color": c["panel-border"],
        "--sidebar-background-color": c["sidebar"], "--sidebar-text-color": c["sidebar-fg"],
        "--sidebar-border-color": c["separator"],
        "--focus-outline-color": c["accent"], "--color-accent-primary": c["accent"],
        "--color-accent-primary-hover": c["accent"], "--color-accent-primary-active": c["accent"],
        "--button-primary-bgcolor": c["accent"], "--button-primary-color": c["on-accent"],
        "--button-background-color-primary": c["accent"], "--button-text-color-primary": c["on-accent"],
        "--button-bgcolor": c["button"], "--button-color": c["button-fg"],
        "--checkbox-checked-bgcolor": c["accent"],
        # the names Firefox ~140+ uses (design-system tokens); the ones above are for older versions / forks
        "--toolbox-background-color": c["frame"], "--toolbox-background-color-inactive": c["frame-inactive"],
        "--toolbox-text-color": c["frame-fg"], "--toolbox-text-color-inactive": c["frame-fg"],
        "--toolbar-background-color": c["toolbar"], "--toolbar-text-color": c["toolbar-fg"],
        "--toolbar-field-background-color-focus": c["field-focus"],
        "--toolbar-field-text-color": c["field-fg"], "--toolbar-field-text-color-focus": c["field-fg"],
        "--tab-background-color-selected": c["tab-selected"], "--tab-text-color-selected": c["tab-selected-fg"],
        "--tab-background-color-hover": c["hover"],
        "--tabpanel-background-color": c["field"],
        "--toolbarbutton-background-color-hover": c["hover"], "--toolbarbutton-background-color-active": c["active"],
        "--panel-background-color": c["panel"], "--panel-text-color": c["panel-fg"],
        "--panel-border-color": c["panel-border"],
        "--urlbarview-background-color-selected": c["accent"], "--urlbarview-text-color-selected": c["accent-fg"],
        "--urlbarview-text-color-action": c["accent-text"],
        "--button-background-color-primary-hover": c["accent"], "--button-background-color-primary-active": c["accent"],
        "--button-text-color-primary-hover": c["on-accent"], "--button-text-color-primary-active": c["on-accent"],
        "--sidebar-divider-color": c["separator"],
    }
    body = "\n".join(f"  {k}: {val} !important;" for k, val in v.items())
    return (f"/* {theme.name} — generated by kde-customizer; imported from userChrome.css */\n"
            f":root {{\n{body}\n}}\n"
            "/* menus drawn by Firefox itself (context menus, the hamburger menu's sub-views) */\n"
            "menupopup, panel { --panel-background: var(--arrowpanel-background) !important;\n"
            "  --panel-color: var(--arrowpanel-color) !important; }\n"
            "#urlbar-background { border-color: var(--toolbar-field-border-color) !important; }\n"
            "::selection { background-color: var(--color-accent-primary); color: var(--button-primary-color); }\n")


def thunderbird_css(theme: Theme) -> str:
    c = colors(theme)
    v = {
        "--layout-background-0": c["toolbar"], "--layout-background-1": c["sidebar"],
        "--layout-background-2": c["frame"], "--layout-background-3": c["hover"],
        "--layout-background-4": c["active"], "--layout-color-0": c["toolbar-fg"],
        "--layout-color-1": c["toolbar-fg"], "--layout-color-2": c["toolbar-fg"],
        "--layout-color-3": c["separator"], "--layout-border-0": c["separator"],
        "--layout-border-1": c["panel-border"], "--layout-border-2": c["panel-border"],
        "--lwt-accent-color": c["frame"], "--lwt-text-color": c["frame-fg"],
        "--toolbar-bgcolor": c["toolbar"], "--toolbar-color": c["toolbar-fg"],
        "--tabs-toolbar-background-color": c["frame"], "--tab-selected-bgcolor": c["tab-selected"],
        "--tab-selected-textcolor": c["tab-selected-fg"],
        "--toolbar-field-background-color": c["field"], "--toolbar-field-color": c["field-fg"],
        "--toolbar-field-border-color": c["field-border"],
        "--toolbar-field-focus-border-color": c["accent"],
        "--sidebar-background": c["sidebar"], "--sidebar-text-color": c["sidebar-fg"],
        "--foldertree-background": c["sidebar"], "--tree-view-bg": c["field"], "--tree-view-color": c["field-fg"],
        "--tree-card-background": c["field"],
        "--selected-item-color": c["accent"], "--selected-item-text-color": c["accent-fg"],
        "--arrowpanel-background": c["panel"], "--arrowpanel-color": c["panel-fg"],
        "--arrowpanel-border-color": c["panel-border"],
        "--focus-outline-color": c["accent"], "--color-accent-primary": c["accent"],
        "--button-primary-background-color": c["accent"], "--button-primary-text-color": c["on-accent"],
    }
    body = "\n".join(f"  {k}: {val} !important;" for k, val in v.items())
    return (f"/* {theme.name} — generated by kde-customizer; imported from userChrome.css */\n"
            f":root {{\n{body}\n}}\n")


def files(theme: Theme) -> dict[str, str]:
    out = {}
    if theme.apps.firefox:
        out["firefox/" + FILE] = firefox_css(theme)
    if theme.apps.thunderbird:
        out["thunderbird/" + FILE] = thunderbird_css(theme)
    return out
