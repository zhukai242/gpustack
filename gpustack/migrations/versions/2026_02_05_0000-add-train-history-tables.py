"""Add train_history and train_instances_history tables

Revision ID: 2026_02_05_0000
Revises: 2026_02_02_0000
Create Date: 2026-02-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '2026_02_05_0000'
down_revision = '1a2b3c4d5e6f_1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create train_history table
    op.create_table('train_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('meta', sa.JSON(), nullable=True),
        sa.Column('replicas', sa.Integer(), nullable=False),
        sa.Column('ready_replicas', sa.Integer(), nullable=False),
        sa.Column('categories', sa.JSON(), nullable=True),
        sa.Column('placement_strategy', sa.String(), nullable=False),
        sa.Column('cpu_offloading', sa.Boolean(), nullable=True),
        sa.Column('distributed_inference_across_workers', sa.Boolean(), nullable=True),
        sa.Column('worker_selector', sa.JSON(), nullable=True),
        sa.Column('gpu_selector', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('backend', sa.String(), nullable=True),
        sa.Column('backend_version', sa.String(), nullable=True),
        sa.Column('backend_parameters', sa.JSON(), nullable=True),
        sa.Column('image_name', sa.String(), nullable=True),
        sa.Column('run_command', sa.Text(), nullable=True),
        sa.Column('env', sa.JSON(), nullable=True),
        sa.Column('restart_on_error', sa.Boolean(), nullable=True),
        sa.Column('distributable', sa.Boolean(), nullable=True),
        sa.Column('extended_kv_cache', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('speculative_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('generic_proxy', sa.Boolean(), nullable=False),
        sa.Column('cluster_id', sa.Integer(), nullable=True),
        sa.Column('access_policy', sa.String(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('task_type', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('huggingface_repo_id', sa.String(), nullable=True),
        sa.Column('huggingface_filename', sa.String(), nullable=True),
        sa.Column('model_scope_model_id', sa.String(), nullable=True),
        sa.Column('model_scope_file_path', sa.String(), nullable=True),
        sa.Column('local_path', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['cluster_id'], ['clusters.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_train_history_name'), 'train_history', ['name'], unique=True)
    
    # Create train_instances_history table
    op.create_table('train_instances_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=True),
        sa.Column('worker_name', sa.String(), nullable=True),
        sa.Column('worker_advertise_address', sa.String(), nullable=True),
        sa.Column('worker_ip', sa.String(), nullable=True),
        sa.Column('worker_ifname', sa.String(), nullable=True),
        sa.Column('pid', sa.Integer(), nullable=True),
        sa.Column('port', sa.Integer(), nullable=True),
        sa.Column('ports', sa.JSON(), nullable=True),
        sa.Column('download_progress', sa.Float(), nullable=True),
        sa.Column('resolved_path', sa.String(), nullable=True),
        sa.Column('draft_model_source', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('draft_model_download_progress', sa.Float(), nullable=True),
        sa.Column('draft_model_resolved_path', sa.String(), nullable=True),
        sa.Column('restart_count', sa.Integer(), nullable=True),
        sa.Column('last_restart_time', sa.DateTime(), nullable=True),
        sa.Column('state', sa.String(), nullable=False),
        sa.Column('state_message', sa.Text(), nullable=True),
        sa.Column('computed_resource_claim', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('gpu_type', sa.String(), nullable=True),
        sa.Column('gpu_indexes', sa.JSON(), nullable=True),
        sa.Column('gpu_addresses', sa.JSON(), nullable=True),
        sa.Column('model_id', sa.Integer(), nullable=False),
        sa.Column('model_name', sa.String(), nullable=False),
        sa.Column('backend', sa.String(), nullable=True),
        sa.Column('backend_version', sa.String(), nullable=True),
        sa.Column('api_detected_backend_version', sa.String(), nullable=True),
        sa.Column('distributed_servers', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('cluster_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('huggingface_repo_id', sa.String(), nullable=True),
        sa.Column('huggingface_filename', sa.String(), nullable=True),
        sa.Column('model_scope_model_id', sa.String(), nullable=True),
        sa.Column('model_scope_file_path', sa.String(), nullable=True),
        sa.Column('local_path', sa.String(), nullable=True),
        sa.Column('train_history_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['cluster_id'], ['clusters.id'], ),
        sa.ForeignKeyConstraint(['train_history_id'], ['train_history.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_train_instances_history_name'), 'train_instances_history', ['name'], unique=True)


def downgrade() -> None:
    # Drop train_instances_history table
    op.drop_index(op.f('ix_train_instances_history_name'), table_name='train_instances_history')
    op.drop_table('train_instances_history')
    
    # Drop train_history table
    op.drop_index(op.f('ix_train_history_name'), table_name='train_history')
    op.drop_table('train_history')
