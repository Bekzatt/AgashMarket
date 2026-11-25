"""Штрих-коды EAN-13: рисование и печать этикеток (на этикеточный принтер или лист A4)."""
from PyQt5.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetricsF, QPageLayout, QPageSize, QPainter
from PyQt5.QtPrintSupport import QPrintDialog, QPrinter
from PyQt5.QtWidgets import QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QVBoxLayout, QWidget

from model.services import is_ean13, money
from views import style
from views.widgets import Card, button, label, number_box, show_error

# --- кодирование EAN-13
_L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"]
_R = ["".join("1" if b == "0" else "0" for b in code) for code in _L]
_G = [code[::-1] for code in _R]
_PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]
QUIET_LEFT, QUIET_RIGHT, MODULES = 11, 7, 95


def ean13_modules(code: str):
    """95 модулей (1 — чёрная полоса) + номера модулей, где полосы удлинённые (охранные)."""
    parity = _PARITY[int(code[0])]
    bits = "101"
    for digit, kind in zip(code[1:7], parity):
        bits += (_L if kind == "L" else _G)[int(digit)]
    bits += "01010"
    for digit in code[7:]:
        bits += _R[int(digit)]
    bits += "101"
    guards = set(range(0, 3)) | set(range(45, 50)) | set(range(92, 95))
    return bits, guards


def draw_ean13(p: QPainter, rect: QRectF, code: str):
    """Рисует штрих-код с цифрами внизу в прямоугольник rect."""
    bits, guards = ean13_modules(code)
    total = QUIET_LEFT + MODULES + QUIET_RIGHT
    module = rect.width() / total
    if module >= 1:
        # ширина полосы — целое число точек принтера: на термопринтере 203 dpi дробная ширина
        # даёт полосы разной толщины, и сканер читает код хуже
        module = float(int(module))
    digit_h = min(rect.height() * 0.22, module * 9)
    bar_bottom = rect.bottom() - digit_h * 0.75
    guard_bottom = rect.bottom() - digit_h * 0.25
    left = rect.left() + round((rect.width() - total * module) / 2)
    x0 = left + QUIET_LEFT * module
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("black"))
    for i, bit in enumerate(bits):
        if bit == "1":
            bottom = guard_bottom if i in guards else bar_bottom
            p.drawRect(QRectF(x0 + i * module, rect.top(), module, bottom - rect.top()))
    font = QFont("Consolas")
    font.setPixelSize(max(1, int(digit_h * 0.95)))
    p.setFont(font)
    p.setPen(QColor("black"))
    text_top = bar_bottom
    text_h = rect.bottom() - text_top + digit_h * 0.25
    p.drawText(QRectF(left, text_top, QUIET_LEFT * module - module, text_h),
               Qt.AlignRight | Qt.AlignVCenter, code[0])
    p.drawText(QRectF(x0 + 3 * module, text_top, 42 * module, text_h), Qt.AlignCenter, code[1:7])
    p.drawText(QRectF(x0 + 50 * module, text_top, 42 * module, text_h), Qt.AlignCenter, code[7:])
    p.restore()


def draw_label(p: QPainter, rect: QRectF, name: str, code: str, price=None):
    """Этикетка: название (до 2 строк), цена, штрих-код. rect — в любых единицах устройства."""
    pad = rect.height() * 0.06
    inner = rect.adjusted(pad, pad, -pad, -pad)
    p.save()
    p.fillRect(rect, QColor("white"))
    title_font = QFont(style.display_family())
    title_font.setPixelSize(max(1, int(inner.height() * 0.13)))
    title_font.setBold(True)
    p.setFont(title_font)
    p.setPen(QColor("black"))
    metrics = QFontMetricsF(title_font)
    title_h = metrics.lineSpacing() * 2
    price_w = 0
    if price:
        price_font = QFont(style.display_family())
        price_font.setPixelSize(max(1, int(inner.height() * 0.15)))
        price_font.setBold(True)
        price_text = f"{money(price)} ₸"
        price_w = QFontMetricsF(price_font).horizontalAdvance(price_text) + pad
        p.setFont(price_font)
        p.drawText(QRectF(inner.right() - price_w, inner.top(), price_w, title_h),
                   Qt.AlignRight | Qt.AlignTop, price_text)
        p.setFont(title_font)
    title_rect = QRectF(inner.left(), inner.top(), inner.width() - price_w, title_h)
    text = _elide_two_lines(name, metrics, title_rect.width())
    p.drawText(title_rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, text)
    code_rect = QRectF(inner.left(), inner.top() + title_h + pad * 0.5, inner.width(),
                       inner.height() - title_h - pad * 0.5)
    draw_ean13(p, code_rect, code)
    p.restore()


def _elide_two_lines(text, metrics: QFontMetricsF, width):
    """Название, которое не помещается в 2 строки, обрезается с «…»."""
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if metrics.horizontalAdvance(candidate) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    if len(lines) <= 2:
        return "\n".join(lines)
    return lines[0] + "\n" + metrics.elidedText(" ".join(lines[1:]), Qt.ElideRight, width)


# --- окно печати этикеток
LABEL_SIZES = [(58, 40), (58, 30), (40, 30), (30, 20)]
TARGET_LABEL, TARGET_A4 = "Этикеточный принтер", "Обычный принтер, лист A4"


class _Preview(QWidget):
    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        self.setMinimumSize(300, 220)

    def paintEvent(self, event):
        w_mm, h_mm = self.dialog.label_size()
        scale = min((self.width() - 20) / w_mm, (self.height() - 20) / h_mm)
        rect = QRectF(0, 0, w_mm * scale, h_mm * scale)
        rect.moveCenter(QRectF(self.rect()).center())
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.fillRect(rect.translated(0, 2), QColor(0, 0, 0, 22))
        draw_label(p, rect, *self.dialog.label_args())
        p.setPen(QColor(style.LINE))
        p.drawRect(rect)


class LabelDialog(QDialog):
    def __init__(self, product, parent=None):
        super().__init__(parent)
        self.product = product
        self.setWindowTitle("Печать этикеток")
        self.setStyleSheet(f"QDialog {{ background: {style.FROST}; }}")

        self.size_box = QComboBox()
        for w, h in LABEL_SIZES:
            self.size_box.addItem(f"{w} × {h} мм", (w, h))
        self.target = QComboBox()
        self.target.addItems([TARGET_LABEL, TARGET_A4])
        self.copies = number_box(1, 1000, " шт")
        self.copies.setValue(max(1, min(product.quantity or 1, 1000)))
        self.with_price = QCheckBox("Печатать цену продажи")
        self.with_price.setChecked(bool(product.salePrice))
        self.with_price.setEnabled(bool(product.salePrice))
        if not product.salePrice:
            self.with_price.setToolTip("Цена продажи не задана — её можно указать на «Складе»")

        card = Card()
        card.body.addWidget(label(product.name, "FormTitle"))
        card.body.addWidget(label(f"Штрих-код {product.barcode}", "Muted"))
        self.preview = _Preview(self)
        card.body.addWidget(self.preview, 1)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow("Размер этикетки", self.size_box)
        form.addRow("Принтер", self.target)
        form.addRow("Количество", self.copies)
        form.addRow("", self.with_price)
        card.body.addLayout(form)
        for w in (self.size_box, self.target):
            w.currentIndexChanged.connect(self.preview.update)
        self.with_price.toggled.connect(self.preview.update)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(button("Закрыть", None, self.reject))
        print_btn = button("Печать", "primary", self.print_labels)
        print_btn.setDefault(True)
        buttons.addWidget(print_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        root.addWidget(card, 1)
        root.addLayout(buttons)
        self.resize(440, 560)

    def label_size(self):
        return self.size_box.currentData()

    def label_args(self):
        price = self.product.salePrice if self.with_price.isChecked() else None
        return self.product.name, self.product.barcode, price

    def print_labels(self):
        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(f"Этикетки {self.product.name}")
        w, h = self.label_size()
        on_labels = self.target.currentText() == TARGET_LABEL
        if on_labels:  # страница = одна этикетка
            size = QPageSize(QSizeF(w, h), QPageSize.Millimeter, f"Этикетка {w}x{h}")
            printer.setPageLayout(QPageLayout(size, QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
        else:
            printer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait,
                                              QMarginsF(8, 8, 8, 8)))
        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle("Печать этикеток")
        if dialog.exec_() != QDialog.Accepted:
            return
        try:
            print_labels(printer, *self.label_args(), copies=self.copies.value(), size_mm=(w, h),
                         grid=not on_labels)
        except Exception as ex:
            show_error(self, ex)
            return
        self.accept()


def print_labels(printer: QPrinter, name, code, price, copies, size_mm, grid):
    """grid=False — по одной этикетке на страницу (этикеточный принтер), растянуто на страницу.
    grid=True — этикетки нужного размера сеткой на листе, с линиями для разрезания."""
    if not is_ean13(code or ""):
        raise ValueError("Печатать можно только штрих-код EAN-13 (13 цифр)")
    p = QPainter()
    if not p.begin(printer):
        raise RuntimeError("Не удалось начать печать — проверьте принтер")
    try:
        page = QRectF(printer.pageRect())  # в точках принтера, без полей
        if not grid:
            for i in range(copies):
                if i:
                    printer.newPage()
                draw_label(p, page, name, code, price)
            return
        per_mm = printer.resolution() / 25.4
        w, h = size_mm[0] * per_mm, size_mm[1] * per_mm
        cols, rows = max(1, int(page.width() // w)), max(1, int(page.height() // h))
        cut_pen = QColor(170, 170, 170)
        for i in range(copies):
            slot = i % (cols * rows)
            if i and slot == 0:
                printer.newPage()
            rect = QRectF(slot % cols * w, slot // cols * h, w, h)
            draw_label(p, rect, name, code, price)
            p.setPen(cut_pen)
            p.drawRect(rect)
    finally:
        p.end()
