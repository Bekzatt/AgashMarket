"""Общие виджеты: модель таблицы, кнопки, карточки, сообщения об ошибках."""
import logging
from dataclasses import dataclass
from typing import Callable, Optional

from PyQt5.QtCore import QAbstractTableModel, QDate, QModelIndex, Qt
from PyQt5.QtGui import QColor, QPainter, QTextCharFormat
from PyQt5.QtWidgets import (QAbstractItemView, QCalendarWidget, QComboBox, QCompleter, QDateEdit, QFrame, QLabel,
                             QMessageBox, QPushButton, QSpinBox, QStyledItemDelegate, QTableView, QVBoxLayout)

from model.services import AppError, money
from views import style

log = logging.getLogger(__name__)


@dataclass
class Column:
    title: str
    getter: Callable
    kind: str = "text"  # text | int | money | datetime
    min_width: int = 0  # не ужимать колонку уже этого (например, название товара)


NUMERIC = ("money", "int")


def format_datetime(value: str) -> str:
    """'2026-11-25 11:09:41' → '25.11.2026  11:09'"""
    if not value or len(value) < 10 or value[4] != "-":
        return value or ""
    text = f"{value[8:10]}.{value[5:7]}.{value[0:4]}"
    return f"{text}  {value[11:16]}" if len(value) >= 16 else text


class RowsModel(QAbstractTableModel):
    """Табличная модель над списком объектов из services."""

    def __init__(self, columns, muted_if: Optional[Callable] = None):
        super().__init__()
        self.columns = columns
        self.rows = []
        self.muted_if = muted_if

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def row_at(self, index: int):
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        col = self.columns[index.column()]
        obj = self.rows[index.row()]
        if role == Qt.DisplayRole:
            value = col.getter(obj)
            if value is None:
                return ""
            if col.kind in NUMERIC:
                return money(value)
            return format_datetime(value) if col.kind == "datetime" else str(value)
        if role == Qt.ToolTipRole and col.kind == "text":
            value = col.getter(obj)
            return str(value) if value else None
        if role == Qt.TextAlignmentRole:
            if col.kind in NUMERIC:
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.FontRole and col.kind in NUMERIC:
            return self._number_font
        if role == Qt.ForegroundRole:
            if self.muted_if and self.muted_if(obj):
                return QColor("#a3aeaa")
            if col.kind == "datetime":
                return QColor(style.MUTED)
        return None

    @property
    def _number_font(self):
        if not hasattr(self, "_nf"):
            self._nf = style.number_font()
        return self._nf

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation != Qt.Horizontal:
            return None
        if role == Qt.DisplayRole:
            return self.columns[section].title
        if role == Qt.TextAlignmentRole:
            right = self.columns[section].kind in NUMERIC
            return int((Qt.AlignRight if right else Qt.AlignLeft) | Qt.AlignVCenter)
        return None


class DataTable(QTableView):
    """Таблица-ведомость. Когда строк нет — показывает подсказку, что делать."""

    def __init__(self, model, empty_text=""):
        super().__init__()
        self.empty_text = empty_text
        self.setModel(model)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setFocusPolicy(Qt.ClickFocus)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(38)
        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        header.setHighlightSections(False)
        header.setFixedHeight(40)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

    def fit_columns(self):
        self.resizeColumnsToContents()
        count = self.model().columnCount()
        for col in range(count - 1):
            self.setColumnWidth(col, min(self.columnWidth(col), 320))
        if count < 2:
            return
        # если не хватает нескольких пикселей — ужимаем самую широкую колонку, чтобы не было прокрутки
        last = count - 1
        last_needed = max(self.sizeHintForColumn(last), self.horizontalHeader().sectionSizeHint(last))
        overflow = sum(self.columnWidth(c) for c in range(last)) + last_needed + 8 - self.viewport().width()
        # не хватает места — по шагу ужимаем самые широкие текстовые колонки (не уже их заголовка);
        # полный текст обрезанной ячейки виден во всплывающей подсказке
        columns = getattr(self.model(), "columns", [])
        shrinkable = [c for c in range(last) if c < len(columns) and columns[c].kind == "text"]
        while overflow > 0 and shrinkable:
            widest = max(shrinkable, key=self.columnWidth)
            room = self.columnWidth(widest) - max(70, self.horizontalHeader().sectionSizeHint(widest),
                                                  columns[widest].min_width)
            if room <= 0:
                shrinkable.remove(widest)
                if not shrinkable:
                    break
                continue
            step = min(room, overflow, 20)
            self.setColumnWidth(widest, self.columnWidth(widest) - step)
            overflow -= step
        # Qt округляет ширину растянутой последней колонки — из-за 1–4 px не показываем прокрутку
        excess = self.horizontalHeader().length() - self.viewport().width()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff if excess <= 4 else Qt.ScrollBarAsNeeded)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.model() is not None and self.model().rowCount():
            self.fit_columns()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.model().rowCount() == 0 and self.empty_text:
            painter = QPainter(self.viewport())
            painter.setPen(QColor(style.MUTED))
            rect = self.viewport().rect().adjusted(40, 0, -40, 0)
            painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, self.empty_text)


def button(text, kind=None, slot=None) -> QPushButton:
    btn = QPushButton(text)
    if kind:
        btn.setProperty("kind", kind)
    btn.setCursor(Qt.PointingHandCursor)
    if slot:
        btn.clicked.connect(slot)
    return btn


def label(text="", name=None) -> QLabel:
    lbl = QLabel(text)
    lbl.setTextFormat(Qt.PlainText)  # названия товаров с "<" не должны превращаться в HTML
    if name:
        lbl.setObjectName(name)
    return lbl


class WrapLabel(QLabel):
    """Метка с переносом строк, которая сама пересчитывает свою высоту при смене текста
    (обычный QLabel с wordWrap в карточке фиксированной ширины сжимает соседние поля)."""

    def __init__(self, text="", name=None, width=332):
        super().__init__()
        self._wrap_width = width
        self.setWordWrap(True)
        self.setTextFormat(Qt.PlainText)
        if name:
            self.setObjectName(name)
        self.setText(text)

    def setText(self, text):
        super().setText(text)
        self.ensurePolished()
        self.setMinimumHeight(self.heightForWidth(self._wrap_width))
        # сообщаем карточке и её родителям, что высота изменилась
        parent = self.parentWidget()
        while parent is not None:
            if parent.layout() is not None:
                parent.layout().invalidate()
            parent.updateGeometry()
            if parent.objectName() == "Card":
                break
            parent = parent.parentWidget()


def number_box(minimum=0, maximum=100_000_000, suffix="") -> QSpinBox:
    box = QSpinBox()
    box.setRange(minimum, maximum)
    box.setGroupSeparatorShown(True)
    box.setButtonSymbols(QSpinBox.NoButtons)
    if suffix:
        box.setSuffix(suffix)
    return box


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 16)
        self.body.setSpacing(10)


def _style_popup(view):
    view.setObjectName("Popup")
    view.setItemDelegate(QStyledItemDelegate(view))


def combo(items=(), editable=False, placeholder="") -> QComboBox:
    box = QComboBox()
    box.setItemDelegate(QStyledItemDelegate(box))
    box.setMaxVisibleItems(12)
    if editable:
        box.setEditable(True)
        box.setInsertPolicy(QComboBox.NoInsert)
        completer = box.completer()
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        _style_popup(completer.popup())
        completer.popup().setMinimumWidth(320)
        if placeholder:
            box.lineEdit().setPlaceholderText(placeholder)
    box.addItems(list(items))
    return box


def date_edit(day=None) -> QDateEdit:
    """Поле даты с аккуратным календарём: неделя с понедельника, без номеров недель, «сегодня» выделено."""
    edit = QDateEdit(QDate.currentDate() if day is None else QDate(day), calendarPopup=True)
    edit.setDisplayFormat("dd.MM.yyyy")
    edit.setMinimumWidth(172)
    cal = edit.calendarWidget()
    cal.setFirstDayOfWeek(Qt.Monday)
    cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
    cal.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
    cal.setGridVisible(False)
    cal.setMinimumSize(300, 290)
    header = QTextCharFormat()
    header.setForeground(QColor(style.MUTED))
    header.setBackground(QColor(style.PAPER))
    cal.setHeaderTextFormat(header)
    weekend = QTextCharFormat()
    weekend.setForeground(QColor("#a5503a"))
    cal.setWeekdayTextFormat(Qt.Saturday, weekend)
    cal.setWeekdayTextFormat(Qt.Sunday, weekend)
    today = QTextCharFormat()
    today.setForeground(QColor(style.RESIN))
    today.setFontWeight(700)
    cal.setDateTextFormat(QDate.currentDate(), today)
    return edit


def rule() -> QFrame:
    line = QFrame()
    line.setObjectName("Rule")
    return line


def show_error(parent, ex) -> None:
    if isinstance(ex, AppError):
        QMessageBox.warning(parent, "Внимание", str(ex))
    else:
        log.exception("Ошибка", exc_info=ex)
        QMessageBox.critical(parent, "Ошибка", f"Произошла ошибка:\n{ex}")


def ask(parent, title, text) -> bool:
    return QMessageBox.question(parent, title, text, QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) == QMessageBox.Yes
