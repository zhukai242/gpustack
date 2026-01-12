"""Add tenant management tables.

Revision ID: 2026_01_08_1400
Revises: 2026_01_07_1200
Create Date: 2026-01-08 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '2026_01_08_1400'
down_revision = '2026_01_07_1200'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create tenants table
    op.create_table(
        'tenants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('contact_person', sa.String(), nullable=True),
        sa.Column('contact_phone', sa.String(), nullable=True),
        sa.Column('contact_email', sa.String(), nullable=True),
        sa.Column('resource_start_time', sa.DateTime(), nullable=True),
        sa.Column('resource_end_time', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='active'),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('labels', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_tenants_deleted_at_created_at', 'tenants', ['deleted_at', 'created_at'])
    op.create_index('idx_tenants_status', 'tenants', ['status'])
    op.create_index('idx_tenants_name', 'tenants', ['name'])
    op.create_index(op.f('ix_tenants_id'), 'tenants', ['id'], unique=False)

    # Create tenant_resources table
    op.create_table(
        'tenant_resources',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('gpu_id', sa.String(), nullable=True),
        sa.Column('resource_start_time', sa.DateTime(), nullable=True),
        sa.Column('resource_end_time', sa.DateTime(), nullable=True),
        sa.Column('resource_config', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_tenant_resources_deleted_at_created_at', 'tenant_resources', ['deleted_at', 'created_at'])
    op.create_index('idx_tenant_resources_tenant_id', 'tenant_resources', ['tenant_id'])
    op.create_index('idx_tenant_resources_worker_id', 'tenant_resources', ['worker_id'])
    op.create_index('idx_tenant_resources_gpu_id', 'tenant_resources', ['gpu_id'])
    op.create_index('idx_tenant_resources_end_time', 'tenant_resources', ['resource_end_time'])
    op.create_index(op.f('ix_tenant_resources_id'), 'tenant_resources', ['id'], unique=False)

    # Create tenant_resource_adjustments table
    op.create_table(
        'tenant_resource_adjustments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('adjustment_type', sa.String(), nullable=False),
        sa.Column('adjustment_time', sa.DateTime(), nullable=False),
        sa.Column('operator', sa.String(), nullable=True),
        sa.Column('adjustment_details', sa.JSON(), nullable=True),
        sa.Column('reason', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_tenant_adjustments_deleted_at_created_at', 'tenant_resource_adjustments', ['deleted_at', 'created_at'])
    op.create_index('idx_tenant_adjustments_tenant_id', 'tenant_resource_adjustments', ['tenant_id'])
    op.create_index('idx_tenant_adjustments_time', 'tenant_resource_adjustments', ['adjustment_time'])
    op.create_index('idx_tenant_adjustments_type', 'tenant_resource_adjustments', ['adjustment_type'])
    op.create_index(op.f('ix_tenant_resource_adjustments_id'), 'tenant_resource_adjustments', ['id'], unique=False)

    # Create tenant_resource_usage_details table
    op.create_table(
        'tenant_resource_usage_details',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('usage_date', sa.DateTime(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('gpu_id', sa.String(), nullable=True),
        sa.Column('gpu_hours', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('gpu_utilization', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('vram_usage_gb', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('cost', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('cost_currency', sa.String(), nullable=False, server_default='USD'),
        sa.Column('usage_metrics', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_tenant_usage_deleted_at_created_at', 'tenant_resource_usage_details', ['deleted_at', 'created_at'])
    op.create_index('idx_tenant_usage_tenant_id', 'tenant_resource_usage_details', ['tenant_id'])
    op.create_index('idx_tenant_usage_date', 'tenant_resource_usage_details', ['usage_date'])
    op.create_index('idx_tenant_usage_worker_id', 'tenant_resource_usage_details', ['worker_id'])
    op.create_index('idx_tenant_usage_gpu_id', 'tenant_resource_usage_details', ['gpu_id'])
    op.create_index('idx_tenant_usage_tenant_date', 'tenant_resource_usage_details', ['tenant_id', 'usage_date'])
    op.create_index(op.f('ix_tenant_resource_usage_details_id'), 'tenant_resource_usage_details', ['id'], unique=False)


def downgrade() -> None:
    # Drop tenant_resource_usage_details table
    op.drop_index(op.f('ix_tenant_resource_usage_details_id'), table_name='tenant_resource_usage_details')
    op.drop_index('idx_tenant_usage_tenant_date', table_name='tenant_resource_usage_details')
    op.drop_index('idx_tenant_usage_gpu_id', table_name='tenant_resource_usage_details')
    op.drop_index('idx_tenant_usage_worker_id', table_name='tenant_resource_usage_details')
    op.drop_index('idx_tenant_usage_date', table_name='tenant_resource_usage_details')
    op.drop_index('idx_tenant_usage_tenant_id', table_name='tenant_resource_usage_details')
    op.drop_index('idx_tenant_usage_deleted_at_created_at', table_name='tenant_resource_usage_details')
    op.drop_table('tenant_resource_usage_details')

    # Drop tenant_resource_adjustments table
    op.drop_index(op.f('ix_tenant_resource_adjustments_id'), table_name='tenant_resource_adjustments')
    op.drop_index('idx_tenant_adjustments_type', table_name='tenant_resource_adjustments')
    op.drop_index('idx_tenant_adjustments_time', table_name='tenant_resource_adjustments')
    op.drop_index('idx_tenant_adjustments_tenant_id', table_name='tenant_resource_adjustments')
    op.drop_index('idx_tenant_adjustments_deleted_at_created_at', table_name='tenant_resource_adjustments')
    op.drop_table('tenant_resource_adjustments')

    # Drop tenant_resources table
    op.drop_index(op.f('ix_tenant_resources_id'), table_name='tenant_resources')
    op.drop_index('idx_tenant_resources_end_time', table_name='tenant_resources')
    op.drop_index('idx_tenant_resources_gpu_id', table_name='tenant_resources')
    op.drop_index('idx_tenant_resources_worker_id', table_name='tenant_resources')
    op.drop_index('idx_tenant_resources_tenant_id', table_name='tenant_resources')
    op.drop_index('idx_tenant_resources_deleted_at_created_at', table_name='tenant_resources')
    op.drop_table('tenant_resources')

    # Drop tenants table
    op.drop_index(op.f('ix_tenants_id'), table_name='tenants')
    op.drop_index('idx_tenants_name', table_name='tenants')
    op.drop_index('idx_tenants_status', table_name='tenants')
    op.drop_index('idx_tenants_deleted_at_created_at', table_name='tenants')
    op.drop_table('tenants')
