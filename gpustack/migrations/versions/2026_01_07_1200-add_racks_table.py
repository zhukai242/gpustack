"""Create racks table and add rack_id to workers.

Revision ID: 2026_01_07_1200-add_racks_table
Revises: 2025_12_08_1623-2aed534bd7b2_v2_0_2_database_changes
Create Date: 2026-01-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '2026_01_07_1200'
down_revision = '53667f33f000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create racks table
    op.create_table('racks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('cluster_id', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['cluster_id'], ['clusters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_racks_deleted_at_created_at', 'racks', ['deleted_at', 'created_at'])
    op.create_index(op.f('ix_racks_id'), 'racks', ['id'], unique=False)
    
    # Add rack_id column to workers table
    op.add_column('workers', sa.Column('rack_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'workers', 'racks', ['rack_id'], ['id'], ondelete='SET NULL')
    op.create_index(op.f('ix_workers_rack_id'), 'workers', ['rack_id'], unique=False)


def downgrade() -> None:
    # Drop rack_id column from workers table
    op.drop_index(op.f('ix_workers_rack_id'), table_name='workers')
    op.drop_constraint(None, 'workers', type_='foreignkey')
    op.drop_column('workers', 'rack_id')
    
    # Drop racks table
    op.drop_index(op.f('ix_racks_id'), table_name='racks')
    op.drop_index('idx_racks_deleted_at_created_at', table_name='racks')
    op.drop_table('racks')
