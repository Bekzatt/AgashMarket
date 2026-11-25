"""Запуск кассы.

    python init.py            — касса (бот запускается вместе с ней)
    AgashMarket.exe           — то же из собранного exe
    AgashMarket.exe --bot     — только бот (так касса запускает бота из exe)
"""
import logging
import subprocess
import sys
import traceback

from PyQt5.QtWidgets import QApplication, QMessageBox

import config
import version

log = logging.getLogger("app")


def setup_logging():
    config.LOG_DIR.mkdir(exist_ok=True)
    handlers = [logging.FileHandler(config.LOG_DIR / "app.log", encoding="utf-8")]
    if sys.stderr:  # в exe без консоли sys.stderr нет
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=handlers)


def excepthook(exc_type, exc_value, exc_tb):
    """Непойманная ошибка: пишем в logs/app.log и показываем окно, но программа не закрывается."""
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    log.error("Unhandled exception:\n%s", text)
    if QApplication.instance():
        box = QMessageBox(QMessageBox.Critical, "Ошибка", f"Произошла ошибка:\n{exc_value}\n\n{config.HELP_TEXT}")
        box.setDetailedText(text)
        box.exec_()


def apply_migrations():
    """Создаёт/обновляет таблицы в базе (alembic upgrade head)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(config.BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(config.BASE_DIR / "alembic"))
    command.upgrade(cfg, "head")


def start_bot():
    """Запускает Telegram-бота в фоне (без окна). Бот живёт, пока открыта касса."""
    if not config.BOT_TOKEN:
        log.info("BOT_TOKEN не задан — бот не запускается")
        return None
    try:
        errors = open(config.LOG_DIR / "bot-console.log", "a", encoding="utf-8")
        if config.FROZEN:  # exe запускает сам себя в режиме бота
            command = [sys.executable, "--bot", "--with-kassa"]
        else:
            command = [sys.executable, str(config.BASE_DIR / "mainBot.py"), "--with-kassa"]
        return subprocess.Popen(
            command, cwd=str(config.APP_DIR), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        log.exception("Не удалось запустить бота")
        return None


def stop_bot(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.stdin.close()  # бот видит, что касса закрылась, и завершается сам
        proc.wait(timeout=8)
    except Exception:
        proc.kill()
    log.info("Бот остановлен")


def run_bot():
    import asyncio
    import mainBot
    asyncio.run(mainBot.main())
    return 0


def main():
    if "--bot" in sys.argv:
        return run_bot()
    setup_logging()
    log.info("Запуск кассы, версия %s", version.VERSION)
    sys.excepthook = excepthook
    app = QApplication(sys.argv)
    from views.style import setup_app
    setup_app(app)

    try:
        apply_migrations()
    except Exception as ex:
        log.exception("Не удалось подключиться к базе")
        QMessageBox.critical(None, "База данных",
                             f"Не удалось подключиться к базе данных.\nПроверьте DATABASE_URL в файле .env\n\n{ex}")
        return 1

    from views.updater import Updater
    from views.userAuthView import AuthWindow
    bot = start_bot()
    window = AuthWindow()
    window.show()
    updater = Updater(app)
    updater.check()  # в фоне; если есть новая версия — спросит «Скачать и установить?»
    try:
        return app.exec_()
    finally:
        stop_bot(bot)  # бот работает из того же exe — его нужно закрыть до подмены файла
        updater.apply_if_pending()


if __name__ == "__main__":
    sys.exit(main())
