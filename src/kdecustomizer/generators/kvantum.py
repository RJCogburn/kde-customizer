"""Kvantum app style — goes to ~/.config/Kvantum/<Slug>/<Slug>.{kvconfig,svg}.

A Kvantum theme is a kvconfig (one section per widget: which SVG element it uses, frame thickness, text
colors) plus one SVG holding every element. Framed elements come as nine pieces per state —
`<el>-<state>` (interior, stretched) and `<el>-<state>-top|…|bottomright` (frame, scaled to the
kvconfig's `frame.top|bottom|left|right`). States: normal, focused (= hover), pressed, toggled (checked /
selected), disabled. A state whose element is present but empty draws nothing — that's how flat tool
buttons and menu items stay transparent until hovered. Indicators (arrows, check boxes, radio buttons)
are single elements scaled to `indicator.size`.

Every color comes from `colors.scheme()`, so Kvantum apps match the KDE color scheme exactly.
"""
from __future__ import annotations

from ..color import RGB, darken, mix, parse, shift, to_hex
from ..spec import Theme
from . import colors as color_scheme
from .plasmastyle import _corner_d, _n, _path, _rect, _Svg

STATES = ("normal", "focused", "pressed", "toggled", "disabled")
TILE = 16
GHOST = 'fill="#000000" fill-opacity="0"'
Paint = tuple[RGB, float] | None    # color + alpha, or nothing


def _scheme(theme: Theme) -> dict[str, dict[str, RGB]]:
    return {sec: {k: parse(v) if isinstance(v, str) else v for k, v in roles.items()}
            for sec, roles in color_scheme.scheme(theme).items()}


def _fill(p: Paint) -> str:
    c, a = p  # type: ignore[misc]
    return f'fill="{to_hex(c)}"' + (f' fill-opacity="{_n(a)}"' if a < 1 else "")


class _Sheet:
    """Places elements on the SVG canvas row by row."""

    def __init__(self) -> None:
        self.svg = _Svg()
        self.x = 0.0
        self.y = 0.0
        self.row_h = 0.0
        self.width = 0.0

    def place(self, w: float, h: float) -> tuple[float, float]:
        if self.x + w > 1200:
            self.x, self.y, self.row_h = 0.0, self.y + self.row_h + 4, 0.0
        pos = (self.x, self.y)
        self.x += w + 4
        self.row_h = max(self.row_h, h)
        self.width = max(self.width, self.x)
        return pos

    def frame(self, name: str, looks: dict[str, tuple[Paint, Paint]], F: float, radius: float) -> None:
        """Nine-piece element per state; looks[state] = (fill, border)."""
        r = min(radius, F)
        for state in STATES:
            fill, border = looks.get(state, looks["normal"])
            size = 2 * F + TILE
            x, y = self.place(size, size)
            self.svg.el(f"{name}-{state}", _rect(x + F, y + F, TILE, TILE, GHOST),
                        *([_rect(x + F, y + F, TILE, TILE, _fill(fill))] if fill else []))
            regions = {
                "topleft": (x, y, F, F), "top": (x + F, y, TILE, F), "topright": (x + F + TILE, y, F, F),
                "left": (x, y + F, F, TILE), "right": (x + F + TILE, y + F, F, TILE),
                "bottomleft": (x, y + F + TILE, F, F), "bottom": (x + F, y + F + TILE, TILE, F),
                "bottomright": (x + F + TILE, y + F + TILE, F, F),
            }
            for piece, (px, py, pw, ph) in regions.items():
                shapes = [_rect(px, py, pw, ph, GHOST)]
                if piece in ("topleft", "topright", "bottomleft", "bottomright"):
                    if fill:
                        shapes.append(_path(_corner_d(px, py, F, r, piece), _fill(fill)))
                    if border:
                        ring = _corner_d(px, py, F, r, piece) + " " + _corner_d(px, py, F, r, piece, inset=1)
                        shapes.append(_path(ring, _fill(border) + ' fill-rule="evenodd"'))
                else:
                    if fill:
                        shapes.append(_rect(px, py, pw, ph, _fill(fill)))
                    if border:
                        band = {"top": (px, py, pw, 1), "bottom": (px, py + ph - 1, pw, 1),
                                "left": (px, py, 1, ph), "right": (px + pw - 1, py, 1, ph)}[piece]
                        shapes.append(_rect(*band, _fill(border)))
                self.svg.el(f"{name}-{state}-{piece}", *shapes)

    def icon(self, name: str, draw: dict[str, str], size: float = 16) -> None:
        """Single-element indicator per state; draw[state] = SVG for a size x size box at the origin."""
        for state in STATES:
            body = draw.get(state, draw["normal"])
            x, y = self.place(size, size)
            self.svg.el(f"{name}-{state}", _rect(x, y, size, size, GHOST),
                        f'<g transform="translate({_n(x)},{_n(y)})">{body}</g>')


def _stroke(c: RGB, a: float = 1.0, w: float = 1.6) -> str:
    return (f'fill="none" stroke="{to_hex(c)}" stroke-opacity="{_n(a)}" stroke-width="{_n(w)}" '
            'stroke-linecap="round" stroke-linejoin="round"')


_CHEVRON = {"down": "M4.5,6.5 L8,10 L11.5,6.5", "up": "M4.5,9.5 L8,6 L11.5,9.5",
            "right": "M6.5,4.5 L10,8 L6.5,11.5", "left": "M9.5,4.5 L6,8 L9.5,11.5"}


def svg(theme: Theme) -> str:
    """The Kvantum SVG: per widget element an interior and nine frame pieces for each state, plus arrows, check boxes,
    radios and slider handles."""
    s = _scheme(theme)
    dark = theme.dark
    win, btn, view = s["Colors:Window"], s["Colors:Button"], s["Colors:View"]
    sel, tip = s["Colors:Selection"], s["Colors:Tooltip"]
    fg, bg = win["ForegroundNormal"], win["BackgroundNormal"]
    acc, on_acc = sel["BackgroundNormal"], sel["ForegroundNormal"]
    line = mix(fg, bg, 0.82)          # quiet border
    strong = mix(fg, bg, 0.6)         # check box / radio outline
    R = theme.widgets.radius
    F = max(R, 2)
    sh = _Sheet()
    P = lambda c, a=1.0: (c, a)  # noqa: E731

    b = btn["BackgroundNormal"]
    sh.frame("button", {
        "normal": (P(b), P(line)),
        "focused": (P(shift(b, 0.05, dark)), P(acc)),
        "pressed": (P(mix(b, acc, 0.3)), P(acc)),
        "toggled": (P(mix(b, acc, 0.22)), P(acc)),
        "disabled": (P(b, 0.5), P(line, 0.5)),
    }, F, R)
    sh.frame("tbutton", {
        "normal": (None, None),
        "focused": (P(fg, 0.08), None),
        "pressed": (P(acc, 0.35), None),
        "toggled": (P(acc, 0.22), P(acc, 0.6)),
        "disabled": (None, None),
    }, F, R)
    v = view["BackgroundNormal"]
    sh.frame("lineedit", {
        "normal": (P(v), P(line)),
        "focused": (P(v), P(acc)),
        "pressed": (P(v), P(acc)),
        "toggled": (P(v), P(acc)),
        "disabled": (P(v, 0.5), P(line, 0.5)),
    }, F, R)
    sh.frame("common", {"normal": (None, P(line)), "disabled": (None, P(line, 0.5))}, F, R)
    sh.frame("group", {"normal": (P(fg, 0.03), P(line))}, F, R)
    page = shift(bg, 0.03, dark)
    sh.frame("tab", {
        "normal": (None, None),
        "focused": (P(fg, 0.07), None),
        "pressed": (P(fg, 0.1), None),
        "toggled": (P(page), P(line)),
        "disabled": (None, None),
    }, F, R)
    sh.frame("tabframe", {"normal": (P(page), P(line))}, F, R)
    sh.frame("menu", {"normal": (P(bg), P(line))}, F, R)
    sh.frame("menuitem", {
        "normal": (None, None), "focused": (P(acc), None), "pressed": (P(acc), None),
        "toggled": (None, None), "disabled": (None, None),
    }, F, R)
    sh.frame("menubaritem", {
        "normal": (None, None), "focused": (P(fg, 0.08), None), "pressed": (P(acc), None),
        "toggled": (P(acc), None), "disabled": (None, None),
    }, F, R)
    sh.frame("itemview", {
        "normal": (None, None), "focused": (P(acc, 0.22), None), "pressed": (P(acc), None),
        "toggled": (P(acc), None), "disabled": (None, None),
    }, F, R)
    sh.frame("progress", {"normal": (P(fg, 0.12), None)}, 3, 3)
    sh.frame("progress-pattern", {"normal": (P(acc), None)}, 3, 3)
    sh.frame("slider", {"normal": (P(fg, 0.18), None), "toggled": (P(acc), None),
                        "disabled": (P(fg, 0.08), None)}, 3, 3)
    sh.frame("scrollbargroove", {"normal": (None, None)}, 4, 4)
    sh.frame("scrollbarslider", {
        "normal": (P(fg, 0.32), None), "focused": (P(fg, 0.5), None), "pressed": (P(acc), None),
        "toggled": (P(acc), None), "disabled": (P(fg, 0.15), None),
    }, 4, 4)
    sh.frame("tooltip", {"normal": (P(tip["BackgroundNormal"]), P(line))}, F, R)

    # --- indicators (16 x 16) ---
    box_r = min(R, 5)

    def box(fill: Paint, border: Paint, round_: bool) -> str:
        style = (_fill(fill) if fill else 'fill="none"') + (
            f' stroke="{to_hex(border[0])}" stroke-opacity="{_n(border[1])}" stroke-width="1"' if border else "")
        if round_:
            return f'<circle cx="8" cy="8" r="7" {style}/>'
        return f'<rect x="1.5" y="1.5" width="13" height="13" rx="{_n(box_r)}" {style}/>'

    for kind, round_ in (("checkbox", False), ("radio", True)):
        off = {
            "normal": box(P(v), P(strong), round_), "focused": box(P(v), P(acc), round_),
            "pressed": box(P(acc, 0.25), P(acc), round_), "toggled": box(P(v), P(strong), round_),
            "disabled": box(P(v, 0.5), P(strong, 0.4), round_),
        }
        sh.icon(kind, off)
        mark = (f'<circle cx="8" cy="8" r="3" {_fill(P(on_acc))}/>' if round_
                else f'<path d="M4.5,8.3 L7,10.8 L11.5,5.5" {_stroke(on_acc, 1, 2)}/>')
        on = {
            "normal": box(P(acc), P(acc), round_) + mark,
            "focused": box(P(shift(acc, 0.08, dark)), P(acc), round_) + mark,
            "pressed": box(P(mix(acc, (0, 0, 0), 0.2)), P(acc), round_) + mark,
            "toggled": box(P(acc), P(acc), round_) + mark,
            "disabled": box(P(acc, 0.4), P(acc, 0.4), round_) + mark,
        }
        sh.icon(f"{kind}-checked", on)
        if kind == "checkbox":
            dash = f'<path d="M4.5,8 H11.5" {_stroke(on_acc, 1, 2)}/>'
            sh.icon("checkbox-tristate", {k: val.replace(mark, dash) for k, val in on.items()})

    for direction, d in _CHEVRON.items():
        sh.icon(f"arrow-{direction}", {"normal": f'<path d="{d}" {_stroke(fg)}/>',
                                       "disabled": f'<path d="{d}" {_stroke(fg, 0.35)}/>'})
        if direction in ("left", "right"):    # sub-menu arrows (on the highlight when hovered)
            sh.icon(f"menuitem-{direction}", {"normal": f'<path d="{d}" {_stroke(fg)}/>',
                                              "focused": f'<path d="{d}" {_stroke(on_acc)}/>',
                                              "pressed": f'<path d="{d}" {_stroke(on_acc)}/>',
                                              "disabled": f'<path d="{d}" {_stroke(fg, 0.35)}/>'})
    sh.icon("arrow-plus", {"normal": f'<path d="M4.5,8 H11.5 M8,4.5 V11.5" {_stroke(fg)}/>',
                           "disabled": f'<path d="M4.5,8 H11.5 M8,4.5 V11.5" {_stroke(fg, 0.35)}/>'})
    sh.icon("arrow-minus", {"normal": f'<path d="M4.5,8 H11.5" {_stroke(fg)}/>',
                            "disabled": f'<path d="M4.5,8 H11.5" {_stroke(fg, 0.35)}/>'})
    # The default push button is drawn like a toggled one (normal_default_pushbutton=false);
    # an empty indicator keeps Kvantum from adding its corner triangle.
    x, y = sh.place(8, 8)
    sh.svg.el("button-default-indicator", _rect(x, y, 8, 8, GHOST))
    knob = btn["BackgroundNormal"]
    sh.icon("slidercursor", {
        "normal": f'<circle cx="8" cy="8" r="6.5" {_fill(P(knob))} stroke="{to_hex(acc)}" stroke-width="1.5"/>',
        "focused": f'<circle cx="8" cy="8" r="6.5" {_fill(P(shift(knob, 0.08, dark)))} '
                   f'stroke="{to_hex(acc)}" stroke-width="2"/>',
        "pressed": f'<circle cx="8" cy="8" r="6.5" {_fill(P(acc))} stroke="{to_hex(acc)}" stroke-width="2"/>',
        "disabled": f'<circle cx="8" cy="8" r="6.5" {_fill(P(knob, 0.5))} '
                    f'stroke="{to_hex(strong)}" stroke-opacity="0.5" stroke-width="1.5"/>',
    })
    return sh.svg.render(sh.width, sh.y + sh.row_h + 4)


def kvconfig(theme: Theme) -> str:
    """The .kvconfig: one section per widget (which SVG elements, frame thickness, text colors) plus the general
    hints."""
    s = _scheme(theme)
    win, btn, view, sel, tip = (s[k] for k in ("Colors:Window", "Colors:Button", "Colors:View",
                                               "Colors:Selection", "Colors:Tooltip"))
    h = to_hex
    fg, bg = win["ForegroundNormal"], win["BackgroundNormal"]
    acc, on_acc = sel["BackgroundNormal"], sel["ForegroundNormal"]
    F = max(theme.widgets.radius, 2)
    t = lambda c: {f"text.{k}.color": h(c) for k in ("normal", "focus", "press", "toggle")}  # noqa: E731
    frame = lambda n: {"frame.top": n, "frame.bottom": n, "frame.left": n, "frame.right": n}  # noqa: E731
    sections: dict[str, dict[str, object]] = {
        "%General": {
            "author": theme.author or "kde-customizer",
            "comment": f"{theme.name} — generated by kde-customizer",
            "x11drag": "menubar_and_primary_toolbar", "alt_mnemonic": "true",
            "left_tabs": "false", "attach_active_tab": "false", "group_toolbar_buttons": "false",
            "spread_progressbar": "true", "progressbar_thickness": 6,
            "composite": "true", "translucent_windows": "false", "blurring": "false",
            "menu_shadow_depth": 0, "tooltip_shadow_depth": 0, "spread_menuitems": "true",
            "splitter_width": 5, "scroll_width": 10, "scroll_min_extent": 40, "scroll_arrows": "false",
            "transient_scrollbar": "true", "transient_groove": "true",
            "combo_as_lineedit": "true", "inline_spin_indicators": "true",
            "slider_width": 4, "slider_handle_width": 16, "slider_handle_length": 16,
            "check_size": 16, "toolbar_icon_size": "font", "animate_states": "true",
            "button_contents_shift": "false", "respect_DE": "true", "no_inactiveness": "false",
        },
        "GeneralColors": {
            "window.color": h(bg), "base.color": h(view["BackgroundNormal"]),
            "alt.base.color": h(view["BackgroundAlternate"]), "button.color": h(btn["BackgroundNormal"]),
            "light.color": h(shift(btn["BackgroundNormal"], 0.12, theme.dark)),
            "mid.light.color": h(shift(btn["BackgroundNormal"], 0.06, theme.dark)),
            "dark.color": h(darken(bg, 0.5)), "mid.color": h(darken(bg, 0.2)),
            "highlight.color": h(acc), "inactive.highlight.color": h(mix(acc, bg, 0.35)),
            "text.color": h(view["ForegroundNormal"]), "window.text.color": h(fg),
            "button.text.color": h(btn["ForegroundNormal"]), "disabled.text.color": h(win["ForegroundInactive"]),
            "tooltip.base.color": h(tip["BackgroundNormal"]), "tooltip.text.color": h(tip["ForegroundNormal"]),
            "highlight.text.color": h(on_acc), "link.color": h(win["ForegroundLink"]),
            "link.visited.color": h(win["ForegroundVisited"]), "progress.indicator.text.color": h(fg),
        },
        "Hacks": {"respect_darkness": "true", "transparent_ktitle_label": "true",
                  "transparent_dolphin_view": "false", "blur_konsole": "false", "iconless_pushbutton": "false",
                  "normal_default_pushbutton": "false", "tint_on_mouseover": 0},
        "PanelButtonCommand": {
            "frame": "true", "frame.element": "button", "interior": "true", "interior.element": "button",
            **frame(F), "indicator.size": 10, "indicator.element": "arrow", **t(btn["ForegroundNormal"]),
            "text.shadow": 0, "text.margin": 1, "text.iconspacing": 4,
            "text.margin.top": 2, "text.margin.bottom": 2, "text.margin.left": 4, "text.margin.right": 4,
            "min_width": "+0.3font", "min_height": "+0.3font",
        },
        "PanelButtonTool": {"inherits": "PanelButtonCommand", "frame.element": "tbutton",
                            "interior.element": "tbutton"},
        "ToolbarButton": {"inherits": "PanelButtonTool"},
        "Dock": {"inherits": "PanelButtonCommand", "frame": "false", "interior": "false"},
        "DockTitle": {"inherits": "PanelButtonCommand", "frame": "false", "interior": "false",
                      "text.bold": "true"},
        "IndicatorSpinBox": {"inherits": "PanelButtonCommand", "frame": "false", "interior": "false",
                             "indicator.element": "arrow", "indicator.size": 10},
        "RadioButton": {"inherits": "PanelButtonCommand", "frame": "false", "interior.element": "radio",
                        **t(fg)},
        "CheckBox": {"inherits": "PanelButtonCommand", "frame": "false", "interior.element": "checkbox",
                     **t(fg)},
        "GenericFrame": {"inherits": "PanelButtonCommand", "frame": "true", "interior": "false",
                         "frame.element": "common", "interior.element": "common", **frame(F), **t(fg)},
        "LineEdit": {"inherits": "PanelButtonCommand", "frame.element": "lineedit",
                     "interior.element": "lineedit", **t(view["ForegroundNormal"]),
                     "text.margin.left": 4, "text.margin.right": 4},
        "DropDownButton": {"inherits": "PanelButtonCommand", "indicator.element": "arrow-down"},
        "IndicatorArrow": {"indicator.element": "arrow", "indicator.size": 10},
        "ToolboxTab": {"inherits": "PanelButtonCommand"},
        "Tab": {"inherits": "PanelButtonCommand", "frame.element": "tab", "interior.element": "tab",
                "indicator.element": "tab", **t(fg), **frame(F),
                "text.margin.left": 8, "text.margin.right": 8, "text.margin.top": 4, "text.margin.bottom": 4,
                "min_height": "+0.6font"},
        "TabFrame": {"inherits": "PanelButtonCommand", "frame.element": "tabframe", "interior": "false",
                     **frame(F)},
        "TreeExpander": {"inherits": "PanelButtonCommand", "frame": "false", "interior": "false",
                         "indicator.size": 10},
        "HeaderSection": {"inherits": "PanelButtonCommand", "frame.element": "tbutton",
                          "interior.element": "tbutton", **frame(2), **t(fg)},
        "SizeGrip": {"inherits": "PanelButtonCommand", "frame": "false", "interior": "false",
                     "indicator.element": "resize-grip"},
        "Toolbar": {"inherits": "PanelButtonCommand", "frame": "false", "interior": "false",
                    "indicator.element": "toolbar", **t(fg), "text.margin": 0},
        "Slider": {"inherits": "PanelButtonCommand", "frame.element": "slider", "interior.element": "slider",
                   **frame(3)},
        "SliderCursor": {"inherits": "PanelButtonCommand", "frame": "false", "interior.element": "slidercursor"},
        "Progressbar": {"inherits": "PanelButtonCommand", "frame.element": "progress",
                        "interior.element": "progress", **frame(3), **t(fg), "text.margin": 0},
        "ProgressbarContents": {"inherits": "PanelButtonCommand", "frame": "true",
                                "frame.element": "progress-pattern", "interior.element": "progress-pattern",
                                **frame(3)},
        "ItemView": {"inherits": "PanelButtonCommand", "frame.element": "itemview",
                     "interior.element": "itemview", **frame(min(F, 3)),
                     "text.normal.color": h(view["ForegroundNormal"]), "text.focus.color": h(view["ForegroundNormal"]),
                     "text.press.color": h(on_acc), "text.toggle.color": h(on_acc),
                     "text.margin.top": 2, "text.margin.bottom": 2, "text.margin.left": 4, "text.margin.right": 4},
        "Splitter": {"inherits": "PanelButtonCommand", "frame": "false", "interior": "false",
                     "indicator.element": "splitter-grip"},
        "Scrollbar": {"inherits": "PanelButtonCommand", "frame": "false", "interior": "false",
                      "indicator.size": 10},
        "ScrollbarGroove": {"inherits": "PanelButtonCommand", "frame.element": "scrollbargroove",
                            "interior.element": "scrollbargroove", **frame(4)},
        "ScrollbarSlider": {"inherits": "PanelButtonCommand", "frame.element": "scrollbarslider",
                            "interior.element": "scrollbarslider", **frame(4), "indicator.element": "grip"},
        "ScrollbarTransientSlider": {"inherits": "ScrollbarSlider"},
        "MenuItem": {"inherits": "PanelButtonCommand", "frame.element": "menuitem",
                     "interior.element": "menuitem", "indicator.element": "menuitem", **frame(min(F, 3)),
                     "text.normal.color": h(fg), "text.focus.color": h(on_acc), "text.press.color": h(on_acc),
                     "text.toggle.color": h(fg),
                     "text.margin.top": 3, "text.margin.bottom": 3, "text.margin.left": 6, "text.margin.right": 6},
        "MenuBar": {"inherits": "PanelButtonCommand", "frame": "false", "interior": "false"},
        "MenuBarItem": {"inherits": "PanelButtonCommand", "frame.element": "menubaritem",
                        "interior.element": "menubaritem", **frame(min(F, 3)),
                        "text.normal.color": h(fg), "text.focus.color": h(fg), "text.press.color": h(on_acc),
                        "text.toggle.color": h(on_acc), "text.margin.left": 6, "text.margin.right": 6},
        "TitleBar": {"inherits": "PanelButtonCommand", "frame": "false", "interior": "false",
                     **t(fg), "text.bold": "true"},
        "ComboBox": {"inherits": "PanelButtonCommand"},
        "Menu": {"inherits": "PanelButtonCommand", "frame.element": "menu", "interior.element": "menu",
                 **frame(F), **t(fg), "frame.expansion": 0},
        "GroupBox": {"inherits": "GenericFrame", "frame": "true", "frame.element": "group", **frame(F),
                     "text.margin": 0},
        "TabBarFrame": {"inherits": "GenericFrame", "frame": "false", "interior": "false"},
        "ToolTip": {"inherits": "GenericFrame", "frame.element": "tooltip", "interior": "true",
                    "interior.element": "tooltip", **frame(F), **t(tip["ForegroundNormal"]), "text.margin": 2},
        "StatusBar": {"inherits": "GenericFrame", "frame": "false", "interior": "false"},
        "Window": {"interior": "false", "frame": "false"},
        "Focus": {"frame": "false"},
    }
    out: list[str] = []
    for name, kv in sections.items():
        out.append(f"[{name}]")
        out += [f"{k}={v}" for k, v in kv.items()]
        out.append("")
    return "\n".join(out)


def files(theme: Theme) -> dict[str, str]:
    name = theme.kvantum_name
    return {f"{name}.kvconfig": kvconfig(theme), f"{name}.svg": svg(theme)}
