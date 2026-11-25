"""Чек как в магазине: просмотр на экране и печать (на любой принтер, в т.ч. чековый 58/80 мм)."""
from html import escape

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QTextDocument
from PyQt5.QtPrintSupport import QPrintDialog, QPrinter
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QTextBrowser, QVBoxLayout, QWidget

from model.services import CASH, DEBT, KASPI, MIXED, Receipt, money
from views import style
from views.widgets import button, show_error

RECEIPT_FONT = "Consolas"  # есть во всех Windows, поддерживает казахские буквы и ₸
PAYMENT_NAMES = {CASH: "Наличные", KASPI: "Kaspi", MIXED: "Аралас", DEBT: "В долг (Қарыз)"}
WIDTH_CHARS = 32  # ширина ленты 80 мм ≈ 32–42 символа


def _rule(char="-"):
    return f'<p class="rule">{char * WIDTH_CHARS}</p>'


def receipt_html(r: Receipt) -> str:
    rows = []
    for line in r.lines:
        payment = PAYMENT_NAMES.get(line.payment, line.payment)
        if line.debt_payment:
            detail = f"оплата долга, {payment}"
        else:
            detail = f"{line.count} × {money(line.price)}, {payment}"
        rows.append(
            f'<tr><td colspan="2" class="item">{escape(line.name)}</td></tr>'
            f'<tr><td class="sub">&nbsp;&nbsp;{escape(detail)}</td>'
            f'<td class="sum" align="right">{money(line.summa)}</td></tr>'
        )
    pays = "".join(
        f'<tr><td class="sub">{escape(PAYMENT_NAMES.get(k, k))}</td><td align="right">{money(v)}</td></tr>'
        for k, v in r.by_type.items()
    )
    debtors = "".join(
        f'<p class="sub">Покупатель (долг): {escape(name)}{", " + escape(phone) if phone else ""}</p>'
        for name, phone in r.debtors
    )
    created = f"{r.created[8:10]}.{r.created[5:7]}.{r.created[0:4]} {r.created[11:16]}"
    shop = f'<p class="center">{escape(r.shop)}</p>' if r.shop else ""
    return f"""
<html><head><style>
  body {{ font-family: '{RECEIPT_FONT}'; font-size: 10pt; color: #111; }}
  p {{ margin: 0; }}
  .brand {{ font-size: 15pt; font-weight: bold; text-align: center; }}
  .center {{ text-align: center; }}
  .rule {{ color: #8a8a8a; margin: 4px 0; }}
  .sub {{ color: #555; }}
  .item {{ padding-top: 4px; }}
  .sum {{ font-weight: bold; }}
  .total td {{ font-size: 14pt; font-weight: bold; }}
</style></head><body>
<p class="brand">АҒАШ БАЗАР</p>
{shop}
{_rule()}
<p>Чек № {r.number}</p>
<p>{created}</p>
<p>Кассир: {escape(r.seller)}</p>
{_rule()}
<table width="100%" cellspacing="0" cellpadding="0">{''.join(rows)}</table>
{_rule("=")}
<table width="100%" cellspacing="0" cellpadding="0" class="total">
  <tr><td>ИТОГО</td><td align="right">{money(r.total)} ₸</td></tr>
</table>
<table width="100%" cellspacing="0" cellpadding="0">{pays}</table>
{debtors}
{_rule()}
<p class="center">Рақмет! Спасибо за покупку!</p>
</body></html>"""


class _Paper(QWidget):
    """Белая чековая лента с зубчатым нижним краем."""
    TOOTH = 9

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h, t = self.width(), self.height(), self.TOOTH
        path = QPainterPath(QPointF(0, 0))
        path.lineTo(w, 0)
        path.lineTo(w, h - t)
        x = w
        while x > 0:
            path.lineTo(max(x - t / 2, 0), h)
            path.lineTo(max(x - t, 0), h - t)
            x -= t
        path.closeSubpath()
        p.fillPath(path.translated(0, 2), QColor(0, 0, 0, 18))  # мягкая тень
        p.fillPath(path, QColor(style.PAPER))


class ReceiptDialog(QDialog):
    def __init__(self, receipt: Receipt, parent=None):
        super().__init__(parent)
        self.receipt = receipt
        self.html = receipt_html(receipt)
        self.setWindowTitle(f"Чек № {receipt.number}")
        self.setStyleSheet(f"QDialog {{ background: {style.FROST}; }}")

        paper = _Paper()
        paper.setFixedWidth(360)
        inner = QVBoxLayout(paper)
        inner.setContentsMargins(22, 22, 22, 22 + _Paper.TOOTH)
        view = QTextBrowser()
        view.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setHtml(self.html)
        view.document().setTextWidth(360 - 44)  # ширина ленты минус поля — тогда высота считается верно
        view.setFixedHeight(int(min(view.document().size().height() + 6, 600)))
        inner.addWidget(view)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(button("Закрыть", None, self.accept))
        print_btn = button("Печать чека", "primary", self.print_receipt)
        print_btn.setDefault(True)
        buttons.addWidget(print_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(18)
        root.addWidget(paper, 0, Qt.AlignHCenter)
        root.addLayout(buttons)

    def print_receipt(self):
        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(f"Чек {self.receipt.number}")
        # в PyQt5 у QPrinter своя версия setPageMargins: четыре числа + единицы QPrinter
        printer.setPageMargins(3, 3, 3, 3, QPrinter.Millimeter)
        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle("Печать чека")
        if dialog.exec_() != QDialog.Accepted:
            return
        try:
            doc = QTextDocument()
            doc.setDefaultFont(QFont(RECEIPT_FONT, 9))
            doc.setHtml(self.html)
            doc.print_(printer)
        except Exception as ex:
            show_error(self, ex)
