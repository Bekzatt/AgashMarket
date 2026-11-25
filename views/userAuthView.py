"""Окно входа и регистрации продавца."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QFormLayout, QHBoxLayout, QLineEdit, QMessageBox, QStackedWidget, QVBoxLayout, QWidget

import config
import version
from model import services
from model.notifier import notify
from views.mainPage import MainWindow
from views.widgets import Card, button, label, show_error


class AuthWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Root")
        self.setWindowTitle(f"Ағаш базар — вход (версия {version.VERSION})")
        self.setWindowIcon(QIcon(str(config.BASE_DIR / "images" / "login.png")))
        self.resize(900, 620)
        self.main_window = None

        card = Card()
        card.setFixedWidth(400)
        card.body.setContentsMargins(32, 28, 32, 28)
        card.body.setSpacing(14)
        card.body.addWidget(label("Ағаш базар", "PageTitle"), alignment=Qt.AlignHCenter)
        self.subtitle = label("Войдите, чтобы продолжить", "Muted")
        card.body.addWidget(self.subtitle, alignment=Qt.AlignHCenter)

        self.pages = QStackedWidget()
        self.pages.setStyleSheet("QStackedWidget { background: transparent; }")
        self.pages.addWidget(self._login_form())
        self.pages.addWidget(self._register_form())
        card.body.addWidget(self.pages)

        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(card)
        row.addStretch()
        outer.addStretch()
        outer.addLayout(row)
        outer.addStretch()

    # ------------------------------------------------------------ формы
    def _login_form(self):
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 8, 0, 0)
        form.setVerticalSpacing(12)
        self.login_name = QLineEdit(placeholderText="Логин")
        self.login_pass = QLineEdit(placeholderText="Пароль", echoMode=QLineEdit.Password)
        self.login_pass.returnPressed.connect(self.do_login)
        self.login_name.returnPressed.connect(self.login_pass.setFocus)
        form.addRow("Логин", self.login_name)
        form.addRow("Пароль", self.login_pass)
        form.addRow(button("Кіру / Войти", "primary", self.do_login))
        form.addRow(button("Нет аккаунта? Тіркелу", "link", lambda: self._switch(1)))
        form.addRow(button("Шығу / Выход", None, self.close))
        return page

    def _register_form(self):
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 8, 0, 0)
        form.setVerticalSpacing(12)
        self.reg_shop = QLineEdit(placeholderText="Дүкен атауы")
        self.reg_name = QLineEdit(placeholderText="Логин")
        self.reg_pass = QLineEdit(placeholderText="Минимум 4 символа", echoMode=QLineEdit.Password)
        self.reg_pass2 = QLineEdit(placeholderText="Повторите пароль", echoMode=QLineEdit.Password)
        self.reg_pass2.returnPressed.connect(self.do_register)
        form.addRow("Магазин", self.reg_shop)
        form.addRow("Логин", self.reg_name)
        form.addRow("Пароль", self.reg_pass)
        form.addRow("Повтор", self.reg_pass2)
        form.addRow(button("Тіркелу / Зарегистрироваться", "primary", self.do_register))
        form.addRow(button("← Уже есть аккаунт", "link", lambda: self._switch(0)))
        return page

    def _switch(self, index):
        self.pages.setCurrentIndex(index)
        self.subtitle.setText("Войдите, чтобы продолжить" if index == 0 else "Новый продавец")

    # ------------------------------------------------------------ действия
    def do_login(self):
        try:
            seller = services.login(self.login_name.text(), self.login_pass.text())
        except Exception as ex:
            show_error(self, ex)
            return
        if not seller:
            QMessageBox.warning(self, "Ошибка", "Неверный логин или пароль")
            self.login_pass.clear()
            return
        notify(f"🔑 {seller.name} кассаға кірді")
        self.main_window = MainWindow(seller)
        self.main_window.show()
        self.close()

    def do_register(self):
        try:
            services.register_seller(self.reg_shop.text(), self.reg_name.text(),
                                     self.reg_pass.text(), self.reg_pass2.text())
        except Exception as ex:
            show_error(self, ex)
            return
        QMessageBox.information(self, "Готово", f"Продавец «{self.reg_name.text().strip()}» зарегистрирован")
        self.login_name.setText(self.reg_name.text().strip())
        for w in (self.reg_shop, self.reg_name, self.reg_pass, self.reg_pass2):
            w.clear()
        self._switch(0)
        self.login_pass.setFocus()
