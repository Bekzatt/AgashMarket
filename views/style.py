"""Оформление кассы «Ағаш базар».

Палитра — ель, хвоя и смола. Bahnschrift (встроен в Windows 10/11, есть все казахские буквы и ₸)
используется для заголовков, меню и всех чисел; Segoe UI — для обычного текста.
"""
from PyQt5.QtCore import QLibraryInfo, QLocale, QTranslator
from PyQt5.QtGui import QFont, QFontDatabase

import config

SPRUCE = "#17312e"      # боковое меню
SPRUCE_2 = "#20413d"    # наведение в меню
NEEDLE = "#245a52"      # основные кнопки, фокус, выбранный день
NEEDLE_DARK = "#1b4741"
RESIN = "#c8871c"       # метка активного раздела, «сегодня» в календаре
RESIN_TINT = "#fbf0da"  # выделенная строка
FROST = "#edf1ef"       # фон
PAPER = "#ffffff"
LINE = "#d4dcd8"
RULE = "#e9eeeb"        # линии между строками
INK = "#1b2523"
MUTED = "#67756f"
DANGER = "#b3261e"

ICONS = (config.BASE_DIR / "images" / "ui").as_posix()
_display_family = None


def display_family() -> str:
    """Bahnschrift SemiBold, если система отдаёт его отдельным семейством, иначе Bahnschrift/Segoe UI."""
    global _display_family
    if _display_family is None:
        families = set(QFontDatabase().families())
        _display_family = next((f for f in ("Bahnschrift SemiBold", "Bahnschrift", "Segoe UI") if f in families),
                               "Segoe UI")
    return _display_family


def display_font(point_size: float) -> QFont:
    font = QFont(display_family())
    font.setPointSizeF(point_size)
    if display_family() != "Bahnschrift SemiBold":
        font.setWeight(QFont.DemiBold)
    return font


def number_font() -> QFont:
    """Числа в таблицах: Segoe UI с цифрами одинаковой ширины, полужирный — суммы читаются колонкой."""
    font = QFont("Segoe UI")
    font.setPointSizeF(10)
    font.setWeight(QFont.DemiBold)
    return font


def build_style() -> str:
    d = display_family()
    w = "normal" if d == "Bahnschrift SemiBold" else "600"
    return f"""
* {{ font-family: "Segoe UI"; font-size: 10pt; color: {INK}; }}
QMainWindow, QWidget#Root, QStackedWidget {{ background: {FROST}; }}
QToolTip {{ background: {SPRUCE}; color: #ffffff; border: none; padding: 6px 8px; }}

/* ---------- боковое меню ---------- */
QWidget#Sidebar {{ background: {SPRUCE}; }}
QLabel#Brand {{ font-family: "{d}"; font-weight: {w}; font-size: 17pt; color: #ffffff; padding: 22px 20px 0 20px; }}
QLabel#UserInfo {{ color: #9db3ac; padding: 2px 20px 20px 20px; }}
QListWidget#Nav {{ background: transparent; border: none; outline: 0;
    font-family: "{d}"; font-weight: {w}; font-size: 11pt; }}
QListWidget#Nav::item {{ color: #b9cbc5;
    padding: 9px 17px; border-left: 3px solid transparent; }}
QListWidget#Nav::item:hover {{ background: {SPRUCE_2}; color: #ffffff; }}
QListWidget#Nav::item:selected {{ background: {SPRUCE_2}; color: #ffffff; border-left: 3px solid {RESIN}; }}
QPushButton#SideButton {{ background: transparent; border: none; color: #9db3ac; text-align: left;
    padding: 0 20px; min-height: 32px; border-radius: 0; }}
QPushButton#SideButton:hover {{ color: #ffffff; background: {SPRUCE_2}; }}

/* ---------- заголовки ---------- */
QLabel#PageTitle {{ font-family: "{d}"; font-weight: {w}; font-size: 20pt; color: {SPRUCE}; }}
QLabel#Total {{ font-family: "{d}"; font-weight: {w}; font-size: 17pt; color: {NEEDLE}; }}
QLabel#FormTitle {{ font-family: "{d}"; font-weight: {w}; font-size: 12.5pt; color: {SPRUCE}; }}
QLabel#Muted, QLabel#StatTitle {{ color: {MUTED}; }}
QLabel#Warn {{ color: #8a5a0b; }}
QLabel#StatValue {{ font-family: "{d}"; font-weight: {w}; font-size: 21pt; color: {INK}; }}
QLabel#StatValue[tone="good"] {{ color: {NEEDLE}; }}
QLabel#StatValue[tone="bad"] {{ color: {DANGER}; }}
QFrame#Card {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 8px; }}
QFrame#Rule {{ background: {RULE}; border: none; max-height: 1px; min-height: 1px; }}

/* ---------- поля ввода ---------- */
QLineEdit, QComboBox, QSpinBox, QDateEdit {{
    background: {PAPER}; border: 1px solid {LINE}; border-radius: 6px;
    padding: 0 10px; min-height: 34px; selection-background-color: {RESIN_TINT}; selection-color: {INK}; }}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDateEdit:hover {{ border-color: #b7c4be; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus {{ border: 1px solid {NEEDLE}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QDateEdit:disabled {{
    background: #f3f5f4; color: #9aa6a1; border-color: {RULE}; }}
/* поле сканера в корзине: крупнее; при фокусе — смоляная рамка «готов к скану» */
QLineEdit#Scan {{ min-height: 42px; font-size: 11pt; background: {FROST}; border: 1px dashed #b7c4be; }}
QLineEdit#Scan:focus {{ background: {PAPER}; border: 2px solid {RESIN}; padding: 0 9px; }}

QComboBox {{ padding-right: 30px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 30px; border: none; }}
QComboBox::down-arrow {{ image: url({ICONS}/chevron-down.svg); width: 14px; height: 14px; }}
QComboBox::down-arrow:on {{ top: 1px; }}

QDateEdit {{ padding-right: 36px; }}
QDateEdit::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 34px;
    border: none; border-left: 1px solid {RULE}; }}
QDateEdit::down-arrow {{ image: url({ICONS}/calendar.svg); width: 16px; height: 16px; }}
QDateEdit::down-arrow:disabled {{ image: none; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid #a9b6b0; border-radius: 4px; background: {PAPER}; }}
QCheckBox::indicator:hover {{ border-color: {NEEDLE}; }}
QCheckBox::indicator:checked {{ background: {NEEDLE}; border-color: {NEEDLE}; image: url({ICONS}/check.svg); }}

/* ---------- выпадающие списки и подсказки ---------- */
QComboBox QAbstractItemView, QListView#Popup {{
    background: {PAPER}; border: 1px solid {LINE}; padding: 4px; outline: 0; }}
QComboBox QAbstractItemView::item, QListView#Popup::item {{
    min-height: 30px; padding: 0 10px; border: none; border-radius: 4px; color: {INK}; }}
QComboBox QAbstractItemView::item:hover, QListView#Popup::item:hover {{ background: {FROST}; }}
QComboBox QAbstractItemView::item:selected, QListView#Popup::item:selected {{ background: {RESIN_TINT}; color: {INK}; }}
QMenu {{ background: {PAPER}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {RESIN_TINT}; color: {INK}; }}

/* ---------- календарь ---------- */
QCalendarWidget {{ background: {PAPER}; border: 1px solid {LINE}; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {SPRUCE}; min-height: 42px; }}
QCalendarWidget QToolButton {{ font-family: "{d}"; font-weight: {w}; font-size: 11pt; color: #ffffff;
    background: transparent; border: none; border-radius: 6px; padding: 4px 10px; margin: 4px 2px; }}
QCalendarWidget QToolButton:hover {{ background: {SPRUCE_2}; }}
QCalendarWidget QToolButton::menu-indicator {{ image: none; width: 0; }}
QCalendarWidget QToolButton#qt_calendar_prevmonth {{ qproperty-icon: url({ICONS}/chevron-left.svg); }}
QCalendarWidget QToolButton#qt_calendar_nextmonth {{ qproperty-icon: url({ICONS}/chevron-right.svg); }}
QCalendarWidget QSpinBox {{ min-height: 26px; background: {PAPER}; color: {INK}; border-radius: 4px; }}
QCalendarWidget QAbstractItemView {{ background: {PAPER}; outline: 0; border: none;
    font-family: "Bahnschrift"; font-size: 10.5pt;
    selection-background-color: {NEEDLE}; selection-color: #ffffff; }}
QCalendarWidget QAbstractItemView:disabled {{ color: #c2cbc7; }}

/* ---------- кнопки ---------- */
QPushButton {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 6px; padding: 0 16px;
    min-height: 34px; color: {INK}; }}
QPushButton:hover {{ border-color: #b7c4be; background: #f7f9f8; }}
QPushButton:pressed {{ background: {FROST}; }}
QPushButton:focus {{ border-color: {NEEDLE}; }}
QPushButton:disabled {{ color: #a3aeaa; background: #f3f5f4; border-color: {RULE}; }}
QPushButton[kind="primary"] {{ background: {NEEDLE}; border: 1px solid {NEEDLE}; color: #ffffff; font-weight: 600; }}
QPushButton[kind="primary"]:hover {{ background: {NEEDLE_DARK}; border-color: {NEEDLE_DARK}; }}
QPushButton[kind="primary"]:focus {{ border: 2px solid {RESIN}; }}
QPushButton[kind="primary"]:disabled {{ background: #a9c0bb; border-color: #a9c0bb; color: #ffffff; }}
QPushButton[kind="danger"] {{ color: {DANGER}; border-color: #e6c4c0; }}
QPushButton[kind="danger"]:hover {{ background: #fcf1f0; }}
QPushButton[kind="danger"]:disabled {{ color: #c9a9a6; border-color: {RULE}; background: #f3f5f4; }}
QPushButton[kind="link"] {{ background: transparent; border: none; color: {NEEDLE}; min-height: 24px; padding: 0 4px; }}
QPushButton[kind="link"]:hover {{ text-decoration: underline; }}
QPushButton[size="large"] {{ min-height: 44px; font-size: 11pt; }}
QMessageBox QPushButton {{ min-width: 90px; }}
QMessageBox QLabel {{ min-width: 280px; }}

/* ---------- таблица: ведомость с тонкими линиями ---------- */
QTableView {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 8px; gridline-color: {RULE};
    selection-background-color: {RESIN_TINT}; selection-color: {INK}; outline: 0; }}
QTableView::item {{ border: none; border-bottom: 1px solid {RULE}; padding: 0 7px; }}
QTableView::item:selected {{ background: {RESIN_TINT}; color: {INK}; border-bottom: 1px solid #efdcb5; }}
QHeaderView {{ background: {PAPER}; border: none; border-top-left-radius: 8px; border-top-right-radius: 8px; }}
QHeaderView::section {{ background: {PAPER}; color: {MUTED}; font-weight: 600; border: none;
    border-bottom: 1px solid {LINE}; padding: 0 10px; min-height: 38px; }}
QTableCornerButton::section {{ background: {PAPER}; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 4px; }}
QScrollBar::handle {{ background: #c5cfcb; border-radius: 3px; }}
QScrollBar::handle:vertical {{ min-height: 32px; }}
QScrollBar::handle:horizontal {{ min-width: 32px; }}
QScrollBar::handle:hover {{ background: #9fb0a9; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    width: 0; height: 0; background: none; }}
"""


def setup_app(app) -> None:
    """Стиль Fusion + наши стили + русская локаль (названия месяцев, кнопки «Да/Нет»)."""
    app.setStyle("Fusion")
    QLocale.setDefault(QLocale(QLocale.Russian, QLocale.Kazakhstan))
    translator = QTranslator(app)
    if translator.load("qtbase_ru", QLibraryInfo.location(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
    app._translator = translator
    font = QFont("Segoe UI")
    font.setPointSizeF(10)
    app.setFont(font)
    app.setStyleSheet(build_style())
