"""Add tenant_id to users.

Revision ID: 2026_01_20_1500-add_tenant_id_to_users
Revises: 2026_01_19_1500-add_user_group_tables
Create Date: 2026-01-20 15:00:00.000000

"""
from typing import Sequence, Union

from sqlalchemy import Column, Integer, ForeignKey, Index

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2026_01_20_1500'
down_revision: Union[str, None] = '2026_01_19_1500'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add tenant_id column to users table
    op.add_column(
        'users',
        Column('tenant_id', Integer, ForeignKey('tenants.id', ondelete='CASCADE'), nullable=True)
    )
    
    # Create index for tenant_id
    op.create_index('idx_users_tenant_id', 'users', ['tenant_id'])


def downgrade() -> None:
    # Drop index
    op.drop_index('idx_users_tenant_id', table_name='users')
    
    # Drop column
    op.drop_column('users', 'tenant_id')
