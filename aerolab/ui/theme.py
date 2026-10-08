"""Qt styling — one stylesheet, two palettes, no per-widget colour code.

Every colour comes from `aerolab.viz.style.THEMES`, so the window chrome, the plots and
the Origin figures all agree.
"""
from __future__ import annotations

from ..viz.style import THEMES

__all__ = ["stylesheet", "colours", "ACCENTS", "FONT_STACK"]

FONT_STACK = '"Segoe UI Variable Text", "Segoe UI", Inter, Roboto, system-ui, sans-serif'
MONO_STACK = '"Cascadia Code", "Consolas", "JetBrains Mono", monospace'

# Extra tones the window chrome needs that a plot does not.
_EXTRA = {
    "light": {
        "rail": "#11151B", "rail_text": "#B7BFCA", "rail_active": "#FFFFFF",
        "surface": "#FFFFFF", "raised": "#F6F7F9", "sunken": "#EEF0F3",
        "border": "#DDE1E6", "border_strong": "#C3C9D2", "hover": "#EDF3FB",
        "selected": "#DCEAFB", "shadow": "rgba(16,24,40,0.10)",
        "good": "#0B7A4B", "warn": "#9A6400", "bad": "#B3261E",
        "good_bg": "#E7F6EE", "warn_bg": "#FDF3DC", "bad_bg": "#FCEBEA",
        "field": "#FFFFFF", "disabled": "#9AA1AB",
    },
    "dark": {
        "rail": "#0D1014", "rail_text": "#9AA3AF", "rail_active": "#FFFFFF",
        "surface": "#15181D", "raised": "#1E2228", "sunken": "#11141A",
        "border": "#2C313A", "border_strong": "#3B424D", "hover": "#222833",
        "selected": "#1E3350", "shadow": "rgba(0,0,0,0.45)",
        "good": "#4ADE80", "warn": "#FBBF24", "bad": "#F87171",
        "good_bg": "#13291F", "warn_bg": "#2A2213", "bad_bg": "#2C1718",
        "field": "#1A1E24", "disabled": "#5C646F",
    },
}

ACCENTS = {"light": "#0072B2", "dark": "#3987E5"}


def colours(theme: str = "light") -> dict[str, str]:
    """Every colour token for a theme, flattened into one dict."""
    t = THEMES.get(theme, THEMES["light"])
    c = {
        "bg": t.background, "panel": t.panel, "fg": t.foreground, "muted": t.muted,
        "grid": t.grid, "accent": t.accent,
    }
    c.update(_EXTRA.get(theme, _EXTRA["light"]))
    return c


def stylesheet(theme: str = "light") -> str:
    c = colours(theme)
    return f"""
* {{ font-family: {FONT_STACK}; font-size: 13px; }}

QWidget {{ background: {c['bg']}; color: {c['fg']}; }}
QMainWindow, QDialog {{ background: {c['bg']}; }}
QToolTip {{
    background: {c['rail']}; color: #FFFFFF; border: none;
    padding: 6px 9px; border-radius: 6px; font-size: 12px;
}}

/* ---------- navigation rail ---------- */
#NavRail {{ background: {c['rail']}; border: none; }}
#NavRail QLabel {{ background: transparent; color: {c['rail_text']}; }}
#NavBrand {{ color: #FFFFFF; font-size: 16px; font-weight: 700; padding: 2px 0 0 2px; }}
#NavVersion {{ color: {c['rail_text']}; font-size: 11px; padding: 0 0 2px 2px; }}
#NavSection {{
    color: #6B7480; font-size: 10px; font-weight: 700;
    letter-spacing: 1.1px; padding: 14px 12px 4px 12px;
}}
QPushButton#NavButton {{
    background: transparent; color: {c['rail_text']};
    border: none; border-radius: 8px; padding: 9px 12px;
    text-align: left; font-size: 13px; font-weight: 500;
}}
QPushButton#NavButton:hover {{ background: rgba(255,255,255,0.07); color: #FFFFFF; }}
QPushButton#NavButton:checked {{
    background: {c['accent']}; color: {c['rail_active']}; font-weight: 600;
}}
#NavBadge {{
    background: rgba(255,255,255,0.14); color: #FFFFFF; border-radius: 8px;
    padding: 1px 7px; font-size: 11px; font-weight: 700;
}}

/* ---------- headers ---------- */
#PageTitle {{ font-size: 23px; font-weight: 700; color: {c['fg']}; }}
#PageSubtitle {{ font-size: 13px; color: {c['muted']}; }}
#SectionTitle {{ font-size: 15px; font-weight: 650; color: {c['fg']}; }}
#Hint {{ color: {c['muted']}; font-size: 12px; }}
#Mono {{ font-family: {MONO_STACK}; font-size: 12px; }}

/* ---------- cards ---------- */
#Card {{
    background: {c['surface']}; border: 1px solid {c['border']};
    border-radius: 12px;
}}
#CardHeader {{ background: transparent; }}
#Tile {{
    background: {c['raised']}; border: 1px solid {c['border']};
    border-radius: 10px;
}}
#TileValue, #TileLabel, #TileUnit {{ background: transparent; }}
#TileValue {{ font-size: 21px; font-weight: 700; color: {c['fg']}; }}
#TileLabel {{ font-size: 11px; color: {c['muted']}; font-weight: 600; letter-spacing: .4px; }}
#TileUnit {{ font-size: 12px; color: {c['muted']}; }}

/* ---------- buttons ---------- */
QPushButton {{
    background: {c['surface']}; color: {c['fg']};
    border: 1px solid {c['border_strong']}; border-radius: 8px;
    padding: 7px 14px; font-weight: 550;
}}
QPushButton:hover {{ background: {c['hover']}; border-color: {c['accent']}; }}
QPushButton:pressed {{ background: {c['selected']}; }}
QPushButton:disabled {{ color: {c['disabled']}; border-color: {c['border']}; background: {c['sunken']}; }}
QPushButton#Primary {{
    background: {c['accent']}; color: #FFFFFF; border: 1px solid {c['accent']};
    font-weight: 600; padding: 8px 18px;
}}
QPushButton#Primary:hover {{ background: {c['accent']}; border-color: {c['fg']}; }}
QPushButton#Primary:disabled {{ background: {c['disabled']}; border-color: {c['disabled']}; color: {c['bg']}; }}
QPushButton#Ghost {{ background: transparent; border: none; color: {c['accent']}; padding: 5px 8px; }}
QPushButton#Ghost:hover {{ background: {c['hover']}; }}
QPushButton#Danger {{ color: {c['bad']}; border-color: {c['bad']}; background: transparent; }}
QPushButton#Danger:hover {{ background: {c['bad_bg']}; }}
QPushButton#Chip {{
    background: {c['raised']}; border: 1px solid {c['border']};
    border-radius: 14px; padding: 5px 13px; font-size: 12px; font-weight: 500;
}}
QPushButton#Chip:checked {{ background: {c['accent']}; color: #FFFFFF; border-color: {c['accent']}; }}

/* ---------- inputs ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {c['field']}; color: {c['fg']};
    border: 1px solid {c['border_strong']}; border-radius: 8px;
    padding: 6px 10px; selection-background-color: {c['accent']}; selection-color: #FFFFFF;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {c['accent']};
}}
QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled {{
    background: {c['sunken']}; color: {c['disabled']};
}}
QLineEdit#Search {{ border-radius: 9px; padding: 8px 12px; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none; border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {c['muted']}; margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {c['surface']}; color: {c['fg']}; border: 1px solid {c['border_strong']};
    border-radius: 8px; selection-background-color: {c['accent']}; selection-color: #FFFFFF;
    padding: 4px; outline: none;
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 17px; height: 17px; border-radius: 5px;
    border: 1px solid {c['border_strong']}; background: {c['field']};
}}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
QCheckBox::indicator:disabled {{ background: {c['sunken']}; }}
QRadioButton::indicator {{
    width: 16px; height: 16px; border-radius: 8px;
    border: 1px solid {c['border_strong']}; background: {c['field']};
}}
QRadioButton::indicator:checked {{ background: {c['accent']}; border: 4px solid {c['field']}; }}

/* ---------- tables ---------- */
QTableWidget, QTableView, QTreeWidget, QListWidget {{
    background: {c['surface']}; alternate-background-color: {c['raised']};
    border: 1px solid {c['border']}; border-radius: 10px;
    gridline-color: {c['grid']}; outline: none;
}}
QTableWidget::item, QTreeWidget::item, QListWidget::item {{
    padding: 5px 8px; border: none;
}}
QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {c['selected']}; color: {c['fg']};
}}
QHeaderView::section {{
    background: {c['raised']}; color: {c['muted']};
    padding: 8px 9px; border: none; border-bottom: 1px solid {c['border']};
    border-right: 1px solid {c['border']};
    font-weight: 650; font-size: 11px; letter-spacing: .35px;
}}
QHeaderView::section:first {{ border-top-left-radius: 9px; }}
QHeaderView::section:last {{ border-top-right-radius: 9px; border-right: none; }}
QTableCornerButton::section {{ background: {c['raised']}; border: none; }}

/* ---------- tabs ---------- */
QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 10px; top: -1px; }}
QTabBar::tab {{
    background: transparent; color: {c['muted']};
    padding: 8px 16px; border: none; border-bottom: 2px solid transparent;
    font-weight: 550;
}}
QTabBar::tab:selected {{ color: {c['accent']}; border-bottom: 2px solid {c['accent']}; }}
QTabBar::tab:hover:!selected {{ color: {c['fg']}; }}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle {{ background: {c['border_strong']}; border-radius: 5px; min-height: 28px; min-width: 28px; }}
QScrollBar::handle:hover {{ background: {c['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ border: none; background: transparent; }}

/* ---------- progress, splitter, status ---------- */
QProgressBar {{
    background: {c['sunken']}; border: none; border-radius: 4px;
    height: 7px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 4px; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {c['border']}; }}
#StatusBar {{ background: {c['raised']}; border-top: 1px solid {c['border']}; }}
#StatusText {{ color: {c['muted']}; font-size: 12px; }}

/* ---------- toast ---------- */
#Toast {{ border-radius: 10px; border: 1px solid {c['border_strong']}; background: {c['surface']}; }}
#ToastInfo    {{ background: {c['raised']};   border-left: 4px solid {c['accent']}; }}
#ToastSuccess {{ background: {c['good_bg']};  border-left: 4px solid {c['good']}; }}
#ToastWarning {{ background: {c['warn_bg']};  border-left: 4px solid {c['warn']}; }}
#ToastError   {{ background: {c['bad_bg']};   border-left: 4px solid {c['bad']}; }}
#ToastText {{ background: transparent; font-size: 12.5px; font-weight: 550; }}

/* ---------- status pills ---------- */
#PillGood {{ background: {c['good_bg']}; color: {c['good']};
             border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 700; }}
#PillWarn {{ background: {c['warn_bg']}; color: {c['warn']};
             border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 700; }}
#PillBad  {{ background: {c['bad_bg']};  color: {c['bad']};
             border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 700; }}

/* ---------- drop zone ---------- */
#DropZone {{
    background: {c['raised']}; border: 2px dashed {c['border_strong']};
    border-radius: 12px;
}}
#DropZone[hot="true"] {{ border-color: {c['accent']}; background: {c['hover']}; }}
#DropTitle {{ font-size: 15px; font-weight: 600; background: transparent; }}
#DropHint {{ color: {c['muted']}; font-size: 12px; background: transparent; }}

/* ---------- command palette ---------- */
#Palette {{ background: {c['surface']}; border: 1px solid {c['border_strong']}; border-radius: 14px; }}
#PaletteInput {{
    background: transparent; border: none; border-bottom: 1px solid {c['border']};
    border-radius: 0; padding: 14px 16px; font-size: 16px;
}}
#PaletteInput:focus {{ border: none; border-bottom: 1px solid {c['accent']}; }}
#PaletteList {{ background: transparent; border: none; }}
#PaletteList::item {{ padding: 9px 14px; border-radius: 8px; }}
#PaletteList::item:selected {{ background: {c['accent']}; color: #FFFFFF; }}

QFrame#HLine {{ background: {c['border']}; max-height: 1px; border: none; }}
QFrame#VLine {{ background: {c['border']}; max-width: 1px; border: none; }}
"""
