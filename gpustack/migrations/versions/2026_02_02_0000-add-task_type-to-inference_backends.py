"""Add task_type to inference_backends

Revision ID: 2026_02_02_0000
Revises: 
Create Date: 2026-02-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2026_02_02_0000'
down_revision = '2026_01_28_1500'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add task_type column to inference_backends table with nullable=True first
    op.add_column(
        'inference_backends',
        sa.Column('task_type', sa.Integer(), nullable=True)
    )
    
    # Update existing rows to set default value
    op.execute('UPDATE inference_backends SET task_type = 0 WHERE task_type IS NULL')
    
    # Set column to nullable=False
    op.alter_column('inference_backends', 'task_type', nullable=False)
    # Add tenant_id column to inference_backends table
    op.add_column(
        'inference_backends',
        sa.Column('tenant_id', sa.Integer(), nullable=True, index=True)
    )
    # Add created_by column to inference_backends table
    op.add_column(
        'inference_backends',
        sa.Column('created_by', sa.Integer(), nullable=True)
    )

def downgrade() -> None:
    # Remove task_type column from inference_backends table
    op.drop_column('inference_backends', 'task_type')
    # Remove tenant_id column from inference_backends table
    op.drop_column('inference_backends', 'tenant_id')
    # Remove created_by column from inference_backends table
    op.drop_column('inference_backends', 'created_by')
