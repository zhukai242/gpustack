"""Add license operations table.

Revision ID: 2026_01_19_1000
Revises: 2026_01_13_1000
Create Date: 2026-01-19 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '2026_01_19_1000'
down_revision = '2026_01_13_1000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create license_operations table
    op.create_table('license_operations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('license_id', sa.Integer(), nullable=True),
        sa.Column('operation_type', sa.String(), nullable=False),
        sa.Column('operator', sa.String(), nullable=False),
        sa.Column('operation_time', sa.DateTime(), nullable=True),
        sa.Column('old_value', sa.String(), nullable=True),
        sa.Column('new_value', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['license_id'], ['licenses.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_license_operations_deleted_at_created_at', 'license_operations', ['deleted_at', 'created_at'])
    op.create_index(op.f('ix_license_operations_id'), 'license_operations', ['id'], unique=False)
    op.create_index(op.f('ix_license_operations_license_id'), 'license_operations', ['license_id'], unique=False)
    op.create_index(op.f('ix_license_operations_operation_type'), 'license_operations', ['operation_type'], unique=False)


def downgrade() -> None:
    # Drop license_operations table
    op.drop_index(op.f('ix_license_operations_operation_type'), table_name='license_operations')
    op.drop_index(op.f('ix_license_operations_license_id'), table_name='license_operations')
    op.drop_index(op.f('ix_license_operations_id'), table_name='license_operations')
    op.drop_index('idx_license_operations_deleted_at_created_at', table_name='license_operations')
    op.drop_table('license_operations')
