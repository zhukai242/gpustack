"""Add license tables.

Revision ID: 2026_01_08_1800
Revises: 2026_01_08_1700
Create Date: 2026-01-08 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '2026_01_08_1800'
down_revision = '2026_01_08_1700'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create licenses table
    op.create_table('licenses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('license_id', sa.String(), nullable=False),
        sa.Column('license_code', sa.String(), nullable=False),
        sa.Column('license_type', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('activation_time', sa.DateTime(), nullable=True),
        sa.Column('expiration_time', sa.DateTime(), nullable=True),
        sa.Column('issued_time', sa.DateTime(), nullable=True),
        sa.Column('issuer', sa.String(), nullable=False),
        sa.Column('max_gpus', sa.Integer(), nullable=False),
        sa.Column('cluster_id', sa.Integer(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['cluster_id'], ['clusters.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('license_code'),
        sa.UniqueConstraint('license_id')
    )
    op.create_index('idx_licenses_deleted_at_created_at', 'licenses', ['deleted_at', 'created_at'])
    op.create_index(op.f('ix_licenses_id'), 'licenses', ['id'], unique=False)
    op.create_index(op.f('ix_licenses_license_code'), 'licenses', ['license_code'], unique=True)
    op.create_index(op.f('ix_licenses_license_id'), 'licenses', ['license_id'], unique=True)
    op.create_index(op.f('ix_licenses_status'), 'licenses', ['status'], unique=False)
    
    # Create license_activations table
    op.create_table('license_activations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('license_external_id', sa.String(), nullable=False),
        sa.Column('license_code', sa.String(), nullable=False),
        sa.Column('license_id', sa.Integer(), nullable=True),
        sa.Column('worker_id', sa.Integer(), nullable=True),
        sa.Column('gpu_id', sa.String(), nullable=True),
        sa.Column('gpu_sn', sa.String(), nullable=False),
        sa.Column('gpu_model', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('activation_time', sa.DateTime(), nullable=True),
        sa.Column('expiration_time', sa.DateTime(), nullable=True),
        sa.Column('activated_by', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['license_id'], ['licenses.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_license_activations_deleted_at_created_at', 'license_activations', ['deleted_at', 'created_at'])
    op.create_index(op.f('ix_license_activations_gpu_id'), 'license_activations', ['gpu_id'], unique=False)
    op.create_index(op.f('ix_license_activations_gpu_sn'), 'license_activations', ['gpu_sn'], unique=False)
    op.create_index(op.f('ix_license_activations_id'), 'license_activations', ['id'], unique=False)
    op.create_index(op.f('ix_license_activations_license_code'), 'license_activations', ['license_code'], unique=False)
    op.create_index(op.f('ix_license_activations_license_external_id'), 'license_activations', ['license_external_id'], unique=False)
    op.create_index(op.f('ix_license_activations_license_id'), 'license_activations', ['license_id'], unique=False)
    op.create_index(op.f('ix_license_activations_status'), 'license_activations', ['status'], unique=False)
    op.create_index(op.f('ix_license_activations_worker_id'), 'license_activations', ['worker_id'], unique=False)


def downgrade() -> None:
    # Drop license_activations table
    op.drop_index(op.f('ix_license_activations_worker_id'), table_name='license_activations')
    op.drop_index(op.f('ix_license_activations_status'), table_name='license_activations')
    op.drop_index(op.f('ix_license_activations_license_id'), table_name='license_activations')
    op.drop_index(op.f('ix_license_activations_license_external_id'), table_name='license_activations')
    op.drop_index(op.f('ix_license_activations_license_code'), table_name='license_activations')
    op.drop_index(op.f('ix_license_activations_id'), table_name='license_activations')
    op.drop_index(op.f('ix_license_activations_gpu_sn'), table_name='license_activations')
    op.drop_index(op.f('ix_license_activations_gpu_id'), table_name='license_activations')
    op.drop_index('idx_license_activations_deleted_at_created_at', table_name='license_activations')
    op.drop_table('license_activations')
    
    # Drop licenses table
    op.drop_index(op.f('ix_licenses_status'), table_name='licenses')
    op.drop_index(op.f('ix_licenses_license_id'), table_name='licenses')
    op.drop_index(op.f('ix_licenses_license_code'), table_name='licenses')
    op.drop_index(op.f('ix_licenses_id'), table_name='licenses')
    op.drop_index('idx_licenses_deleted_at_created_at', table_name='licenses')
    op.drop_table('licenses')
