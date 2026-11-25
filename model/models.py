"""Таблицы базы данных.

Имена таблиц и колонок оставлены как в старой версии (в т.ч. русские названия колонок),
поэтому существующая база MS SQL работает без изменений, а данные можно перенести в
PostgreSQL скриптом tools/transfer_data.py.
"""
from sqlalchemy import Boolean, Index, Integer, String, Unicode
from sqlalchemy.orm import DeclarativeBase, mapped_column


class Base(DeclarativeBase):
    pass


class TempProduct(Base):
    """История прихода товара (меню «Приход»). Каждая запись прибавляет количество на склад."""
    __tablename__ = "tempProducts"
    id = mapped_column(Integer, primary_key=True)
    name = mapped_column("Названия", Unicode, nullable=False)
    quantity = mapped_column("Количество", Integer)
    price = mapped_column("Цена", Integer, nullable=False)
    description = mapped_column("Описание", Unicode)
    isAdd = mapped_column(Boolean, nullable=True)
    updateAt = mapped_column(String, nullable=True)
    updatedBy = mapped_column(String, nullable=True)
    createAt = mapped_column(String, nullable=True)
    createdBy = mapped_column(String, nullable=False)


class Product(Base):
    """Склад. price — закупочная цена (себестоимость) за 1 шт."""
    __tablename__ = "products"
    id = mapped_column(Integer, primary_key=True)
    name = mapped_column("Названия", Unicode, nullable=False)
    quantity = mapped_column("Количество", Integer)
    price = mapped_column("Цена", Integer, nullable=False)
    description = mapped_column("Описание", Unicode)
    updateAt = mapped_column(String, nullable=True)
    updatedBy = mapped_column(String, nullable=True)
    createAt = mapped_column(String, nullable=True)
    createdBy = mapped_column(String, nullable=False)
    # Штрих-код: заводской или свой (EAN-13, начинается на 2). Уникальность проверяется в services
    # (уникальный индекс в MS SQL не допускает несколько пустых значений).
    barcode = mapped_column("Штрихкод", String(64), nullable=True)
    salePrice = mapped_column("Цена продажи", Integer, nullable=True)  # цена за 1 шт для сканера
    __table_args__ = (Index("ix_products_barcode", "Штрихкод"),)


class SaleMixin:
    """Общие колонки корзины, заказов и долгов."""
    id = mapped_column(Integer, primary_key=True)
    nameProduct = mapped_column("Названия", Unicode, nullable=False)
    count = mapped_column("Количество", Integer, nullable=False)
    summa = mapped_column("Сумма", Integer, nullable=False)          # цена продажи
    sysprice = mapped_column(Integer, nullable=False)                # себестоимость
    nameCustomer = mapped_column("Имя покупателя", Unicode, nullable=False)
    phoneNumberCustomer = mapped_column("Телефон номер покупателя", String, nullable=False)
    paymentType = mapped_column("Тип оплаты", Unicode, nullable=False)
    fioSeller = mapped_column("Имя продавца", Unicode, nullable=False)
    createAt = mapped_column(String, nullable=True)
    productId = mapped_column(Integer, nullable=False)

    def sale_fields(self) -> dict:
        return {
            "nameProduct": self.nameProduct, "count": self.count, "summa": self.summa,
            "sysprice": self.sysprice, "nameCustomer": self.nameCustomer,
            "phoneNumberCustomer": self.phoneNumberCustomer, "paymentType": self.paymentType,
            "fioSeller": self.fioSeller, "createAt": self.createAt, "productId": self.productId,
        }


class Cart(SaleMixin, Base):
    __tablename__ = "carts"


class Order(SaleMixin, Base):
    __tablename__ = "orders"
    # True — это оплата долга; paymentType тогда хранит способ оплаты (Наличка/Каспи/Аралас)
    isDebtPayment = mapped_column(Boolean, nullable=True)


class Debt(SaleMixin, Base):
    __tablename__ = "debts"


class Seller(Base):
    __tablename__ = "sellers"
    id = mapped_column(Integer, primary_key=True)
    nameShop = mapped_column("Названия магазина", Unicode, nullable=False)
    name = mapped_column("ФИО", Unicode, nullable=False)
    password = mapped_column("Пароль", Unicode, nullable=False)  # хэш pbkdf2


class Expense(Base):
    __tablename__ = "expenses"
    id = mapped_column(Integer, primary_key=True)
    name = mapped_column("ФИО", Unicode, nullable=False)  # название расхода
    summa = mapped_column("Сумма", Integer, nullable=False)
    description = mapped_column("Описание", Unicode)
    updateAt = mapped_column(String, nullable=True)
    updatedBy = mapped_column(String, nullable=True)
    createAt = mapped_column(String, nullable=True)
    createdBy = mapped_column(String, nullable=False)


class TelegramUser(Base):
    __tablename__ = "telegramUsers"
    id = mapped_column(Integer, primary_key=True)
    name = mapped_column("ФИО", Unicode, nullable=False)
    chatId = mapped_column(String, nullable=False)
    userId = mapped_column(String, nullable=False)


class Event(Base):
    """Подписчики уведомлений в Telegram."""
    __tablename__ = "events"
    id = mapped_column(Integer, primary_key=True)
    name = mapped_column("Названия", Unicode, nullable=False)
    chatId = mapped_column(String, nullable=True)
    userId = mapped_column(String, nullable=True)
