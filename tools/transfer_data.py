"""Перенос всех данных из одной базы в другую (например, MS SQL → PostgreSQL).

Использование:
    python tools/transfer_data.py "ИСТОЧНИК_URL" "ЦЕЛЬ_URL"

Пример:
    python tools/transfer_data.py ^
      "mssql+pyodbc://MyPC/AgashGroup?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes" ^
      "postgresql+psycopg2://postgres:ПАРОЛЬ@localhost:5432/agashgroup"

Таблицы в целевой базе создаются автоматически (alembic upgrade head) и должны быть пустыми.
Исходная база не изменяется.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    source_url, target_url = sys.argv[1], sys.argv[2]

    # миграции и модели читают DATABASE_URL — направляем их на целевую базу
    os.environ["DATABASE_URL"] = target_url
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, func, select, text

    from model.models import Base

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    command.upgrade(cfg, "head")

    source = create_engine(source_url)
    target = create_engine(target_url)
    tables = Base.metadata.sorted_tables

    with target.connect() as conn:
        busy = [t.name for t in tables if conn.execute(select(func.count()).select_from(t)).scalar()]
    if busy:
        print("Целевая база не пустая, перенос отменён. Таблицы с данными:", ", ".join(busy))
        return 1

    with source.connect() as src, target.begin() as dst:
        for table in tables:
            rows = [dict(r._mapping) for r in src.execute(select(table))]
            if rows:
                dst.execute(table.insert(), rows)
            print(f"{table.name}: {len(rows)} строк")
            if target.dialect.name == "postgresql" and rows:
                # чтобы новые записи получали id после перенесённых
                dst.execute(text(f"SELECT setval(pg_get_serial_sequence('\"{table.name}\"', 'id'), "
                                 f"(SELECT MAX(id) FROM \"{table.name}\"))"))
    print("Готово.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
