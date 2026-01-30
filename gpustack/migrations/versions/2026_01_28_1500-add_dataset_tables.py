"""Add dataset tables.

Revision ID: add_dataset_tables
Revises: add_created_by_to_models
Create Date: 2026-01-28 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '2026_01_28_1500'
down_revision = '2026_01_27_1500'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create datasets table
    op.create_table('datasets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False, index=True),
        sa.Column('path', sa.String(length=1024), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('sample_count', sa.Integer(), nullable=True, default=0),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True, default=0),
        sa.Column('storage_type', sa.String(length=50), nullable=True, default='local'),
        sa.Column('status', sa.String(length=50), nullable=True, default='active'),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create dataset_versions table
    op.create_table('dataset_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=False, index=True),
        sa.Column('version', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('sample_count', sa.Integer(), nullable=True, default=0),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True, default=0),
        sa.Column('path', sa.String(length=1024), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create unique constraint for dataset version
    op.create_unique_constraint('uq_dataset_version', 'dataset_versions', ['dataset_id', 'version'])


def downgrade() -> None:
    # Drop dataset_versions table
    op.drop_table('dataset_versions')
    # Drop datasets table
    op.drop_table('datasets')
