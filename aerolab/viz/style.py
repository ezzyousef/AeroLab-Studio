"""One definition of "publishable" — shared by the on-screen plots and by Origin.

Colours are a colourblind-safe qualitative ramp checked against deuteranopia,
protanopia and tritanopia simulations, with enough lightness separation to survive
greyscale printing. Symbols are the open/filled shapes journals expect, ordered so that
neighbouring series never share a shape.

The Origin bridge reads the very same tables, so a figure exported to Origin looks like
the one on screen rather than like Origin's default template.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "PALETTES", "SYMBOLS", "ORIGIN_SYMBOL", "MPL_MARKER", "LINE_STYLES", "ORIGIN_LINE_STYLE",
    "SeriesStyle", "Theme", "THEMES", "style_for", "palette", "apply_matplotlib_style",
    "FIGURE_SIZES", "EXPORT_DPI",
]

# ---------------------------------------------------------------------------
# colour
# ---------------------------------------------------------------------------
PALETTES: dict[str, list[str]] = {
    # Default: Okabe–Ito, the standard colourblind-safe eight, reordered so the first
    # three are also the most distinct in greyscale.
    "publication": ["#0072B2", "#D55E00", "#009E73", "#CC79A7",
                    "#E69F00", "#56B4E9", "#7F3F98", "#333333"],
    # Higher contrast for dark backgrounds and projected slides.
    "vivid": ["#3987E5", "#FF7A45", "#1FC28C", "#FF6FB5",
              "#FFC24B", "#7DD3FC", "#A78BFA", "#E5E7EB"],
    # Sequential ramp for a series ordered by a parameter (density, temperature, cycle).
    "sequential": ["#08306B", "#12508F", "#2171B5", "#4292C6",
                   "#6BAED6", "#9ECAE1", "#C6DBEF", "#DEEBF7"],
    # Warm-to-cool diverging ramp, for signed quantities.
    "diverging": ["#B2182B", "#D6604D", "#F4A582", "#FDDBC7",
                  "#D1E5F0", "#92C5DE", "#4393C3", "#2166AC"],
    # One accent against a graded grey ramp, for figures where a single series is the
    # point and the rest are context. Every tone is distinct, so the greys stay tellable
    # apart even when six of them share a plot.
    "focus": ["#0072B2", "#2F343B", "#4A5058", "#656C75",
              "#828992", "#9EA5AD", "#B9BFC6", "#D4D9DE"],
}

DEFAULT_PALETTE = "publication"

# Fits and guides are drawn in the parent series' colour but thinner and dashed; when a
# fit has no parent it falls back to these.
FIT_COLOUR_LIGHT = "#333333"
FIT_COLOUR_DARK = "#D5D8DD"


# ---------------------------------------------------------------------------
# symbols
# ---------------------------------------------------------------------------
# Order matters: adjacent entries differ in shape *and* in fill.
SYMBOLS: list[str] = ["circle", "square", "triangle_up", "diamond",
                      "triangle_down", "hexagon", "star", "cross"]

MPL_MARKER: dict[str, str] = {
    "circle": "o", "square": "s", "triangle_up": "^", "diamond": "D",
    "triangle_down": "v", "hexagon": "h", "star": "*", "cross": "X",
    "plus": "P", "none": "",
}

# Origin's symbol shape codes for `set %C -k <n>` / plot.symbol_kind.
ORIGIN_SYMBOL: dict[str, int] = {
    "circle": 2, "square": 3, "triangle_up": 7, "diamond": 5,
    "triangle_down": 8, "hexagon": 12, "star": 10, "cross": 15,
    "plus": 14, "none": 0,
}

LINE_STYLES: dict[str, tuple[float, ...] | None] = {
    "solid": None, "dash": (6, 3), "dot": (1.5, 2.5),
    "dashdot": (7, 2.5, 1.5, 2.5), "longdash": (11, 4),
}

# Origin's line style codes for `set %C -d <n>`.
ORIGIN_LINE_STYLE: dict[str, int] = {
    "solid": 0, "dash": 1, "dot": 2, "dashdot": 3, "longdash": 5,
}


@dataclass(frozen=True)
class SeriesStyle:
    """Everything needed to draw one trace, in either renderer."""
    colour: str
    symbol: str
    line_style: str
    line_width: float
    symbol_size: float
    filled: bool
    label: str = ""

    # -- matplotlib ----------------------------------------------------------
    @property
    def marker(self) -> str:
        return MPL_MARKER.get(self.symbol, "o")

    @property
    def dashes(self) -> tuple[float, ...] | None:
        return LINE_STYLES.get(self.line_style)

    def mpl_kwargs(self, background: str = "#FFFFFF") -> dict:
        kw: dict = {
            "color": self.colour,
            "linewidth": self.line_width,
            "markersize": self.symbol_size,
            "markeredgecolor": self.colour,
            "markerfacecolor": self.colour if self.filled else background,
            "markeredgewidth": 1.1,
            "label": self.label,
        }
        kw["marker"] = self.marker if self.symbol != "none" else ""
        if self.line_style == "none" or self.line_width <= 0:
            kw["linestyle"] = "none"
        elif self.dashes:
            kw["linestyle"] = (0, self.dashes)
        else:
            kw["linestyle"] = "-"
        return kw

    # -- Origin --------------------------------------------------------------
    @property
    def origin_symbol(self) -> int:
        return ORIGIN_SYMBOL.get(self.symbol, 2)

    @property
    def origin_line_style(self) -> int:
        return ORIGIN_LINE_STYLE.get(self.line_style, 0)

    @property
    def origin_symbol_interior(self) -> int:
        """Origin's `plotN.symbol.interior`: 0 fills with the plot colour, 1 leaves it open.

        Verified against Origin 2026b — originpro's own docstring has these the other way
        round, and setting 1 there produces a hollow symbol, not a solid one.
        """
        return 0 if self.filled else 1

    @property
    def rgb(self) -> tuple[int, int, int]:
        h = self.colour.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    @property
    def origin_color(self) -> int:
        """Origin packs colours as BGR in a 32-bit int."""
        r, g, b = self.rgb
        return (b << 16) | (g << 8) | r


# ---------------------------------------------------------------------------
# themes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Theme:
    name: str
    background: str
    panel: str
    foreground: str
    muted: str
    grid: str
    accent: str
    palette: str = DEFAULT_PALETTE


THEMES: dict[str, Theme] = {
    "light": Theme("light", "#FFFFFF", "#F6F7F9", "#1B1F24", "#6A7280",
                   "#DDE1E6", "#0072B2", "publication"),
    "dark": Theme("dark", "#15181D", "#1E2228", "#E8EAED", "#9AA1AB",
                  "#2C313A", "#3987E5", "vivid"),
}

FIGURE_SIZES: dict[str, tuple[float, float]] = {
    "single_column": (3.35, 2.6),      # 85 mm, the usual single-column width
    "double_column": (6.9, 4.2),       # 175 mm
    "square": (4.2, 4.2),
    "presentation": (8.0, 4.5),
    "screen": (7.2, 4.6),
}

EXPORT_DPI = {"screen": 110, "print": 300, "poster": 600}


# ---------------------------------------------------------------------------
# assignment
# ---------------------------------------------------------------------------
def palette(name: str | None = None) -> list[str]:
    return PALETTES.get(name or DEFAULT_PALETTE, PALETTES[DEFAULT_PALETTE])


def style_for(index: int, role: str = "data", *, palette_name: str | None = None,
              label: str = "", parent: int | None = None, theme: str = "light",
              style_hint: str = "scatter") -> SeriesStyle:
    """Pick the style for series `index`.

    `role` is what the series is for — measured data, a fitted line, or a guide.
    `parent` lets a fit borrow the colour of the data it belongs to, which is what
    makes a figure with four data sets and four fits readable.
    """
    colours = palette(palette_name)
    source = parent if parent is not None else index
    colour = colours[source % len(colours)]
    symbol = SYMBOLS[source % len(SYMBOLS)]
    filled = (source // len(SYMBOLS)) % 2 == 0

    if role == "fit":
        return SeriesStyle(colour, "none", "dash", 1.6, 0.0, False, label)
    if role == "guide":
        muted = FIT_COLOUR_DARK if theme == "dark" else FIT_COLOUR_LIGHT
        return SeriesStyle(muted, "none", "dot", 1.2, 0.0, False, label)

    if style_hint == "line":
        return SeriesStyle(colour, "none", "solid", 1.9, 0.0, True, label)
    if style_hint == "scatter+line":
        return SeriesStyle(colour, symbol, "solid", 1.4, 5.4, filled, label)
    return SeriesStyle(colour, symbol, "none", 0.0, 6.0, filled, label)


def apply_matplotlib_style(theme: str = "light", size: str = "screen") -> dict:
    """rcParams for a figure that already looks like a journal figure."""
    t = THEMES.get(theme, THEMES["light"])
    return {
        "figure.figsize": FIGURE_SIZES.get(size, FIGURE_SIZES["screen"]),
        "figure.facecolor": t.background,
        "figure.dpi": 110,
        "savefig.facecolor": t.background,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.06,
        "axes.facecolor": t.background,
        "axes.edgecolor": t.foreground,
        "axes.labelcolor": t.foreground,
        "axes.titlecolor": t.foreground,
        "axes.linewidth": 1.0,
        "axes.grid": True,
        "axes.axisbelow": True,
        "axes.titlesize": 11,
        "axes.titleweight": "semibold",
        "axes.titlepad": 9,
        "axes.labelsize": 10,
        "axes.labelpad": 5,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.prop_cycle": _cycler(palette(t.palette)),
        "grid.color": t.grid,
        "grid.linewidth": 0.7,
        "grid.alpha": 0.9,
        "xtick.color": t.foreground,
        "ytick.color": t.foreground,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "xtick.major.width": 1.0,
        "ytick.major.width": 1.0,
        "xtick.minor.visible": True,
        "ytick.minor.visible": True,
        "legend.frameon": True,
        "legend.framealpha": 0.92,
        "legend.facecolor": t.background,
        "legend.edgecolor": t.grid,
        "legend.fontsize": 9,
        "legend.labelcolor": t.foreground,
        "legend.borderpad": 0.5,
        "text.color": t.foreground,
        "font.size": 10,
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "Arial", "Helvetica", "DejaVu Sans"],
        "mathtext.fontset": "dejavusans",
        "lines.solid_capstyle": "round",
    }


def _cycler(colours):
    from cycler import cycler
    return cycler(color=colours)
