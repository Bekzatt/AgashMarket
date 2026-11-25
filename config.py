"""Настройки приложения. Все секреты и адрес базы берутся из файла .env (см. .env.example)."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

FROZEN = getattr(sys, "frozen", False)  # True — запущено из собранного AgashMarket.exe
# Ресурсы программы (картинки, миграции): в exe они распаковываются во временную папку
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
# Папка с настройками (.env) и логами: рядом с exe или рядом со скриптами
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
load_dotenv(APP_DIR / ".env")

# Строка подключения SQLAlchemy.
#   PostgreSQL: postgresql+psycopg2://user:password@localhost:5432/agashgroup
#   MS SQL:     mssql+pyodbc://SERVER/AgashGroup?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/agashgroup",
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Telegram ID через запятую, кому разрешено регистрироваться в боте. Пусто = всем.
BOT_ALLOWED_IDS = {
    int(x) for x in os.getenv("BOT_ALLOWED_IDS", "").replace(" ", "").split(",") if x.isdigit()
}

HELP_TEXT = os.getenv(
    "HELP_TEXT",
    "Егер қателіктер болған жағдайда скрин жасап әкімшіге жазыңыз",
)

LOG_DIR = APP_DIR / "logs"

# Обновления через GitHub Releases. Репозиторий задаётся в version.py (UPDATE_REPO),
# в .env можно переопределить. Токен (только чтение) нужен лишь для приватного репозитория.
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
