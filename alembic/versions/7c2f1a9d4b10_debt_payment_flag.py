"""Order.isDebtPayment: оплата долга + способ оплаты

Revision ID: 7c2f1a9d4b10
Revises: 1e0748763819
Create Date: 2026-11-25 12:30:00

"""
from alembic import op
import sqlalchemy as sa

revision = '7c2f1a9d4b10'
down_revision = '1e0748763819'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('isDebtPayment', sa.Boolean(), nullable=True))
    orders = sa.table('orders', sa.column('isDebtPayment', sa.Boolean()), sa.column('Тип оплаты', sa.Unicode()))
    # старые записи «Погашен» — это оплаты долгов (способ оплаты тогда не сохранялся)
    op.execute(orders.update().where(orders.c['Тип оплаты'] == 'Погашен').values(isDebtPayment=True))
    op.execute(orders.update().where(orders.c['Тип оплаты'] != 'Погашен').values(isDebtPayment=False))


def downgrade() -> None:
    op.drop_column('orders', 'isDebtPayment')
