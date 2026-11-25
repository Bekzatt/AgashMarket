"""Product: штрих-код и цена продажи

Revision ID: a3e5b8c21f07
Revises: 7c2f1a9d4b10
Create Date: 2026-11-26 10:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = 'a3e5b8c21f07'
down_revision = '7c2f1a9d4b10'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('products', sa.Column('Штрихкод', sa.String(64), nullable=True))
    op.add_column('products', sa.Column('Цена продажи', sa.Integer(), nullable=True))
    op.create_index('ix_products_barcode', 'products', ['Штрихкод'])


def downgrade() -> None:
    op.drop_index('ix_products_barcode', table_name='products')
    op.drop_column('products', 'Цена продажи')
    op.drop_column('products', 'Штрихкод')
