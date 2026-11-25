"""Главное окно кассы: боковое меню + страницы (Корзина, Заказы, Склад, Приход, Долги, Расходы, Отчёт)."""
from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (QApplication, QCheckBox, QFormLayout, QGridLayout, QHBoxLayout, QLineEdit, QListWidget, QMainWindow,
                             QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

import config
from model import services
from model.notifier import notify
from model.services import DEBT, DEBT_PAY_TYPES, PAYMENT_TYPES, is_ean13, money
from views.barcode import LabelDialog
from views.receipt import ReceiptDialog
from views.widgets import (Card, Column, DataTable, RowsModel, WrapLabel, ask, button, combo, date_edit,
                           format_datetime, label, number_box, rule, show_error)


# ====================================================================== база страницы

class BasePage(QWidget):
    title = ""
    columns = []
    has_search = True
    date_filter = None  # None | "today" | "all" — есть ли фильтр по дате и включён ли он по умолчанию
    empty_text = "Записей нет"

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.seller = main.seller.name
        self.model = RowsModel(self.columns, self.muted_if)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 24)
        root.setSpacing(16)

        header = QHBoxLayout()
        header.addWidget(label(self.title, "PageTitle"), 0, Qt.AlignBottom)
        header.addStretch()
        self.summary = label("", "Total")
        header.addWidget(self.summary, 0, Qt.AlignBottom)
        root.addLayout(header)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = QLineEdit(placeholderText="Поиск по названию, покупателю, телефону")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(340)
        self._search_timer = QTimer(self, singleShot=True, interval=300)
        self._search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(self._search_timer.start)
        self.search.setVisible(self.has_search)
        bar.addWidget(self.search)
        if self.date_filter:
            self.day_check = QCheckBox("За дату")
            self.day_check.setChecked(self.date_filter == "today")
            self.day_edit = date_edit()
            self.day_edit.setEnabled(self.day_check.isChecked())
            self.day_check.toggled.connect(self.day_edit.setEnabled)
            self.day_check.toggled.connect(self.refresh)
            self.day_edit.dateChanged.connect(self.refresh)
            bar.addWidget(self.day_check)
            bar.addWidget(self.day_edit)
        bar.addStretch()
        for widget in self.bar_widgets():
            bar.addWidget(widget)
        bar.addWidget(button("Обновить", None, self.refresh))
        if self.has_search or self.date_filter:  # в корзине строка поиска не нужна
            root.addLayout(bar)

        body = QHBoxLayout()
        body.setSpacing(16)
        self.table = DataTable(self.model, self.empty_text)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self.on_select(self.selected()))
        body.addWidget(self.table, 1)
        side = self.build_side()
        if side is not None:
            side.setFixedWidth(370)
            column = QVBoxLayout()  # карточка растёт вместе с содержимым, снизу пустое место
            column.addWidget(side)
            column.addStretch(1)
            body.addLayout(column)
        root.addLayout(body, 1)

    # --- переопределяется на страницах
    def fetch(self, search, day):
        raise NotImplementedError

    def build_side(self):
        return None

    def bar_widgets(self):
        return []

    def after_refresh(self, rows):
        pass

    def on_select(self, obj):
        pass

    def muted_if(self, obj):
        return False

    # --- общее
    def side_card(self, title) -> Card:
        card = Card()
        self.side_title = label(title, "FormTitle")
        card.body.addWidget(self.side_title)
        return card

    def current_day(self):
        if self.date_filter and self.day_check.isChecked():
            return self.day_edit.date().toPyDate()
        return None

    def selected(self):
        rows = self.table.selectionModel().selectedRows()
        return self.model.row_at(rows[0].row()) if rows else None

    def refresh(self):
        selected_id = getattr(self.selected(), "id", None)
        try:
            rows = self.fetch(self.search.text(), self.current_day())
        except Exception as ex:
            show_error(self, ex)
            return
        self.model.set_rows(rows)
        self.table.fit_columns()
        for i, row in enumerate(rows):
            if selected_id is not None and row.id == selected_id:
                self.table.selectRow(i)
                break
        self.on_select(self.selected())
        self.after_refresh(rows)

    def on_show(self):
        self.refresh()


# ====================================================================== Корзина

class CartPage(BasePage):
    title = "Корзина"
    has_search = False
    empty_text = ("Корзина пуста. Отсканируйте штрих-код товара или выберите товар справа "
                  "и нажмите «Добавить в корзину».")
    columns = [
        Column("Товар", lambda r: r.nameProduct),
        Column("Кол-во", lambda r: r.count, "int"),
        Column("Сумма", lambda r: r.summa, "money"),
        Column("Оплата", lambda r: r.paymentType),
        Column("Покупатель", lambda r: r.nameCustomer),
        Column("Телефон", lambda r: r.phoneNumberCustomer),
    ]

    def __init__(self, main):
        self.editing = False
        self.last_receipt = None
        super().__init__(main)

    def fetch(self, search, day):
        return services.list_cart(self.seller)

    def build_side(self):
        card = self.side_card("Добавить товар")
        self.scan = QLineEdit(placeholderText="Отсканируйте штрих-код")
        self.scan.setObjectName("Scan")
        self.scan.setClearButtonEnabled(True)
        self.scan.addAction(QIcon(str(config.BASE_DIR / "images" / "ui" / "barcode.svg")), QLineEdit.LeadingPosition)
        self.scan.returnPressed.connect(lambda: self.on_scan(self.scan.text()))
        card.body.addWidget(self.scan)
        self.scan_status = WrapLabel("", "Muted")
        self.scan_status.setVisible(False)
        card.body.addWidget(self.scan_status)
        card.body.addWidget(rule())
        self.hint = WrapLabel("Чтобы изменить позицию, выберите её в таблице.", "Muted")
        card.body.addWidget(self.hint)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.product = combo(editable=True, placeholder="Начните вводить название")
        # если штрих-код отсканировали в поле «Товар» — обрабатываем как скан
        self.product.lineEdit().returnPressed.connect(self._product_enter)
        self.count = number_box(1, 1_000_000, " шт")
        self.summa = number_box(0, 100_000_000, " ₸")
        self.payment = combo(PAYMENT_TYPES)
        self.payment.currentTextChanged.connect(self._payment_changed)
        self.customer = QLineEdit(placeholderText="Необязательно")
        self.phone = QLineEdit(placeholderText="Необязательно")
        form.addRow("Товар", self.product)
        form.addRow("Количество", self.count)
        form.addRow("Сумма продажи", self.summa)
        form.addRow("Тип оплаты", self.payment)
        form.addRow("Покупатель", self.customer)
        form.addRow("Телефон", self.phone)
        card.body.addLayout(form)
        self.submit_btn = button("Добавить в корзину", "primary", self.submit)
        card.body.addWidget(self.submit_btn)
        row = QHBoxLayout()
        self.cancel_btn = button("Отменить", None, self.table.clearSelection)
        self.remove_btn = button("Удалить из корзины", "danger", self.remove)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.remove_btn)
        card.body.addLayout(row)
        card.body.addWidget(rule())
        self.checkout_btn = button("Оформить заказ", "primary", self.checkout)
        self.checkout_btn.setProperty("size", "large")
        card.body.addWidget(self.checkout_btn)
        self.last_receipt_btn = button("Показать последний чек", "link", self.show_last_receipt)
        self.last_receipt_btn.setVisible(False)
        card.body.addWidget(self.last_receipt_btn, 0, Qt.AlignHCenter)
        self._set_mode(False)
        # фокус на таблице: сканер «печатает» в таблицу — перенаправляем символы в поле сканера
        self.table.installEventFilter(self)
        return card

    def eventFilter(self, obj, event):
        if obj is self.table and event.type() == QEvent.KeyPress and event.text().isprintable() \
                and event.text() and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            self.scan.setFocus()
            self.scan.insert(event.text())
            return True
        return super().eventFilter(obj, event)

    def _product_enter(self):
        text = self.product.currentText().strip()
        if text and self._product_id() is None and " " not in text:
            try:
                found = services.find_by_barcode(text)
            except Exception:
                found = None
            if found:
                self.product.setEditText("")
                self.on_scan(text)

    def _show_scan_status(self, text, tone="Muted"):
        self.scan_status.setObjectName(tone)
        self.scan_status.style().unpolish(self.scan_status)
        self.scan_status.style().polish(self.scan_status)
        self.scan_status.setText(text)
        self.scan_status.setVisible(bool(text))

    def on_scan(self, code):
        code = code.strip()
        self.scan.clear()
        if not code:
            return
        payment = self.payment.currentText()
        try:
            result = services.scan_to_cart(self.seller, code, payment, self.customer.text(), self.phone.text())
        except Exception as ex:
            QApplication.beep()
            self._show_scan_status("")
            show_error(self, ex)
            self.scan.setFocus()
            return
        if result.item is None:
            # цена не известна — выбираем товар в форме, сумму вводит продавец
            self.table.clearSelection()
            index = self.product.findData(result.product.id)
            if index < 0:
                self.product.addItem(result.product.name, result.product.id)
                index = self.product.count() - 1
            self.product.setCurrentIndex(index)
            self.product.lineEdit().setCursorPosition(0)
            self.count.setValue(1)
            self.summa.setValue(0)
            self._show_scan_status(f"Для «{result.product.name}» нет цены продажи. Введите сумму и нажмите "
                                   "«Добавить в корзину». Цену можно задать на «Складе».", "Warn")
            self.summa.setFocus()
            self.summa.selectAll()
            return
        item = result.item
        self._show_scan_status(f"+1  {item.nameProduct}  ·  {item.count} шт  ·  {money(item.summa)} ₸")
        self.table.clearSelection()
        self.refresh()
        for i, row in enumerate(self.model.rows):
            if row.id == item.id:
                self.table.scrollTo(self.model.index(i, 0))
                break
        self.scan.setFocus()

    def _payment_changed(self, text):
        hint = "Обязательно для «Қарыз»" if text == DEBT else "Необязательно"
        self.customer.setPlaceholderText(hint)
        self.phone.setPlaceholderText(hint)

    def _load_products(self):
        current = self.product.currentText()
        self.product.clear()
        try:
            products = services.list_products(in_stock_only=True)
        except Exception as ex:
            show_error(self, ex)
            return
        for p in products:
            self.product.addItem(f"{p.name}  (остаток {p.quantity})", p.id)
        self.product.setCurrentIndex(self.product.findText(current) if current else -1)

    def _product_id(self):
        index = self.product.findText(self.product.currentText())
        return self.product.itemData(index) if index >= 0 else None

    def _clear_form(self):
        self.product.setCurrentIndex(-1)
        self.product.setEditText("")
        self.count.setValue(1)
        self.summa.setValue(0)
        self.customer.clear()
        self.phone.clear()

    def _set_mode(self, editing):
        self.editing = editing
        self.side_title.setText("Изменить позицию" if editing else "Добавить товар")
        self.submit_btn.setText("Сохранить изменения" if editing else "Добавить в корзину")
        self.hint.setText("Измените поля и нажмите «Сохранить изменения»." if editing
                          else "Чтобы изменить позицию, выберите её в таблице.")
        self.cancel_btn.setVisible(editing)
        self.remove_btn.setVisible(editing)

    def on_show(self):
        self._load_products()
        self.refresh()
        self.scan.setFocus()

    def on_select(self, item):
        if item is None:
            if self.editing:
                self._clear_form()
            self._set_mode(False)
            return
        self._set_mode(True)
        index = self.product.findData(item.productId)
        if index < 0:  # товара уже нет в списке «в наличии» — добавим, чтобы можно было сохранить
            self.product.addItem(item.nameProduct, item.productId)
            index = self.product.count() - 1
        self.product.setCurrentIndex(index)
        self.product.lineEdit().setCursorPosition(0)
        self.count.setValue(item.count)
        self.summa.setValue(item.summa)
        self.payment.setCurrentText(item.paymentType)
        self.customer.setText(item.nameCustomer or "")
        self.phone.setText(item.phoneNumberCustomer or "")

    def after_refresh(self, rows):
        self.summary.setText(f"Итого: {money(sum(r.summa for r in rows))} ₸")
        self.checkout_btn.setEnabled(bool(rows))

    def submit(self):
        item = self.selected()
        args = (self._product_id(), self.count.value(), self.summa.value(),
                self.payment.currentText(), self.customer.text(), self.phone.text())
        try:
            if item:
                services.update_cart_item(self.seller, item.id, *args)
            else:
                services.add_to_cart(self.seller, *args)
        except Exception as ex:
            show_error(self, ex)
            return
        self.table.clearSelection()
        self._clear_form()
        self._show_scan_status("")
        self.refresh()
        self.scan.setFocus()

    def remove(self):
        item = self.selected()
        if not item:
            return
        try:
            services.remove_from_cart(self.seller, item.id)
        except Exception as ex:
            show_error(self, ex)
        self.table.clearSelection()
        self.refresh()

    def checkout(self):
        total = sum(r.summa for r in self.model.rows)
        if not ask(self, "Оформить заказ", f"Оформить заказ на {money(total)} ₸?"):
            return
        try:
            result = services.checkout(self.seller)
        except Exception as ex:
            show_error(self, ex)
            return
        text = "\n".join([f"🧾 Жаңа заказ — {self.seller}", *result.lines, f"Барлығы: {money(result.total)} ₸"])
        if result.debt_total:
            text += f"\nОның ішінде қарыз: {money(result.debt_total)} ₸"
        notify(text)
        self.table.clearSelection()
        self._clear_form()
        self._show_scan_status("")
        self.on_show()
        self.last_receipt = result.receipt
        self.last_receipt_btn.setVisible(True)
        self.show_last_receipt()

    def show_last_receipt(self):
        if self.last_receipt:
            ReceiptDialog(self.last_receipt, self).exec_()


# ====================================================================== Заказы

class OrdersPage(BasePage):
    title = "Заказы"
    date_filter = "today"
    empty_text = "За эту дату заказов нет. Снимите галочку «За дату», чтобы увидеть все."
    columns = [
        Column("Дата", lambda r: r.createAt, "datetime"),
        Column("Товар", lambda r: r.nameProduct),
        Column("Кол-во", lambda r: r.count, "int"),
        Column("Сумма", lambda r: r.summa, "money"),
        Column("Себест.", lambda r: r.sysprice, "money"),
        Column("Оплата", services.payment_label),
        Column("Покупатель", lambda r: r.nameCustomer),
        Column("Телефон", lambda r: r.phoneNumberCustomer),
        Column("Продавец", lambda r: r.fioSeller),
    ]

    def fetch(self, search, day):
        return services.list_orders(search, day)

    def bar_widgets(self):
        self.receipt_btn = button("Чек", None, self.show_receipt)
        self.receipt_btn.setToolTip("Показать и распечатать чек выбранного заказа")
        self.receipt_btn.setEnabled(False)
        return [self.receipt_btn]

    def on_select(self, order):
        self.receipt_btn.setEnabled(order is not None)

    def show_receipt(self):
        order = self.selected()
        if not order:
            return
        try:
            receipt = services.receipt_for(order.fioSeller, order.createAt, bool(order.isDebtPayment))
        except Exception as ex:
            show_error(self, ex)
            return
        ReceiptDialog(receipt, self).exec_()

    def after_refresh(self, rows):
        self.summary.setText(f"{len(rows)} шт · {money(sum(r.summa for r in rows))} ₸")


# ====================================================================== Склад

class StockPage(BasePage):
    title = "Склад"
    empty_text = "Склад пуст. Товары появляются здесь после «Прихода»."
    columns = [
        Column("Название", lambda r: r.name, min_width=190),
        Column("Остаток", lambda r: r.quantity, "int"),
        Column("Цена закуп.", lambda r: r.price, "money"),
        Column("Цена прод.", lambda r: r.salePrice, "money"),
        Column("Штрих-код", lambda r: r.barcode, min_width=128),
        Column("Описание", lambda r: r.description),  # кто и когда обновил — в карточке справа
    ]

    def muted_if(self, obj):
        return (obj.quantity or 0) <= 0

    def fetch(self, search, day):
        return services.list_products(search)

    def after_refresh(self, rows):
        worth = sum((r.quantity or 0) * (r.price or 0) for r in rows)
        self.summary.setText(f"{len(rows)} товаров · {money(worth)} ₸")

    def build_side(self):
        card = self.side_card("Изменить товар")
        self.selected_name = WrapLabel("Выберите товар в таблице", "Muted")
        card.body.addWidget(self.selected_name)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.quantity = number_box(0, 1_000_000, " шт")
        self.price = number_box(0, 100_000_000, " ₸")
        self.sale_price = number_box(0, 100_000_000, " ₸")
        self.sale_price.setSpecialValueText("не задана")
        self.sale_price.setToolTip("Цена за 1 шт, которую ставит сканер в корзине. "
                                   "Если не задана — берётся цена из последней продажи.")
        self.barcode = QLineEdit(placeholderText="Отсканируйте или введите")
        self.barcode.setClearButtonEnabled(True)
        self.description = QLineEdit()
        form.addRow("Остаток", self.quantity)
        form.addRow("Цена закуп.", self.price)
        form.addRow("Цена продажи", self.sale_price)
        form.addRow("Штрих-код", self.barcode)
        form.addRow("Описание", self.description)
        card.body.addLayout(form)
        self.save_btn = button("Сохранить изменения", "primary", self.save)
        card.body.addWidget(self.save_btn)
        row = QHBoxLayout()
        self.make_code_btn = button("Создать свой код", None, self.make_code)
        self.make_code_btn.setToolTip("Для товара без заводского штрих-кода: касса создаст код, "
                                      "который можно напечатать на этикетке")
        self.labels_btn = button("Печать этикеток", None, self.print_labels)
        row.addWidget(self.make_code_btn)
        row.addWidget(self.labels_btn)
        card.body.addLayout(row)
        card.body.addWidget(label("Новый товар добавляется через «Приход».", "Muted"))
        return card

    def on_select(self, obj):
        for w in (self.quantity, self.price, self.sale_price, self.barcode, self.description, self.save_btn):
            w.setEnabled(obj is not None)
        self.make_code_btn.setEnabled(obj is not None and not obj.barcode)
        printable = obj is not None and is_ean13(obj.barcode or "")
        self.labels_btn.setEnabled(printable)
        self.labels_btn.setToolTip("" if printable or obj is None or not obj.barcode
                                   else "Печать — только для кодов EAN-13 (13 цифр). "
                                        "У заводского товара код уже есть на упаковке.")
        if obj is None:
            self.selected_name.setText("Выберите товар в таблице")
            return
        updated = format_datetime(obj.updateAt or "")
        self.selected_name.setText(f"{obj.name}\nОбновил: {obj.updatedBy}, {updated}" if obj.updatedBy
                                   else obj.name)
        self.quantity.setValue(obj.quantity or 0)
        self.price.setValue(obj.price or 0)
        self.sale_price.setValue(obj.salePrice or 0)
        self.barcode.setText(obj.barcode or "")
        self.description.setText(obj.description or "")

    def make_code(self):
        obj = self.selected()
        if not obj:
            return
        try:
            product = services.generate_barcode(self.seller, obj.id)
        except Exception as ex:
            show_error(self, ex)
            return
        self.refresh()
        LabelDialog(product, self).exec_()

    def print_labels(self):
        obj = self.selected()
        if obj and is_ean13(obj.barcode or ""):
            LabelDialog(obj, self).exec_()

    def save(self):
        obj = self.selected()
        if not obj or not ask(self, "Изменить товар", f"Сохранить изменения для «{obj.name}»?"):
            return
        try:
            product, (old_qty, old_price) = services.update_product(
                self.seller, obj.id, self.quantity.value(), self.price.value(), self.description.text(),
                sale_price=self.sale_price.value(), barcode=self.barcode.text())
        except Exception as ex:
            show_error(self, ex)
            return
        notify(f"✏️ Склад өзгертілді — {self.seller}\n{product.name}: қалдық {old_qty} → {product.quantity}, "
               f"баға {money(old_price)} → {money(product.price)}")
        self.refresh()


# ====================================================================== Приход

class ReceivePage(BasePage):
    title = "Приход товара"
    date_filter = "all"
    empty_text = "Приходов нет. Заполните форму справа, чтобы добавить товар на склад."
    columns = [
        Column("Дата", lambda r: r.createAt, "datetime"),
        Column("Название", lambda r: r.name),
        Column("Кол-во", lambda r: r.quantity, "int"),
        Column("Цена закуп.", lambda r: r.price, "money"),
        Column("Описание", lambda r: r.description),
        Column("Принял", lambda r: r.createdBy),
    ]

    def fetch(self, search, day):
        return services.list_receipts(search, day)

    def build_side(self):
        card = self.side_card("Новый приход")
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.barcode = QLineEdit(placeholderText="Необязательно — отсканируйте")
        self.barcode.setClearButtonEnabled(True)
        self.barcode.returnPressed.connect(self._barcode_entered)
        self.name = combo(editable=True, placeholder="Новое или существующее название")
        self.name.currentTextChanged.connect(self._name_changed)
        self.name.lineEdit().returnPressed.connect(self._name_enter)
        self.quantity = number_box(1, 1_000_000, " шт")
        self.price = number_box(0, 100_000_000, " ₸")
        self.description = QLineEdit(placeholderText="Необязательно")
        form.addRow("Штрих-код", self.barcode)
        form.addRow("Название", self.name)
        form.addRow("Количество", self.quantity)
        form.addRow("Цена закуп.", self.price)
        form.addRow("Описание", self.description)
        card.body.addLayout(form)
        self.stock_hint = label("", "Muted")
        card.body.addWidget(self.stock_hint)
        card.body.addWidget(button("Добавить на склад", "primary", self.add))
        return card

    def _barcode_entered(self):
        """Скан в поле «Штрих-код»: известный товар — подставляем название, новый — вводят название."""
        try:
            product = services.find_by_barcode(self.barcode.text())
        except Exception as ex:
            show_error(self, ex)
            return
        if product:
            self.name.setEditText(product.name)
            self.quantity.setFocus()
            self.quantity.selectAll()
        else:
            self.stock_hint.setText("Новый штрих-код. Введите название — код запишется этому товару.")
            self.name.setFocus()

    def _name_enter(self):
        """Если штрих-код отсканировали в поле «Название» — переносим его в поле «Штрих-код»."""
        text = self.name.currentText().strip()
        if text and " " not in text and len(text) >= 8 and text.isalnum() and not services.find_product(text):
            self.name.setEditText("")
            self.barcode.setText(text)
            self._barcode_entered()

    def _name_changed(self, text):
        try:
            product = services.find_product(text) if text.strip() else None
        except Exception:
            product = None
        if product:
            self.stock_hint.setText(f"Есть на складе: {product.quantity or 0} шт. Количество прибавится.")
            self.price.setValue(product.price or 0)
            self.description.setPlaceholderText(product.description or "Необязательно")
        else:
            self.stock_hint.setText("Новый товар будет создан на складе." if text.strip() else "")
            self.description.setPlaceholderText("Необязательно")

    def on_show(self):
        current = self.name.currentText()
        self.name.blockSignals(True)
        self.name.clear()
        try:
            self.name.addItems(services.product_names())
        except Exception as ex:
            show_error(self, ex)
        self.name.setEditText(current)
        self.name.blockSignals(False)
        self.refresh()

    def add(self):
        name = self.name.currentText().strip()
        try:
            product = services.receive_product(self.seller, name, self.quantity.value(),
                                               self.price.value(), self.description.text(), self.barcode.text())
        except Exception as ex:
            show_error(self, ex)
            return
        notify(f"📥 Приход — {self.seller}\n{product.name}: +{self.quantity.value()} шт "
               f"по {money(self.price.value())} ₸ (қалдық {product.quantity})")
        self.name.setEditText("")
        self.barcode.clear()
        self.quantity.setValue(1)
        self.price.setValue(0)
        self.description.clear()
        self.on_show()
        self.barcode.setFocus()


# ====================================================================== Долги

class DebtsPage(BasePage):
    title = "Долги"
    empty_text = "Долгов нет."
    columns = [
        Column("Дата", lambda r: r.createAt, "datetime"),
        Column("Покупатель", lambda r: r.nameCustomer),
        Column("Телефон", lambda r: r.phoneNumberCustomer),
        Column("Товар", lambda r: r.nameProduct),
        Column("Кол-во", lambda r: r.count, "int"),
        Column("Долг", lambda r: r.summa, "money"),
        Column("Продавец", lambda r: r.fioSeller),
    ]

    def fetch(self, search, day):
        return services.list_debts(search)

    def after_refresh(self, rows):
        self.summary.setText(f"Всего: {money(sum(r.summa for r in rows))} ₸")

    def build_side(self):
        card = self.side_card("Оплата долга")
        self.info = WrapLabel("Выберите долг в таблице", "Muted")
        card.body.addWidget(self.info)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.amount = number_box(0, 100_000_000, " ₸")
        self.method = combo(DEBT_PAY_TYPES)
        form.addRow("Сумма оплаты", self.amount)
        form.addRow("Как оплачено", self.method)
        card.body.addLayout(form)
        row = QHBoxLayout()
        self.full_btn = button("Вся сумма", None, lambda: self.amount.setValue(self.selected().summa))
        self.pay_btn = button("Принять оплату", "primary", self.pay)
        row.addWidget(self.full_btn)
        row.addWidget(self.pay_btn)
        card.body.addLayout(row)
        return card

    def on_select(self, obj):
        for w in (self.amount, self.method, self.full_btn, self.pay_btn):
            w.setEnabled(obj is not None)
        if obj is None:
            self.info.setText("Выберите долг в таблице")
            return
        self.info.setText(f"{obj.nameCustomer} ({obj.phoneNumberCustomer})\n"
                          f"{obj.nameProduct} × {obj.count}\nОстаток долга: {money(obj.summa)} ₸")
        self.amount.setMaximum(obj.summa)
        self.amount.setValue(obj.summa)

    def pay(self):
        debt = self.selected()
        amount = self.amount.value()
        method = self.method.currentText()
        if not debt or not ask(self, "Оплата долга",
                               f"Принять {money(amount)} ₸ ({method}) от {debt.nameCustomer}?"):
            return
        try:
            remaining = services.pay_debt(self.seller, debt.id, amount, method)
        except Exception as ex:
            show_error(self, ex)
            return
        notify(f"💳 Қарыз өтелді — {self.seller}\n{debt.nameCustomer}: {money(amount)} ₸ ({method}), "
               f"қалды {money(remaining)} ₸")
        msg = "Долг полностью погашен" if remaining == 0 else f"Оплата принята. Остаток: {money(remaining)} ₸"
        QMessageBox.information(self, "Готово", msg)
        self.refresh()


# ====================================================================== Расходы

class ExpensesPage(BasePage):
    title = "Расходы"
    date_filter = "today"
    empty_text = "За эту дату расходов нет."
    columns = [
        Column("Дата", lambda r: r.createAt, "datetime"),
        Column("Название", lambda r: r.name),
        Column("Сумма", lambda r: r.summa, "money"),
        Column("Описание", lambda r: r.description),
        Column("Кто", lambda r: r.createdBy),
    ]

    def fetch(self, search, day):
        return services.list_expenses(search, day)

    def after_refresh(self, rows):
        self.summary.setText(f"Итого: {money(sum(r.summa for r in rows))} ₸")

    def build_side(self):
        card = self.side_card("Новый расход")
        self.hint = WrapLabel("Чтобы изменить или удалить расход, выберите его в таблице.", "Muted")
        card.body.addWidget(self.hint)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.name = QLineEdit(placeholderText="Например: аренда, доставка")
        self.amount = number_box(0, 100_000_000, " ₸")
        self.description = QLineEdit(placeholderText="Необязательно")
        form.addRow("Название", self.name)
        form.addRow("Сумма", self.amount)
        form.addRow("Описание", self.description)
        card.body.addLayout(form)
        self.save_btn = button("Добавить расход", "primary", self.save)
        card.body.addWidget(self.save_btn)
        row = QHBoxLayout()
        self.cancel_btn = button("Отменить", None, self.table.clearSelection)
        row.addWidget(self.cancel_btn)
        self.delete_btn = button("Удалить", "danger", self.delete)
        row.addWidget(self.delete_btn)
        card.body.addLayout(row)
        return card

    def on_select(self, obj):
        for w in (self.delete_btn, self.cancel_btn):
            w.setVisible(obj is not None)
        self.hint.setText("Измените поля и нажмите «Сохранить изменения»." if obj
                          else "Чтобы изменить или удалить расход, выберите его в таблице.")
        self.save_btn.setText("Сохранить изменения" if obj else "Добавить расход")
        self.side_title.setText("Изменить расход" if obj else "Новый расход")
        self.name.setText(obj.name if obj else "")
        self.amount.setValue(obj.summa if obj else 0)
        self.description.setText((obj.description or "") if obj else "")

    def save(self):
        obj = self.selected()
        try:
            expense = services.save_expense(self.seller, obj.id if obj else None, self.name.text(),
                                            self.amount.value(), self.description.text())
        except Exception as ex:
            show_error(self, ex)
            return
        action = "өзгертілді" if obj else "қосылды"
        notify(f"💸 Шығын {action} — {self.seller}\n{expense.name}: {money(expense.summa)} ₸")
        self.table.clearSelection()
        self.refresh()

    def delete(self):
        obj = self.selected()
        if not obj or not ask(self, "Удалить расход", f"Удалить «{obj.name}» на {money(obj.summa)} ₸?"):
            return
        try:
            services.delete_expense(obj.id)
        except Exception as ex:
            show_error(self, ex)
            return
        notify(f"🗑 Шығын өшірілді — {self.seller}\n{obj.name}: {money(obj.summa)} ₸")
        self.refresh()


# ====================================================================== Отчёт

class StatCard(Card):
    def __init__(self, title):
        super().__init__()
        self.body.addWidget(label(title, "StatTitle"))
        self.value = label("0 ₸", "StatValue")
        self.body.addWidget(self.value)

    def set(self, amount, tone=None):
        self.value.setText(f"{money(amount)} ₸")
        self.value.setProperty("tone", tone or "")
        self.value.style().unpolish(self.value)
        self.value.style().polish(self.value)


class ReportPage(QWidget):
    def __init__(self, main):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 24)
        root.setSpacing(16)
        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(label("Отчёт за день", "PageTitle"))
        header.addStretch()
        self.day = date_edit()
        self.day.dateChanged.connect(self.on_show)
        header.addWidget(self.day)
        header.addWidget(button("Отправить в Telegram", "primary", self.send))
        root.addLayout(header)

        names = [("net", "Чистая прибыль"), ("revenue", "Выручка"), ("cost", "Себестоимость"),
                 ("expenses", "Расходы"), ("cash", "Наличка"), ("kaspi", "Kaspi"), ("mixed", "Аралас"),
                 ("paid", "Оплаты долгов"), ("gross", "Валовая прибыль"), ("new_debts", "Новые долги за день"),
                 ("debts_total", "Всего долгов")]
        self.cards = {}
        grid = QGridLayout()
        grid.setSpacing(14)
        for i, (key, title) in enumerate(names):
            self.cards[key] = StatCard(title)
            grid.addWidget(self.cards[key], i // 4, i % 4)
        for col in range(4):
            grid.setColumnStretch(col, 1)
        root.addLayout(grid)
        root.addStretch()
        self.report = None

    def on_show(self):
        try:
            r = self.report = services.day_report(self.day.date().toPyDate())
        except Exception as ex:
            show_error(self, ex)
            return
        t = r.by_type
        self.cards["net"].set(r.net, "good" if r.net >= 0 else "bad")
        self.cards["revenue"].set(r.revenue)
        self.cards["cost"].set(r.cost)
        self.cards["expenses"].set(r.expenses)
        self.cards["cash"].set(t.get(services.CASH))
        self.cards["kaspi"].set(t.get(services.KASPI))
        self.cards["mixed"].set(t.get(services.MIXED))
        self.cards["paid"].set(r.debt_paid)
        self.cards["gross"].set(r.gross)
        self.cards["new_debts"].set(r.new_debts, "bad" if r.new_debts else None)
        self.cards["debts_total"].set(r.debts_total)

    def send(self):
        if not self.report:
            return
        if not config.BOT_TOKEN:
            QMessageBox.warning(self, "Telegram", "BOT_TOKEN не задан в файле .env")
            return
        notify(services.format_report(self.report, html=False))
        QMessageBox.information(self, "Telegram", "Отчёт отправлен подписчикам")


# ====================================================================== окно

class MainWindow(QMainWindow):
    PAGES = [("Корзина", CartPage), ("Заказы", OrdersPage), ("Склад", StockPage), ("Приход", ReceivePage),
             ("Долги", DebtsPage), ("Расходы", ExpensesPage), ("Отчёт", ReportPage)]

    def __init__(self, seller):
        super().__init__()
        self.seller = seller
        self.setWindowTitle(f"Ағаш базар — {seller.name}")
        self.setWindowIcon(QIcon(str(config.BASE_DIR / "images" / "icon.png")))
        self.resize(1320, 780)

        root = QWidget(objectName="Root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QWidget(objectName="Sidebar")
        sidebar.setAttribute(Qt.WA_StyledBackground, True)
        sidebar.setFixedWidth(220)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 16)
        side.addWidget(label("Ағаш базар", "Brand"))
        info = label(f"{seller.name} · {seller.nameShop}", "UserInfo")
        info.setWordWrap(True)
        side.addWidget(info)

        self.nav = QListWidget(objectName="Nav")
        self.nav.setCursor(Qt.PointingHandCursor)
        self.stack = QStackedWidget()
        for title, page_class in self.PAGES:
            self.nav.addItem(title)
            self.stack.addWidget(page_class(self))
        self.nav.currentRowChanged.connect(self.open_page)
        side.addWidget(self.nav, 1)
        for text, slot in (("Помощь", self.show_help), ("Выйти", self.close)):
            btn = QPushButton(text, objectName="SideButton")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(slot)
            side.addWidget(btn)

        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.nav.setCurrentRow(0)

    def open_page(self, index):
        self.stack.setCurrentIndex(index)
        self.stack.widget(index).on_show()

    def show_help(self):
        QMessageBox.information(self, "Помощь", config.HELP_TEXT)

    def closeEvent(self, event):
        if not ask(self, "Выход", "Закрыть кассу?"):
            event.ignore()
            return
        thread = notify(f"🚪 {self.seller.name} кассадан шықты")
        if thread:
            thread.join(timeout=3)
        event.accept()
