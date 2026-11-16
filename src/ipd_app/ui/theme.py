"""Look of the application: colours, fonts and the style sheet, light and dark.

One place for every colour. Widgets do not set colours themselves: they carry
a name or a property (`role`, `primary`, `chip`, `card`) and the style sheet
decides what that looks like in the current colour scheme.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from .. import config

log = logging.getLogger("ipd_app.ui")

LIGHT = {
    "window": "#F5F5F7",
    "card": "#FFFFFF",
    "border": "#E1E1E6",
    "text": "#1D1D1F",
    "secondary": "#6E6E73",
    "disabled": "#B4B4BA",
    "accent": "#0071E3",
    "accent_hover": "#0A7BF0",
    "accent_pressed": "#0062C4",
    "accent_soft": "#E3F0FF",
    "on_accent": "#FFFFFF",
    "control": "#FFFFFF",
    "control_border": "#D2D2D7",
    "control_hover": "#F0F0F3",
    "control_pressed": "#E4E4E9",
    "chip": "#ECECF0",
    "chip_hover": "#E2E2E7",
    "track": "#E3E3E8",
    "selection": "#D6E8FF",
    "success": "#1F8A3B",
    "warning": "#A85A00",
    "danger": "#D12C22",
}
DARK = {
    "window": "#1C1C1E",
    "card": "#2A2A2D",
    "border": "#3A3A3D",
    "text": "#F5F5F7",
    "secondary": "#A1A1A6",
    "disabled": "#636366",
    "accent": "#0A84FF",
    "accent_hover": "#3B9BFF",
    "accent_pressed": "#0A6FD6",
    "accent_soft": "#17324F",
    "on_accent": "#FFFFFF",
    "control": "#38383B",
    "control_border": "#4A4A4E",
    "control_hover": "#444448",
    "control_pressed": "#4E4E53",
    "chip": "#38383B",
    "chip_hover": "#444448",
    "track": "#3F3F43",
    "selection": "#1D446E",
    "success": "#30D158",
    "warning": "#FFA62B",
    "danger": "#FF6259",
}

# Glyphs of the icon font that ships with Windows 10 and 11.
ICON_FONT = "Segoe MDL2 Assets"
GLYPH_ACCOUNTS = ""
GLYPH_SETTINGS = ""
GLYPH_LOG = ""
GLYPH_FOLDER = ""

_current: dict[str, str] = LIGHT


def colors() -> dict[str, str]:
    return _current


def is_dark(app: QApplication) -> bool:
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt older than 6.5
        return False


def animations_enabled() -> bool:
    """Windows setting "Show animations in Windows"; on by default elsewhere."""
    if sys.platform != "win32":
        return True
    try:
        enabled = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)  # SPI_GETCLIENTAREAANIMATION
        return bool(enabled.value)
    except (AttributeError, OSError):
        return True


def set_role(widget: QWidget, role: str) -> None:
    """Colour a label by meaning: "", "muted", "success", "warning" or "danger"."""
    if widget.property("role") == role:
        return
    widget.setProperty("role", role)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def icon_font(pixel_size: int = 16) -> QFont:
    font = QFont(ICON_FONT)
    font.setPixelSize(pixel_size)
    return font


def has_icon_font() -> bool:
    return ICON_FONT in QFontDatabase.families()


# ------------------------------------------------------------------ pictures


def _draw(name: str, color: str, scale: int) -> QPixmap:
    """Small arrows and the tick for the style sheet, which can only show files."""
    size = 12 * scale
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.6 * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    points = {
        "down": [(2.5, 4.5), (6, 8), (9.5, 4.5)],
        "up": [(2.5, 7.5), (6, 4), (9.5, 7.5)],
        "check": [(2.5, 6.2), (5, 8.7), (9.5, 3.6)],
    }[name]
    painter.drawPolyline([QPointF(x * scale, y * scale) for x, y in points])
    painter.end()
    return pixmap


def _pictures(palette: dict[str, str], dark: bool) -> dict[str, str]:
    """Write the pictures next to the settings and return their paths for the style sheet.

    Fixed names, overwritten on start: nothing piles up and nothing has to be removed.
    """
    folder = config.app_data_dir() / "theme"
    result: dict[str, str] = {}
    wanted = {
        "down": ("down", palette["secondary"]),
        "up": ("up", palette["secondary"]),
        "down_off": ("down", palette["disabled"]),
        "check": ("check", palette["on_accent"]),
    }
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for key, (shape, color) in wanted.items():
            base = f"{key}_{'dark' if dark else 'light'}"
            _draw(shape, color, 1).save(str(folder / f"{base}.png"))
            _draw(shape, color, 2).save(str(folder / f"{base}@2x.png"))
            result[key] = Path(folder / f"{base}.png").as_posix()
    except OSError as error:  # the look degrades to plain arrows, the program still works
        log.warning("Could not write theme pictures: %s", error)
        return {}
    return result


# --------------------------------------------------------------- style sheet


def stylesheet(c: dict[str, str], pictures: dict[str, str]) -> str:
    def image(key: str) -> str:
        return f'image: url("{pictures[key]}");' if key in pictures else ""

    return f"""
QWidget {{ color: {c['text']}; }}
QMainWindow, QDialog, QMessageBox {{ background: {c['window']}; }}
QToolTip {{ background: {c['card']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 4px 6px; }}

QFrame[card="true"] {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QLabel {{ background: transparent; }}
QLabel[role="muted"] {{ color: {c['secondary']}; }}
QLabel[role="success"] {{ color: {c['success']}; }}
QLabel[role="warning"] {{ color: {c['warning']}; }}
QLabel[role="danger"] {{ color: {c['danger']}; }}
QLabel[role="title"] {{ color: {c['secondary']}; font-size: 12px; font-weight: 600; }}
QLabel#percent {{ font-size: 44px; font-weight: 600; }}
QLineEdit#code {{ font-size: 22px; padding: 8px; }}
QLabel#percent[role="muted"] {{ color: {c['disabled']}; }}

QPushButton {{
    background: {c['control']}; border: 1px solid {c['control_border']}; border-radius: 8px;
    padding: 6px 14px; min-height: 18px;
}}
QPushButton:hover {{ background: {c['control_hover']}; }}
QPushButton:pressed {{ background: {c['control_pressed']}; }}
QPushButton:disabled {{ color: {c['disabled']}; border-color: {c['border']}; }}
QPushButton:focus {{ border-color: {c['accent']}; }}
QPushButton[primary="true"] {{
    background: {c['accent']}; color: {c['on_accent']}; border: 1px solid {c['accent']}; font-weight: 600;
}}
QPushButton[primary="true"]:hover {{ background: {c['accent_hover']}; border-color: {c['accent_hover']}; }}
QPushButton[primary="true"]:pressed {{ background: {c['accent_pressed']}; border-color: {c['accent_pressed']}; }}
QPushButton[primary="true"]:disabled {{ background: {c['track']}; border-color: {c['track']}; color: {c['disabled']}; }}
QPushButton[big="true"] {{ padding: 9px 30px; font-size: 14px; border-radius: 10px; }}
QPushButton[chip="true"] {{
    background: {c['chip']}; border: 1px solid transparent; border-radius: 14px; padding: 4px 12px; min-height: 18px;
}}
QPushButton[chip="true"]:hover {{ background: {c['chip_hover']}; }}
QPushButton[chip="true"]:checked {{ background: {c['accent_soft']}; border-color: {c['accent']}; color: {c['accent']}; }}
QPushButton[chip="true"]:disabled {{ color: {c['disabled']}; }}
QPushButton[link="true"] {{ background: transparent; border: none; color: {c['accent']}; padding: 4px 6px; }}
QPushButton[link="true"]:hover {{ text-decoration: underline; }}
QPushButton[link="true"]:disabled {{ color: {c['disabled']}; }}

QToolButton {{ background: transparent; border: none; border-radius: 8px; padding: 6px; color: {c['secondary']}; }}
QToolButton:hover {{ background: {c['chip']}; color: {c['text']}; }}
QToolButton:pressed {{ background: {c['chip_hover']}; }}
QToolButton:disabled {{ color: {c['disabled']}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QComboBox {{
    background: {c['control']}; border: 1px solid {c['control_border']}; border-radius: 8px;
    padding: 5px 8px; min-height: 18px; selection-background-color: {c['accent']}; selection-color: {c['on_accent']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QDateEdit:disabled, QComboBox:disabled {{
    color: {c['disabled']}; border-color: {c['border']};
}}
QLineEdit:read-only {{ color: {c['secondary']}; }}
QComboBox {{ padding-right: 26px; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 24px; }}
QSpinBox QLineEdit, QDoubleSpinBox QLineEdit, QDateEdit QLineEdit {{
    background: transparent; border: none; padding: 0 2px; min-height: 0;
}}
QComboBox:hover {{ background: {c['control_hover']}; }}
QComboBox::drop-down, QDateEdit::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none;
}}
QComboBox::down-arrow, QDateEdit::down-arrow {{ {image('down')} width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled, QDateEdit::down-arrow:disabled {{ {image('down_off')} }}
QComboBox[flat="true"] {{ background: transparent; border: 1px solid transparent; font-weight: 600; }}
QComboBox[flat="true"]:hover {{ background: {c['chip']}; }}
QComboBox[flat="true"]:disabled {{ color: {c['secondary']}; }}
QComboBox[quiet="true"] {{ background: transparent; border: 1px solid transparent; color: {c['secondary']}; }}
QComboBox[quiet="true"]:hover {{ background: {c['chip']}; color: {c['text']}; }}
QComboBox QAbstractItemView {{
    background: {c['card']}; border: 1px solid {c['border']}; outline: none; padding: 4px;
    selection-background-color: {c['accent']}; selection-color: {c['on_accent']};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
    width: 20px; border: none; background: transparent;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ {image('up')} width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ {image('down')} width: 10px; height: 10px; }}

QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {c['disabled']}; }}
QCheckBox::indicator, QListView::indicator {{
    width: 16px; height: 16px; border: 1px solid {c['control_border']}; border-radius: 5px; background: {c['control']};
}}
QCheckBox::indicator:checked, QListView::indicator:checked {{
    background: {c['accent']}; border-color: {c['accent']}; {image('check')}
}}
QCheckBox::indicator:disabled {{ background: {c['track']}; border-color: {c['border']}; }}
QRadioButton::indicator {{
    width: 16px; height: 16px; border: 1px solid {c['control_border']}; border-radius: 9px; background: {c['control']};
}}
QRadioButton::indicator:checked {{ border: 5px solid {c['accent']}; width: 8px; height: 8px; background: {c['on_accent']}; }}

QProgressBar {{ background: {c['track']}; border: none; border-radius: 4px; min-height: 8px; max-height: 8px; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 4px; }}

QSlider::groove:horizontal {{ height: 4px; border-radius: 2px; background: {c['track']}; }}
QSlider::sub-page:horizontal {{ border-radius: 2px; background: {c['accent']}; }}
QSlider::handle:horizontal {{
    width: 16px; height: 16px; margin: -7px 0; border-radius: 9px;
    background: {c['card']}; border: 1px solid {c['control_border']};
}}

QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 12px; background: {c['card']}; top: -1px; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {c['secondary']}; border: none; padding: 7px 14px; margin: 0 2px 8px 0;
    border-radius: 8px;
}}
QTabBar::tab:hover {{ background: {c['chip']}; }}
QTabBar::tab:selected {{ background: {c['accent_soft']}; color: {c['accent']}; font-weight: 600; }}

QListWidget, QTableWidget, QPlainTextEdit {{
    background: {c['card']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 4px;
    selection-background-color: {c['selection']}; selection-color: {c['text']}; outline: none;
}}
QListWidget::item {{ padding: 6px 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {c['selection']}; color: {c['text']}; }}
QTableWidget {{ gridline-color: {c['border']}; }}
QHeaderView::section {{
    background: {c['card']}; color: {c['secondary']}; border: none; border-bottom: 1px solid {c['border']};
    padding: 6px 8px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {c['card']}; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {c['control_border']}; border-radius: 3px; min-height: 28px; min-width: 28px; }}
QScrollBar::handle:hover {{ background: {c['secondary']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{ background: {c['card']}; border: 1px solid {c['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: {c['accent']}; color: {c['on_accent']}; }}
QMenu::item:disabled {{ color: {c['disabled']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 8px; }}

QCalendarWidget QWidget {{ alternate-background-color: {c['card']}; }}
QCalendarWidget QAbstractItemView {{
    background: {c['card']}; selection-background-color: {c['accent']}; selection-color: {c['on_accent']};
}}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {c['card']}; }}
"""


def _palette(c: dict[str, str]) -> QPalette:
    """For what the style sheet does not reach: message box icons, calendar, native bits."""
    palette = QPalette()
    roles = QPalette.ColorRole
    for role, key in (
        (roles.Window, "window"),
        (roles.Base, "card"),
        (roles.AlternateBase, "window"),
        (roles.Button, "control"),
        (roles.WindowText, "text"),
        (roles.Text, "text"),
        (roles.ButtonText, "text"),
        (roles.ToolTipBase, "card"),
        (roles.ToolTipText, "text"),
        (roles.PlaceholderText, "disabled"),
        (roles.Highlight, "accent"),
        (roles.HighlightedText, "on_accent"),
        (roles.Link, "accent"),
        (roles.Mid, "secondary"),
    ):
        palette.setColor(role, QColor(c[key]))
    for role in (roles.WindowText, roles.Text, roles.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["disabled"]))
    return palette


def apply_theme(app: QApplication, dark: bool | None = None) -> bool:
    """Dress the whole application for the current Windows colour scheme. Returns True for dark."""
    global _current
    dark = is_dark(app) if dark is None else dark
    _current = DARK if dark else LIGHT
    app.setStyle("Fusion")
    font = QFont("Segoe UI Variable Text" if "Segoe UI Variable Text" in QFontDatabase.families() else "Segoe UI")
    font.setPointSizeF(9.75)
    app.setFont(font)
    app.setPalette(_palette(_current))
    app.setStyleSheet(stylesheet(_current, _pictures(_current, dark)))
    return dark


def follow_system(app: QApplication) -> None:
    """Switch between light and dark together with Windows, without a restart."""
    try:
        app.styleHints().colorSchemeChanged.connect(lambda _scheme: apply_theme(app))
    except AttributeError:
        pass
