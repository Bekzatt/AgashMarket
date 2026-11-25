"""Бизнес-логика кассы. Окна и бот вызывают только эти функции.

Все запросы параметризованы (через SQLAlchemy), каждая операция — одна транзакция.
"""
import hashlib
import hmac
import secrets
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from html import escape

from sqlalchemy import String, cast, func, or_, select

from model.db import session_scope
from model.models import Cart, Debt, Event, Expense, Order, Product, Seller, TelegramUser, TempProduct

CASH, KASPI, MIXED, DEBT, PAID = "Наличка", "Каспи", "Аралас", "Қарыз", "Погашен"
PAYMENT_TYPES = [CASH, KASPI, MIXED, DEBT]
DEBT_PAY_TYPES = [CASH, KASPI, MIXED]


class AppError(Exception):
    """Понятная пользователю ошибка (неверный ввод, нет товара и т.п.)."""


# ---------------------------------------------------------------- helpers

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def day_str(day=None) -> str:
    if day is None:
        day = date.today()
    return day if isinstance(day, str) else day.strftime("%Y-%m-%d")


def money(value) -> str:
    return f"{int(value or 0):,}".replace(",", " ")


def _text(value, title, required=True, max_len=200) -> str:
    value = (value or "").strip()
    if required and not value:
        raise AppError(f"Заполните поле «{title}»")
    if len(value) > max_len:
        raise AppError(f"«{title}»: не больше {max_len} символов")
    return value


def _int(value, title, min_value=0) -> int:
    try:
        number = int(str(value).replace(" ", ""))
    except (TypeError, ValueError):
        raise AppError(f"«{title}»: введите целое число") from None
    if number < min_value:
        raise AppError(f"«{title}» должно быть не меньше {min_value}")
    return number


def _search(query, columns, text):
    text = (text or "").strip()
    if not text:
        return query
    pattern = f"%{text}%"
    return query.where(or_(*[cast(c, String).ilike(pattern) for c in columns]))


def _on_day(query, column, day):
    return query.where(column.like(f"{day_str(day)}%")) if day else query


# ---------------------------------------------------------------- продавцы

_PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest}"


def _check_password(password: str, stored: str):
    """Возвращает (совпал, это_старый_пароль_открытым_текстом)."""
    if stored.startswith("pbkdf2_sha256$"):
        _, iterations, salt, digest = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(calc, digest), False
    return hmac.compare_digest(password, stored), True


def register_seller(shop: str, name: str, password: str, password2: str) -> None:
    shop = _text(shop, "Название магазина")
    name = _text(name, "Логин")
    if len(password or "") < 4:
        raise AppError("Пароль должен быть не короче 4 символов")
    if password != password2:
        raise AppError("Пароли не совпадают")
    with session_scope() as s:
        if s.scalar(select(Seller.id).where(Seller.name == name)):
            raise AppError(f"Пользователь «{name}» уже существует")
        s.add(Seller(nameShop=shop, name=name, password=hash_password(password)))


def login(name: str, password: str):
    name = (name or "").strip()
    if not name or not password:
        return None
    with session_scope() as s:
        for seller in s.scalars(select(Seller).where(Seller.name == name)):
            ok, legacy = _check_password(password, seller.password)
            if ok:
                if legacy:  # старый пароль открытым текстом — сразу заменяем на хэш
                    seller.password = hash_password(password)
                return seller
    return None


# ---------------------------------------------------------------- склад и приход

def list_products(search="", in_stock_only=False):
    with session_scope() as s:
        q = select(Product).order_by(Product.name)
        if in_stock_only:
            q = q.where(Product.quantity > 0)
        q = _search(q, [Product.name, Product.description, Product.barcode], search)
        return list(s.scalars(q))


def product_names():
    with session_scope() as s:
        return list(s.scalars(select(Product.name).order_by(Product.name)))


def find_product(name: str):
    with session_scope() as s:
        return s.scalar(select(Product).where(Product.name == (name or "").strip()))


def list_receipts(search="", day=None):
    with session_scope() as s:
        q = select(TempProduct).order_by(TempProduct.id.desc())
        q = _search(q, [TempProduct.name, TempProduct.description, TempProduct.createdBy], search)
        q = _on_day(q, TempProduct.createAt, day)
        return list(s.scalars(q))


def receive_product(seller: str, name, quantity, price, description="", barcode="") -> Product:
    """Приход товара: запись в историю + прибавить количество на складе (или создать товар).
    barcode — необязательно: заводской штрих-код, запишется товару, если у него кода ещё нет."""
    name = _text(name, "Название")
    quantity = _int(quantity, "Количество", 1)
    price = _int(price, "Цена")
    description = _text(description, "Описание", required=False, max_len=500)
    barcode = normalize_barcode(barcode)
    ts = now_str()
    with session_scope() as s:
        existing = s.scalar(select(Product).where(Product.name == name))
        if barcode:
            _check_barcode_free(s, barcode, existing.id if existing else None)
            if existing and existing.barcode and existing.barcode != barcode:
                raise AppError(f"У товара «{name}» уже есть другой штрих-код: {existing.barcode}. "
                               "Изменить его можно на «Складе».")
        s.add(TempProduct(name=name, quantity=quantity, price=price, description=description,
                          isAdd=True, updateAt=ts, updatedBy=seller, createAt=ts, createdBy=seller))
        product = s.scalar(select(Product).where(Product.name == name).with_for_update())
        if product:
            product.quantity = (product.quantity or 0) + quantity
            product.price = price
            if description:
                product.description = description
            if barcode:
                product.barcode = barcode
            product.updateAt, product.updatedBy = ts, seller
        else:
            product = Product(name=name, quantity=quantity, price=price, description=description,
                              barcode=barcode or None,
                              updateAt=ts, updatedBy=seller, createAt=ts, createdBy=seller)
            s.add(product)
        s.flush()
        return product


def update_product(seller: str, product_id: int, quantity, price, description="", sale_price=None,
                   barcode=None):
    """sale_price: None — не менять, 0 — убрать. barcode: None — не менять, "" — убрать."""
    quantity = _int(quantity, "Количество")
    price = _int(price, "Цена")
    description = _text(description, "Описание", required=False, max_len=500)
    if sale_price is not None:
        sale_price = _int(sale_price, "Цена продажи")
    if barcode is not None:
        barcode = normalize_barcode(barcode)
    with session_scope() as s:
        product = s.get(Product, product_id, with_for_update=True)
        if not product:
            raise AppError("Товар не найден")
        old = (product.quantity, product.price)
        product.quantity, product.price, product.description = quantity, price, description
        if sale_price is not None:
            product.salePrice = sale_price or None
        if barcode is not None:
            if barcode:
                _check_barcode_free(s, barcode, product.id)
            product.barcode = barcode or None
        product.updateAt, product.updatedBy = now_str(), seller
        return product, old


# ---------------------------------------------------------------- штрих-коды

STORE_PREFIX = "29"  # EAN-13 с 20–29 — внутренние коды магазина, с заводскими не совпадают


def ean13_check_digit(first12: str) -> str:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return str((10 - total % 10) % 10)


def is_ean13(code: str) -> bool:
    return bool(code) and len(code) == 13 and code.isdigit() and ean13_check_digit(code[:12]) == code[12]


def normalize_barcode(code) -> str:
    """Убирает пробелы и невидимые символы, которые иногда добавляет сканер."""
    code = "".join(ch for ch in str(code or "") if ch.isprintable() and not ch.isspace())
    if code and not (3 <= len(code) <= 64 and code.isascii()):
        raise AppError("Штрих-код должен состоять из латинских букв и цифр (3–64 символа). "
                       "Если сканер вводит русские буквы — переключите раскладку на английскую.")
    return code


def _check_barcode_free(s, code: str, product_id) -> None:
    other = s.scalar(select(Product).where(Product.barcode == code, Product.id != (product_id or -1)))
    if other:
        raise AppError(f"Штрих-код {code} уже присвоен товару «{other.name}»")


def find_by_barcode(code):
    code = normalize_barcode(code)
    if not code:
        return None
    with session_scope() as s:
        return s.scalar(select(Product).where(Product.barcode == code))


def store_barcode(product_id: int) -> str:
    first12 = f"{STORE_PREFIX}{product_id:010d}"
    return first12 + ean13_check_digit(first12)


def generate_barcode(seller: str, product_id: int) -> Product:
    """Свой штрих-код для товара без заводского (печатается на этикетке)."""
    with session_scope() as s:
        product = s.get(Product, product_id, with_for_update=True)
        if not product:
            raise AppError("Товар не найден")
        if product.barcode:
            raise AppError(f"У товара уже есть штрих-код {product.barcode}")
        code = store_barcode(product.id)
        _check_barcode_free(s, code, product.id)
        product.barcode = code
        product.updateAt, product.updatedBy = now_str(), seller
        return product


def unit_sale_price(s, product: Product):
    """Цена 1 шт для сканера: «Цена продажи» товара, иначе цена из последней продажи."""
    if product.salePrice:
        return product.salePrice
    last = s.scalar(select(Order).where(Order.productId == product.id, Order.isDebtPayment.isnot(True),
                                        Order.count > 0, Order.summa > 0).order_by(Order.id.desc()).limit(1))
    return round(last.summa / last.count) if last else None


@dataclass
class ScanResult:
    product: Product
    item: object = None      # позиция корзины; None — цена неизвестна, продавец вводит сумму сам
    merged: bool = False     # True — прибавили к уже имеющейся позиции


def scan_to_cart(seller: str, code, payment_type=CASH, customer="", phone="") -> ScanResult:
    """Скан в корзине: +1 шт товара. Повторный скан того же товара увеличивает количество."""
    code = normalize_barcode(code)
    if not code:
        raise AppError("Пустой штрих-код")
    with session_scope() as s:
        product = s.scalar(select(Product).where(Product.barcode == code))
        if not product:
            raise AppError(f"Товар со штрих-кодом {code} не найден.\n"
                           "Присвойте код товару на «Складе» или при «Приходе».")
        price = unit_sale_price(s, product)
        if price is None:
            return ScanResult(product)
        _, _, customer, phone = _cart_input(product.id, 1, price, payment_type, customer, phone)
        item = s.scalar(select(Cart).where(
            Cart.fioSeller == seller, Cart.productId == product.id, Cart.paymentType == payment_type,
            Cart.nameCustomer == customer).order_by(Cart.id.desc()).limit(1))
        if item:
            _check_stock(s, product, item.count + 1, already_in_this_item=item.count)
            item.count += 1
            item.summa += price
            item.sysprice = item.count * product.price
            return ScanResult(product, item, merged=True)
        _check_stock(s, product, 1)
        item = Cart(nameProduct=product.name, count=1, summa=price, sysprice=product.price,
                    nameCustomer=customer, phoneNumberCustomer=phone, paymentType=payment_type,
                    fioSeller=seller, createAt=now_str(), productId=product.id)
        s.add(item)
        s.flush()
        return ScanResult(product, item)


# ---------------------------------------------------------------- корзина и заказы

def list_cart(seller: str):
    with session_scope() as s:
        return list(s.scalars(select(Cart).where(Cart.fioSeller == seller).order_by(Cart.id)))


def cart_total(seller: str) -> int:
    with session_scope() as s:
        return int(s.scalar(select(func.coalesce(func.sum(Cart.summa), 0)).where(Cart.fioSeller == seller)))


def available_quantity(s, product: Product) -> int:
    reserved = s.scalar(select(func.coalesce(func.sum(Cart.count), 0)).where(Cart.productId == product.id))
    return (product.quantity or 0) - int(reserved)


def _cart_input(product_id, count, summa, payment_type, customer, phone):
    if product_id is None:
        raise AppError("Выберите товар")
    count = _int(count, "Количество", 1)
    summa = _int(summa, "Сумма")
    if payment_type not in PAYMENT_TYPES:
        raise AppError("Выберите тип оплаты")
    required = payment_type == DEBT  # для долга покупатель обязателен
    customer = _text(customer, "Имя покупателя", required=required)
    phone = _text(phone, "Телефон покупателя", required=required, max_len=30)
    return count, summa, customer, phone


def _check_stock(s, product, count, already_in_this_item=0):
    available = available_quantity(s, product) + already_in_this_item
    if count > available:
        raise AppError(f"Не хватает товара «{product.name}»: доступно {available} шт "
                       f"(на складе {product.quantity or 0}, остальное уже в корзинах)")


def add_to_cart(seller: str, product_id, count, summa, payment_type, customer="", phone="") -> Cart:
    count, summa, customer, phone = _cart_input(product_id, count, summa, payment_type, customer, phone)
    with session_scope() as s:
        product = s.get(Product, product_id)
        if not product:
            raise AppError("Товар не найден на складе")
        _check_stock(s, product, count)
        item = Cart(nameProduct=product.name, count=count, summa=summa, sysprice=count * product.price,
                    nameCustomer=customer, phoneNumberCustomer=phone, paymentType=payment_type,
                    fioSeller=seller, createAt=now_str(), productId=product.id)
        s.add(item)
        s.flush()
        return item


def update_cart_item(seller: str, cart_id: int, product_id, count, summa, payment_type,
                     customer="", phone="") -> Cart:
    """Изменить позицию в корзине (товар, количество, сумму, оплату, покупателя)."""
    count, summa, customer, phone = _cart_input(product_id, count, summa, payment_type, customer, phone)
    with session_scope() as s:
        item = s.get(Cart, cart_id)
        if not item or item.fioSeller != seller:
            raise AppError("Позиция не найдена в вашей корзине")
        product = s.get(Product, product_id)
        if not product:
            raise AppError("Товар не найден на складе")
        _check_stock(s, product, count, already_in_this_item=item.count if item.productId == product.id else 0)
        item.nameProduct, item.productId = product.name, product.id
        item.count, item.summa, item.sysprice = count, summa, count * product.price
        item.paymentType, item.nameCustomer, item.phoneNumberCustomer = payment_type, customer, phone
        return item


def remove_from_cart(seller: str, cart_id: int) -> None:
    with session_scope() as s:
        item = s.get(Cart, cart_id)
        if not item or item.fioSeller != seller:
            raise AppError("Позиция не найдена в вашей корзине")
        s.delete(item)


@dataclass
class ReceiptLine:
    name: str
    count: int
    summa: int
    payment: str
    customer: str = ""
    phone: str = ""
    debt_payment: bool = False

    @property
    def price(self) -> int:
        return round(self.summa / self.count) if self.count else self.summa


@dataclass
class Receipt:
    created: str
    seller: str
    shop: str
    lines: list = field(default_factory=list)

    @property
    def number(self) -> str:
        c = self.created  # 2026-11-25 11:57:41 → 251126-115741
        return f"{c[8:10]}{c[5:7]}{c[2:4]}-{c[11:13]}{c[14:16]}{c[17:19]}"

    @property
    def total(self) -> int:
        return sum(line.summa for line in self.lines)

    @property
    def by_type(self) -> dict:
        totals = {}
        for line in self.lines:
            totals[line.payment] = totals.get(line.payment, 0) + line.summa
        return totals

    @property
    def debtors(self) -> list:
        seen = []
        for line in self.lines:
            if line.payment == DEBT and (line.customer, line.phone) not in seen:
                seen.append((line.customer, line.phone))
        return seen


def _receipt(s, seller: str, created: str, rows) -> Receipt:
    shop = s.scalar(select(Seller.nameShop).where(Seller.name == seller)) or ""
    lines = [ReceiptLine(r.nameProduct, r.count, r.summa, r.paymentType, r.nameCustomer or "",
                         r.phoneNumberCustomer or "", bool(getattr(r, "isDebtPayment", False)))
             for r in rows]
    return Receipt(created=created, seller=seller, shop=shop, lines=lines)


def receipt_for(seller: str, created: str, debt_payment: bool = False) -> Receipt:
    """Чек заново: покупки (заказы + долги) или оплаты долгов этого продавца в ту же секунду."""
    with session_scope() as s:
        kind = Order.isDebtPayment.is_(True) if debt_payment else or_(Order.isDebtPayment.is_(None),
                                                                      Order.isDebtPayment == False)  # noqa: E712
        rows = list(s.scalars(select(Order).where(Order.fioSeller == seller, Order.createAt == created, kind)
                              .order_by(Order.id)))
        if not debt_payment:
            rows += list(s.scalars(select(Debt).where(Debt.fioSeller == seller, Debt.createAt == created)
                                   .order_by(Debt.id)))
        if not rows:
            raise AppError("Не удалось найти покупки для этого чека")
        return _receipt(s, seller, created, rows)


@dataclass
class CheckoutResult:
    total: int
    debt_total: int
    lines: list = field(default_factory=list)
    receipt: Receipt = None


def checkout(seller: str) -> CheckoutResult:
    """Корзина продавца → заказы/долги, списание со склада. Всё или ничего."""
    with session_scope() as s:
        items = list(s.scalars(select(Cart).where(Cart.fioSeller == seller).order_by(Cart.id)))
        if not items:
            raise AppError("Корзина пуста")
        need = defaultdict(int)
        for it in items:
            need[it.productId] += it.count
        products = {p.id: p for p in s.scalars(select(Product).where(Product.id.in_(list(need))).with_for_update())}
        for pid, count in need.items():
            product = products.get(pid)
            if not product:
                raise AppError(f"Товар (id {pid}) удалён со склада")
            if (product.quantity or 0) < count:
                raise AppError(f"На складе «{product.name}» осталось {product.quantity or 0} шт, а нужно {count}")
        ts = now_str()
        result = CheckoutResult(total=0, debt_total=0)
        result.receipt = _receipt(s, seller, ts, items)
        for it in items:
            fields = it.sale_fields() | {"createAt": ts}
            s.add(Debt(**fields) if it.paymentType == DEBT else Order(**fields, isDebtPayment=False))
            result.total += it.summa
            if it.paymentType == DEBT:
                result.debt_total += it.summa
            result.lines.append(f"{it.nameProduct} × {it.count} = {money(it.summa)} ({it.paymentType})")
            s.delete(it)
        for pid, count in need.items():
            products[pid].quantity -= count
            products[pid].updateAt, products[pid].updatedBy = ts, seller
        return result


def list_orders(search="", day=None):
    with session_scope() as s:
        q = select(Order).order_by(Order.id.desc())
        q = _search(q, [Order.nameProduct, Order.nameCustomer, Order.phoneNumberCustomer,
                        Order.paymentType, Order.fioSeller], search)
        return list(s.scalars(_on_day(q, Order.createAt, day)))


# ---------------------------------------------------------------- долги

def list_debts(search=""):
    with session_scope() as s:
        q = select(Debt).where(Debt.summa > 0).order_by(Debt.id.desc())
        q = _search(q, [Debt.nameProduct, Debt.nameCustomer, Debt.phoneNumberCustomer], search)
        return list(s.scalars(q))


def payment_label(order) -> str:
    """Как показывать тип оплаты заказа: «Каспи (долг)» для оплаты долга."""
    if getattr(order, "isDebtPayment", False) and order.paymentType != PAID:
        return f"{order.paymentType} (долг)"
    return order.paymentType


def pay_debt(seller: str, debt_id: int, amount, method: str = CASH) -> int:
    """Принять оплату долга (можно частично) наличными/Каспи/смешанно. Возвращает остаток долга."""
    amount = _int(amount, "Сумма оплаты", 1)
    if method not in DEBT_PAY_TYPES:
        raise AppError("Выберите, как оплачен долг")
    with session_scope() as s:
        debt = s.get(Debt, debt_id, with_for_update=True)
        if not debt or debt.summa <= 0:
            raise AppError("Долг не найден или уже погашен")
        if amount > debt.summa:
            raise AppError(f"Сумма больше долга ({money(debt.summa)})")
        fully = amount == debt.summa
        # себестоимость списываем пропорционально оплаченной части
        cost_part = debt.sysprice if fully else round(debt.sysprice * amount / debt.summa)
        s.add(Order(nameProduct=debt.nameProduct, count=debt.count if fully else 0, summa=amount,
                    sysprice=cost_part, nameCustomer=debt.nameCustomer,
                    phoneNumberCustomer=debt.phoneNumberCustomer, paymentType=method, isDebtPayment=True,
                    fioSeller=seller, createAt=now_str(), productId=debt.productId))
        if fully:
            s.delete(debt)
            return 0
        debt.summa -= amount
        debt.sysprice -= cost_part
        return debt.summa


# ---------------------------------------------------------------- расходы

def list_expenses(search="", day=None):
    with session_scope() as s:
        q = select(Expense).order_by(Expense.id.desc())
        q = _search(q, [Expense.name, Expense.description, Expense.createdBy], search)
        return list(s.scalars(_on_day(q, Expense.createAt, day)))


def save_expense(seller: str, expense_id, name, summa, description="") -> Expense:
    name = _text(name, "Название")
    summa = _int(summa, "Сумма", 1)
    description = _text(description, "Описание", required=False, max_len=500)
    ts = now_str()
    with session_scope() as s:
        if expense_id is None:
            expense = Expense(name=name, summa=summa, description=description,
                              updateAt=ts, updatedBy=seller, createAt=ts, createdBy=seller)
            s.add(expense)
        else:
            expense = s.get(Expense, expense_id)
            if not expense:
                raise AppError("Расход не найден")
            expense.name, expense.summa, expense.description = name, summa, description
            expense.updateAt, expense.updatedBy = ts, seller
        s.flush()
        return expense


def delete_expense(expense_id: int) -> None:
    with session_scope() as s:
        expense = s.get(Expense, expense_id)
        if not expense:
            raise AppError("Расход не найден")
        s.delete(expense)


# ---------------------------------------------------------------- отчёт за день

@dataclass
class DayReport:
    day: str
    revenue: int = 0
    cost: int = 0
    expenses: int = 0
    by_type: dict = field(default_factory=dict)   # способ оплаты → сумма (вместе с оплатами долгов)
    debt_paid: int = 0                              # из выручки — оплаты старых долгов
    new_debts: int = 0
    debts_total: int = 0

    @property
    def gross(self):
        return self.revenue - self.cost

    @property
    def net(self):
        return self.gross - self.expenses


def day_report(day=None) -> DayReport:
    report = DayReport(day=day_str(day))
    like = f"{report.day}%"
    with session_scope() as s:
        rows = s.execute(
            select(Order.paymentType, Order.isDebtPayment, func.coalesce(func.sum(Order.summa), 0),
                   func.coalesce(func.sum(Order.sysprice), 0))
            .where(Order.createAt.like(like)).group_by(Order.paymentType, Order.isDebtPayment)
        ).all()
        for payment_type, is_debt_payment, summa, cost in rows:
            summa, cost = int(summa), int(cost)
            report.by_type[payment_type] = report.by_type.get(payment_type, 0) + summa
            if is_debt_payment or payment_type == PAID:
                report.debt_paid += summa
            report.revenue += summa
            report.cost += cost
        report.expenses = int(s.scalar(select(func.coalesce(func.sum(Expense.summa), 0))
                                       .where(Expense.createAt.like(like))))
        report.new_debts = int(s.scalar(select(func.coalesce(func.sum(Debt.summa), 0))
                                        .where(Debt.createAt.like(like))))
        report.debts_total = int(s.scalar(select(func.coalesce(func.sum(Debt.summa), 0))
                                          .where(Debt.summa > 0)))
    return report


def format_report(r: DayReport, html=True) -> str:
    b = (lambda t: f"<b>{t}</b>") if html else (lambda t: t)
    t = r.by_type
    return "\n".join([
        b(f"📊 Есеп: {r.day}"),
        "",
        f"{b('Таза пайда:')} {money(r.net)} ₸",
        f"Жалпы түсім: {money(r.revenue)} ₸",
        f"  • Kaspi: {money(t.get(KASPI))}",
        f"  • Наличка: {money(t.get(CASH))}",
        f"  • Аралас: {money(t.get(MIXED))}",
        f"  Оның ішінде қарыз өтелді: {money(r.debt_paid)}",
        f"Өзіндік құны: {money(r.cost)} ₸",
        f"Жалпы пайда: {money(r.gross)} ₸",
        f"Шығын: {money(r.expenses)} ₸",
        "",
        f"Бүгін қарызға: {money(r.new_debts)} ₸",
        f"Барлық қарыз: {money(r.debts_total)} ₸",
    ])


# ---------------------------------------------------------------- Telegram

def get_tg_user(user_id):
    with session_scope() as s:
        return s.scalar(select(TelegramUser).where(TelegramUser.userId == str(user_id)))


def register_tg_user(name: str, chat_id, user_id) -> None:
    with session_scope() as s:
        if not s.scalar(select(TelegramUser.id).where(TelegramUser.userId == str(user_id))):
            s.add(TelegramUser(name=name, chatId=str(chat_id), userId=str(user_id)))


def is_subscribed(user_id) -> bool:
    with session_scope() as s:
        return s.scalar(select(Event.id).where(Event.userId == str(user_id))) is not None


def subscribe(name: str, chat_id, user_id) -> bool:
    """True — подписали, False — уже был подписан."""
    with session_scope() as s:
        if s.scalar(select(Event.id).where(Event.userId == str(user_id))):
            return False
        s.add(Event(name=name or str(user_id), chatId=str(chat_id), userId=str(user_id)))
        return True


def unsubscribe(user_id) -> bool:
    with session_scope() as s:
        events = list(s.scalars(select(Event).where(Event.userId == str(user_id))))
        for e in events:
            s.delete(e)
        return bool(events)


def subscriber_chat_ids():
    with session_scope() as s:
        rows = s.execute(select(Event.chatId, Event.userId)).all()
    return sorted({chat or user for chat, user in rows if chat or user})


def esc(value) -> str:
    return escape(str(value if value is not None else ""))
