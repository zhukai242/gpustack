"""Add created_by field to models table.

Revision ID: add_created_by_to_models
Revises: add_model_catalog_tables
Create Date: 2026-01-27 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '2026_01_27_1500'
down_revision = '2026_01_26_1500'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add created_by column to models table
    op.add_column('models', sa.Column('created_by', sa.Integer(), nullable=True))
    # Add foreign key constraint
    op.create_foreign_key('fk_models_created_by', 'models', 'users', ['created_by'], ['id'], ondelete='SET NULL')
    # Add index for created_by
    op.create_index('ix_models_created_by', 'models', ['created_by'])
    
    # Add task_type column to models table (0: inference, 1: training)
    op.add_column('models', sa.Column('task_type', sa.Integer(), nullable=False, server_default='0'))
    # Add index for task_type
    op.create_index('ix_models_task_type', 'models', ['task_type'])
    
    # Add dataset_id column to models table
    op.add_column('models', sa.Column('dataset_id', sa.Integer(), nullable=True))
    # Add foreign key constraint
    op.create_foreign_key('fk_models_dataset_id', 'models', 'datasets', ['dataset_id'], ['id'], ondelete='SET NULL')
    # Add index for dataset_id
    op.create_index('ix_models_dataset_id', 'models', ['dataset_id'])


def downgrade() -> None:
    # Drop dataset_id index
    op.drop_index('ix_models_dataset_id', table_name='models')
    # Drop foreign key constraint
    op.drop_constraint('fk_models_dataset_id', 'models', type_='foreignkey')
    # Drop dataset_id column
    op.drop_column('models', 'dataset_id')
    
    # Drop task_type index
    op.drop_index('ix_models_task_type', table_name='models')
    # Drop task_type column
    op.drop_column('models', 'task_type')
    
    # Drop created_by index
    op.drop_index('ix_models_created_by', table_name='models')
    # Drop foreign key constraint
    op.drop_constraint('fk_models_created_by', 'models', type_='foreignkey')
    # Drop created_by column
    op.drop_column('models', 'created_by')
