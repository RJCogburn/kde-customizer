"""Aurorae window decoration — goes to ~/.local/share/aurorae/themes/<Slug>-Decoration/.

An Aurorae theme is a folder of SVGs plus an `<name>rc` with sizes and title colors:

* `decoration.svg` — a KSvg FrameSvg with prefixes `decoration-*` (focused window) and
  `decoration-inactive-*`. The frame covers the whole decoration item: window shadow ("padding",
  outside the window) + title bar + borders. The client window is painted over the middle, so the
  pieces may reach under it — only their bounding sizes matter to FrameSvg, and the middle row/column
  is stretched, so everything there must be constant along the stretch direction.
* one SVG per button (`close.svg`, `maximize.svg`, …) with a `<state>-center` element per state:
  active, hover, pressed (also "toggled", e.g. keep-above on), inactive, deactivated.

Colors come from `colors.scheme()["WM"]` (the same title bar colors the color scheme gives Breeze),
written as plain hex — Aurorae SVGs are not recolored by the color scheme.
"""
from __future__ import annotations

import json

from ..color import RGB, luminance, mix, parse, shift, to_hex
from ..spec import Theme
from . import colors as color_scheme
from .plasmastyle import _FALLOFF, _corner_d, _n, _path, _rect, _Svg

TILE = 32
SHADOW = 20          # padding around the window that holds the shadow
SHADOW_ALPHA = {"decoration": 0.34, "decoration-inactive": 0.2}

# button svg file -> glyph name
BUTTONS = {
    "close": "close", "minimize": "minimize", "maximize": "maximize", "restore": "restore",
    "alldesktops": "pin", "keepabove": "above", "keepbelow": "below", "shade": "shade", "help": "help",
}


def _wm(theme: Theme) -> dict[str, RGB]:
    """Title bar colors from the color scheme, as RGB tuples."""
    return {k: parse(v) if isinstance(v, str) else v for k, v in color_scheme.scheme(theme)["WM"].items()}


def _rgba(c: RGB, a: float = 1.0) -> str:
    return f'fill="{to_hex(c)}"' + (f' fill-opacity="{_n(a)}"' if a < 1 else "")


def _kde_rgba(c: RGB, a: int = 255) -> str:
    return f"{c[0]},{c[1]},{c[2]},{a}"


class _Geo:
    """Sizes of the decoration frame, in px."""

    def __init__(self, theme: Theme):
        d = theme.decoration
        self.r = d.radius
        self.b = d.border
        self.th = d.title_height
        self.rb = self.r if self.b >= self.r else 0        # round bottom corners only if the border fits them
        self.S = SHADOW
        side = max(self.r, self.b, 1)
        self.lw = self.S + side                            # left/right piece width
        self.top_h = self.S + self.th                      # top piece height (shadow + whole title bar)
        self.bot_h = self.S + max(self.b, self.rb, 1)
        self.W = 2 * self.lw + TILE
        self.H = self.top_h + TILE + self.bot_h
        dots = d.button_style == "dots"
        self.box = min(self.th - 10, 18) if dots else self.th - 6   # button size
        self.spacing = 8 if dots else 2
        self.edge = (max(8, self.r // 2 + 6) if dots else max(4, self.r // 2 + 2))


def _pieces(g: _Geo, oy: float) -> dict[str, tuple[float, float, float, float]]:
    xs = [0, g.lw, g.lw + TILE, g.W]
    ys = [oy, oy + g.top_h, oy + g.top_h + TILE, oy + g.H]
    names = [["topleft", "top", "topright"], ["left", "center", "right"], ["bottomleft", "bottom", "bottomright"]]
    return {names[j][i]: (xs[i], ys[j], xs[i + 1] - xs[i], ys[j + 1] - ys[j]) for j in range(3) for i in range(3)}


def _clip(rect, region):
    x, y, w, h = rect
    rx, ry, rw, rh = region
    x0, y0 = max(x, rx), max(y, ry)
    x1, y1 = min(x + w, rx + rw), min(y + h, ry + rh)
    return (x0, y0, x1 - x0, y1 - y0) if x1 > x0 and y1 > y0 else None


def _frame(svg: _Svg, g: _Geo, prefix: str, oy: float, fill: RGB, edge: RGB, edge_a: float) -> None:
    S, W, H = g.S, g.W, g.H
    x0, x1, y0, y1 = S, W - S, oy + S, oy + H - S
    r, rb = g.r, g.rb
    a = SHADOW_ALPHA[prefix]
    stops = lambda start: [(start + (1 - start) * o, a * f) for o, f in _FALLOFF]  # noqa: E731

    def lin(ax: float, ay: float, bx: float, by: float) -> str:
        attrs = f'x1="{_n(ax)}" y1="{_n(ay)}" x2="{_n(bx)}" y2="{_n(by)}"'
        return f'fill="{svg.gradient("linear", attrs, stops(0))}"'

    rects: list[tuple[tuple[float, float, float, float], str]] = [
        # shadow bands: (x, y, w, h), style — gradient runs from the frame edge outwards
        ((x0 + r, oy, x1 - x0 - 2 * r, S), lin(0, y0, 0, oy)),
        ((x0 + rb, y1, x1 - x0 - 2 * rb, S), lin(0, y1, 0, y1 + S)),
        ((0, y0 + r, S, y1 - y0 - r - rb), lin(x0, 0, 0, 0)),
        ((x1, y0 + r, S, y1 - y0 - r - rb), lin(x1, 0, W, 0)),
        # frame fill
        ((x0 + r, y0, x1 - x0 - 2 * r, r), _rgba(fill)),
        ((x0, y0 + r, x1 - x0, y1 - y0 - r - rb), _rgba(fill)),
        ((x0 + rb, y1 - rb, x1 - x0 - 2 * rb, rb), _rgba(fill)),
        # 1px edge
        ((x0 + r, y0, x1 - x0 - 2 * r, 1), _rgba(edge, edge_a)),
        ((x0, y0 + r, 1, y1 - y0 - r - rb), _rgba(edge, edge_a)),
        ((x1 - 1, y0 + r, 1, y1 - y0 - r - rb), _rgba(edge, edge_a)),
        ((x0 + rb, y1 - 1, x1 - x0 - 2 * rb, 1), _rgba(edge, edge_a)),
    ]
    corners = {"topleft": (x0, y0, r), "topright": (x1, y0, r), "bottomleft": (x0, y1, rb), "bottomright": (x1, y1, rb)}
    ghost = 'fill="#000000" fill-opacity="0.004"'
    for name, region in _pieces(g, oy).items():
        shapes = [_rect(*region, ghost)]
        for rect, style in rects:
            c = _clip(rect, region)
            if c and c[2] > 0.001 and c[3] > 0.001:
                shapes.append(_rect(*c, style))
        if name in corners:
            px, py, k = corners[name]
            right, bottom = name.endswith("right"), name.startswith("bottom")
            fx = px - k if right else px            # top-left of the k x k rounded square
            fy = py - k if bottom else py
            cx, cy = (px - k if right else px + k), (py - k if bottom else py + k)
            qx, qy = (fx if right else px - S), (fy if bottom else py - S)
            q = S + k
            grad = svg.gradient("radial", f'cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(k + S)}"',
                                [(0, 0), (k / (k + S), 0)] + stops(k / (k + S)))
            outer = f"M{_n(qx)},{_n(qy)} h{_n(q)} v{_n(q)} h{_n(-q)} Z"
            inner = _corner_d(fx, fy, k, k, name) if k else ""
            shapes.append(_path(f"{outer} {inner}", f'fill="{grad}" fill-rule="evenodd"'))
            if k:
                shapes.append(_path(inner, _rgba(fill)))
                ring = inner + " " + _corner_d(fx, fy, k, k, name, inset=1)
                shapes.append(_path(ring, _rgba(edge, edge_a) + ' fill-rule="evenodd"'))
        svg.el(f"{prefix}-{name}", *shapes)


def decoration_svg(theme: Theme) -> str:
    g = _Geo(theme)
    wm = _wm(theme)
    dark = theme.dark
    svg = _Svg()
    for i, (prefix, state) in enumerate((("decoration", "active"), ("decoration-inactive", "inactive"))):
        bg = wm[f"{state}Background"]
        _frame(svg, g, prefix, i * (g.H + 8), bg, shift(bg, 0.25, dark), 0.6)
    return svg.render(g.W, 2 * g.H + 8)


# --- buttons -------------------------------------------------------------------

def _glyph(kind: str, cx: float, cy: float, s: float, color: RGB, alpha: float = 1.0) -> str:
    """Line-art symbol centered at (cx, cy) for a button `s` px wide."""
    g = s * 0.2
    w = max(1.2, s / 16)
    stroke = (f'fill="none" stroke="{to_hex(color)}" stroke-opacity="{_n(alpha)}" stroke-width="{_n(w)}" '
              'stroke-linecap="round" stroke-linejoin="round"')
    P = lambda d: _path(d, stroke)  # noqa: E731
    f = _n
    if kind == "close":
        return P(f"M{f(cx-g)},{f(cy-g)} L{f(cx+g)},{f(cy+g)} M{f(cx-g)},{f(cy+g)} L{f(cx+g)},{f(cy-g)}")
    if kind == "minimize":
        return P(f"M{f(cx-g)},{f(cy)} H{f(cx+g)}")
    if kind == "maximize":
        return _rect(cx - g, cy - g, 2 * g, 2 * g, stroke)
    if kind == "restore":
        d = g * 0.55
        return (_rect(cx - g, cy - g + d, 2 * g - d, 2 * g - d, stroke)
                + P(f"M{f(cx-g+d)},{f(cy-g+d)} V{f(cy-g)} H{f(cx+g)} V{f(cy+g-d)} H{f(cx+g-d)}"))
    if kind == "pin":
        return f'<circle cx="{f(cx)}" cy="{f(cy)}" r="{f(g*0.65)}" fill="{to_hex(color)}" fill-opacity="{f(alpha)}"/>'
    if kind in ("above", "below"):
        k = -1 if kind == "above" else 1
        return P(f"M{f(cx-g)},{f(cy-k*g*0.5)} L{f(cx)},{f(cy+k*g*0.5)} L{f(cx+g)},{f(cy-k*g*0.5)}")
    if kind == "shade":
        return P(f"M{f(cx-g)},{f(cy-g*0.7)} H{f(cx+g)} M{f(cx-g)},{f(cy+g*0.7)} L{f(cx)},{f(cy-g*0.1)} L{f(cx+g)},{f(cy+g*0.7)}")
    if kind == "help":
        q = g * 0.65
        return (P(f"M{f(cx-q)},{f(cy-g*0.45)} A{f(q)},{f(q)} 0 1 1 {f(cx)},{f(cy+g*0.2)} V{f(cy+g*0.4)}")
                + f'<circle cx="{f(cx)}" cy="{f(cy+g*0.95)}" r="{f(w*0.6)}" fill="{to_hex(color)}" fill-opacity="{f(alpha)}"/>')
    raise ValueError(kind)


def _on(c: RGB) -> RGB:
    return (255, 255, 255) if luminance(c) < 0.45 else (24, 24, 28)


def button_svg(theme: Theme, kind: str) -> str:
    g = _Geo(theme)
    p = theme.palette.resolved()
    wm = _wm(theme)
    fg, ifg = wm["activeForeground"], wm["inactiveForeground"]
    s = g.box
    c = s / 2
    svg = _Svg()
    ghost = 'fill="#000000" fill-opacity="0.004"'
    neg = parse(p.negative)
    if theme.decoration.button_style == "dots":
        dot = {"close": p.negative, "minimize": p.neutral, "maximize": p.positive, "restore": p.positive}
        col = parse(dot.get(kind, p.accent))
        gray = mix(ifg, wm["inactiveBackground"], 0.35)
        rr = s / 2 - 1
        disc = lambda color, a=1.0: f'<circle cx="{_n(c)}" cy="{_n(c)}" r="{_n(rr)}" {_rgba(color, a)}/>'  # noqa: E731
        states = {
            "active": [disc(col)],
            "hover": [disc(col), _glyph(BUTTONS[kind], c, c, s * 0.9, _on(col), 0.85)],
            "pressed": [disc(mix(col, (0, 0, 0), 0.25)), _glyph(BUTTONS[kind], c, c, s * 0.9, _on(col), 0.85)],
            "inactive": [disc(gray)],
            "deactivated": [disc(gray, 0.45)],
        }
    else:
        rr = s / 2 - 1
        hover_bg, press_a = (neg, 1.0) if kind == "close" else (fg, 0.15)
        disc = lambda color, a: f'<circle cx="{_n(c)}" cy="{_n(c)}" r="{_n(rr)}" {_rgba(color, a)}/>'  # noqa: E731
        hover_fg = _on(neg) if kind == "close" else fg
        states = {
            "active": [_glyph(BUTTONS[kind], c, c, s, fg)],
            "hover": [disc(hover_bg, press_a), _glyph(BUTTONS[kind], c, c, s, hover_fg)],
            "pressed": [disc(mix(neg, (0, 0, 0), 0.2), 1.0) if kind == "close" else disc(fg, 0.3),
                        _glyph(BUTTONS[kind], c, c, s, hover_fg)],
            "inactive": [_glyph(BUTTONS[kind], c, c, s, ifg)],
            "deactivated": [_glyph(BUTTONS[kind], c, c, s, fg, 0.3)],
        }
    for i, (state, shapes) in enumerate(states.items()):
        x = i * (s + 4)
        body = "".join(shapes)
        svg.el(f"{state}-center", _rect(x, 0, s, s, ghost), f'<g transform="translate({_n(x)},0)">{body}</g>')
    return svg.render(len(states) * (s + 4), s)


# --- package -------------------------------------------------------------------

def rc(theme: Theme) -> str:
    d = theme.decoration
    g = _Geo(theme)
    wm = _wm(theme)
    return "\n".join([
        "[General]",
        f"ActiveTextColor={_kde_rgba(wm['activeForeground'])}",
        f"InactiveTextColor={_kde_rgba(wm['inactiveForeground'])}",
        f"TitleAlignment={d.title_align.capitalize()}",
        "TitleVerticalAlignment=Center",
        "Animation=120",
        "",
        "[Layout]",
        f"BorderLeft={g.b}", f"BorderRight={g.b}", f"BorderBottom={g.b}",
        "TitleEdgeTop=0", "TitleEdgeBottom=0",
        f"TitleEdgeLeft={g.edge}", f"TitleEdgeRight={g.edge}",
        "TitleBorderLeft=8", "TitleBorderRight=8",
        f"TitleHeight={g.th}",
        f"ButtonWidth={g.box}", f"ButtonHeight={g.box}",
        f"ButtonSpacing={g.spacing}",
        f"ButtonMarginTop={(g.th - g.box) // 2}",
        "ExplicitButtonSpacer=10",
        f"PaddingTop={g.S}", f"PaddingBottom={g.S}", f"PaddingLeft={g.S}", f"PaddingRight={g.S}",
        "TitleEdgeTopMaximized=0", "TitleEdgeBottomMaximized=0",
        f"TitleEdgeLeftMaximized={g.edge}", f"TitleEdgeRightMaximized={g.edge}",
        f"TitleHeightMaximized={g.th}",
        "",
    ])


def metadata(theme: Theme) -> str:
    name = theme.decoration_name
    return json.dumps({
        "KPackageStructure": "aurorae",
        "KPlugin": {
            "Id": name,
            "Name": f"{theme.name}",
            "Description": f"Window decoration for {theme.name}, generated by kde-customizer",
            "Authors": [{"Name": theme.author or "Unknown"}],
            "Category": "Plasma 6 Window Decorations",
            "License": "GPL-2.0+",
            "Version": theme.version,
            "EnabledByDefault": True,
        },
    }, indent=2) + "\n"


def metadata_desktop(theme: Theme) -> str:
    """Older KWin versions list Aurorae themes from metadata.desktop."""
    name = theme.decoration_name
    return "\n".join([
        "[Desktop Entry]", f"Name={theme.name}", f"X-KDE-PluginInfo-Name={name}",
        f"X-KDE-PluginInfo-Author={theme.author or 'Unknown'}", f"X-KDE-PluginInfo-Version={theme.version}",
        "X-KDE-PluginInfo-License=GPL", "X-KDE-PluginInfo-EnabledByDefault=true", "",
    ])


def files(theme: Theme) -> dict[str, str]:
    """File name inside the theme folder -> content."""
    name = theme.decoration_name
    out = {
        "metadata.json": metadata(theme),
        "metadata.desktop": metadata_desktop(theme),
        f"{name}rc": rc(theme),
        "decoration.svg": decoration_svg(theme),
    }
    for kind in BUTTONS:
        out[f"{kind}.svg"] = button_svg(theme, kind)
    return out
