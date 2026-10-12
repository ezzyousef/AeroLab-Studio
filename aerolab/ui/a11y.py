"""Accessibility passes run over a built page (same as labkit.qt.a11y; AeroLab does not vendor labkit).

`label_inputs(root)` ties each caption QLabel to the input it describes, so Alt+mnemonic
focuses the input and a screen reader announces it by the caption (WCAG 1.3.1 / 4.1.2).
Pages build their forms in many ways -- grid rows, form layouts, a label then an input in a
horizontal row -- so this walks the layouts after the fact instead of asking every page to
remember `setBuddy`. An input that already has a buddy label or an accessible name is left
alone, and so is a label that already has a buddy.

`keyboard_friendly(root)` lets Tab leave tables (WCAG 2.1.2: no keyboard trap) and makes a
matplotlib navigation toolbar reachable from the keyboard.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractSpinBox, QComboBox,
                               QFormLayout, QGridLayout, QBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QTextEdit, QToolButton, QWidget)

_INPUTS = (QLineEdit, QAbstractSpinBox, QComboBox, QPlainTextEdit, QTextEdit)

__all__ = ["label_inputs", "keyboard_friendly"]


def _target(widget: QWidget | None) -> QWidget | None:
    """The focusable input inside `widget` (itself, its focus proxy, or a single child input)."""
    if widget is None:
        return None
    if isinstance(widget, _INPUTS):
        return widget
    proxy = widget.focusProxy()
    if isinstance(proxy, _INPUTS):
        return proxy
    inputs = [w for w in widget.findChildren(QWidget) if isinstance(w, _INPUTS)
              and not isinstance(w.parentWidget(), (QComboBox, QAbstractSpinBox))]
    return inputs[0] if len(inputs) == 1 else None


def _caption(label: QLabel) -> str:
    text = label.text().replace("&&", "\0").replace("&", "").replace("\0", "&")
    return text.strip().rstrip(":").strip()


def _tie(label: QWidget | None, widget: QWidget | None) -> bool:
    if not isinstance(label, QLabel) or label.buddy() is not None:
        return False
    target = _target(widget)
    if target is None or target.accessibleName():
        return False
    caption = _caption(label)
    if not caption or len(caption) > 80 or label.textFormat() == Qt.RichText:
        return False
    label.setBuddy(target)
    target.setAccessibleName(caption)
    return True


def _widget_at(layout, index: int) -> QWidget | None:
    item = layout.itemAt(index)
    return item.widget() if item is not None else None


def label_inputs(root: QWidget) -> int:
    """Tie captions to inputs everywhere under `root`; returns how many were tied."""
    tied = 0
    layouts = [w.layout() for w in [root, *root.findChildren(QWidget)] if w.layout() is not None]
    seen = set()
    while layouts:
        layout = layouts.pop()
        if id(layout) in seen:
            continue
        seen.add(id(layout))
        for i in range(layout.count()):
            child = layout.itemAt(i).layout()
            if child is not None:
                layouts.append(child)
        if isinstance(layout, QFormLayout):
            for row in range(layout.rowCount()):
                lab = layout.itemAt(row, QFormLayout.LabelRole)
                fld = layout.itemAt(row, QFormLayout.FieldRole)
                if lab is not None and fld is not None:
                    tied += _tie(lab.widget(), fld.widget())
        elif isinstance(layout, QGridLayout):
            for row in range(layout.rowCount()):
                for col in range(layout.columnCount() - 1):
                    a, b = layout.itemAtPosition(row, col), layout.itemAtPosition(row, col + 1)
                    if a is not None and b is not None:
                        tied += _tie(a.widget(), b.widget())
        elif isinstance(layout, QBoxLayout):
            widgets = [_widget_at(layout, i) for i in range(layout.count())]
            widgets = [w for w in widgets if w is not None]
            for a, b in zip(widgets, widgets[1:]):
                tied += _tie(a, b)
    return tied


def keyboard_friendly(root: QWidget) -> None:
    """Tab moves out of tables; navigation-toolbar buttons can be reached and are named."""
    for view in root.findChildren(QAbstractItemView):
        view.setTabKeyNavigation(False)
    try:
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
    except Exception:                                   # noqa: BLE001 - matplotlib optional
        return
    for bar in root.findChildren(NavigationToolbar2QT):
        for button in bar.findChildren(QAbstractButton):
            if isinstance(button, QToolButton):
                button.setFocusPolicy(Qt.TabFocus)
                name = (button.toolTip() or button.text() or "").split("\n")[0].strip()
                if name and not button.accessibleName():
                    button.setAccessibleName(name)
