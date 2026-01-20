"""Add user group tables.

Revision ID: 2026_01_19_1500-add_user_group_tables
Revises: 
Create Date: 2026-01-19 15:00:00.000000

"""
from typing import Sequence, Union

from sqlalchemy import Column, Integer, String, ForeignKey, JSON, Index, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2026_01_19_1500'
down_revision: str = '2026_01_19_1000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create user_groups table
    op.create_table(
        'user_groups',
        Column('id', Integer, primary_key=True, autoincrement=True),
        Column('name', String(255), nullable=False),
        Column('tenant_id', Integer, ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        Column('description', String(512), nullable=True),
        Column('status', String(50), nullable=False, default='active'),
        Column('labels', JSON, nullable=True),
        Column('created_at', Integer, nullable=False),
        Column('updated_at', Integer, nullable=False),
        Column('deleted_at', Integer, nullable=True),
    )
    
    # Create indexes for user_groups
    op.create_index('idx_user_groups_deleted_at_created_at', 'user_groups', ['deleted_at', 'created_at'])
    op.create_index('idx_user_groups_tenant_id', 'user_groups', ['tenant_id'])
    op.create_index('idx_user_groups_status', 'user_groups', ['status'])
    op.create_index('idx_user_groups_name', 'user_groups', ['name'])
    
    # Create user_group_members table
    op.create_table(
        'user_group_members',
        Column('id', Integer, primary_key=True, autoincrement=True),
        Column('user_group_id', Integer, ForeignKey('user_groups.id', ondelete='CASCADE'), nullable=False),
        Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        Column('created_at', Integer, nullable=False),
        Column('updated_at', Integer, nullable=False),
        Column('deleted_at', Integer, nullable=True),
        UniqueConstraint('user_group_id', 'user_id', name='uq_user_group_members_user_group_id_user_id')
    )
    
    # Create indexes for user_group_members
    op.create_index('idx_user_group_members_user_group_id', 'user_group_members', ['user_group_id'])
    op.create_index('idx_user_group_members_user_id', 'user_group_members', ['user_id'])
    
    # Create user_group_resources table
    op.create_table(
        'user_group_resources',
        Column('id', Integer, primary_key=True, autoincrement=True),
        Column('user_group_id', Integer, ForeignKey('user_groups.id', ondelete='CASCADE'), nullable=False),
        Column('tenant_resource_id', Integer, ForeignKey('tenant_resources.id', ondelete='CASCADE'), nullable=False),
        Column('worker_id', Integer, ForeignKey('workers.id', ondelete='CASCADE'), nullable=False),
        Column('gpu_id', String(255), nullable=True),
        Column('created_at', Integer, nullable=False),
        Column('updated_at', Integer, nullable=False),
        Column('deleted_at', Integer, nullable=True),
        UniqueConstraint('user_group_id', 'tenant_resource_id', name='uq_user_group_resources_user_group_id_tenant_resource_id')
    )
    
    # Create indexes for user_group_resources
    op.create_index('idx_user_group_resources_user_group_id', 'user_group_resources', ['user_group_id'])
    op.create_index('idx_user_group_resources_tenant_resource_id', 'user_group_resources', ['tenant_resource_id'])
    op.create_index('idx_user_group_resources_worker_id', 'user_group_resources', ['worker_id'])
    op.create_index('idx_user_group_resources_gpu_id', 'user_group_resources', ['gpu_id'])


def downgrade() -> None:
    # Drop user_group_resources table
    op.drop_table('user_group_resources')
    
    # Drop user_group_members table
    op.drop_table('user_group_members')
    
    # Drop user_groups table
    op.drop_table('user_groups')
