"""Add processor and comment fields to logs tables.

Revision ID: 2026_01_13_1000
Revises: 2026_01_08_1800
Create Date: 2026-01-13 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '2026_01_13_1000'
down_revision = '2026_01_08_1800'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add processor and comment fields to worker_logs table
    op.add_column('worker_logs', sa.Column('processor', sa.String(), nullable=True))
    op.add_column('worker_logs', sa.Column('comment', sa.String(), nullable=True))
    
    # Add processor and comment fields to gpu_logs table
    op.add_column('gpu_logs', sa.Column('processor', sa.String(), nullable=True))
    op.add_column('gpu_logs', sa.Column('comment', sa.String(), nullable=True))


def downgrade() -> None:
    # Remove processor and comment fields from gpu_logs table
    op.drop_column('gpu_logs', 'comment')
    op.drop_column('gpu_logs', 'processor')
    
    # Remove processor and comment fields from worker_logs table
    op.drop_column('worker_logs', 'comment')
    op.drop_column('worker_logs', 'processor')
