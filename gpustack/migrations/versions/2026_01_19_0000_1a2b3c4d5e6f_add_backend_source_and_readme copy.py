"""add backend_source and readme to inference_backends table

Revision ID: 1a2b3c4d5e6f
Revises: 53667f33f000
Create Date: 2026-01-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
import gpustack

# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, None] = '2026_02_02_0000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('inference_backends', schema=None) as batch_op:
        batch_op.add_column(sa.Column('backend_source', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('enabled', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('icon', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('default_env', sa.JSON(), nullable=True))
        # Change description column from String(255) to Text to support longer descriptions
        batch_op.alter_column('description',
                              existing_type=sa.String(length=255),
                              type_=sa.Text(),
                              existing_nullable=True)
    # Create benchmarks table
    op.create_table('benchmarks',
    sa.Column('created_at', gpustack.schemas.common.UTCDateTime(), nullable=False),
    sa.Column('updated_at', gpustack.schemas.common.UTCDateTime(), nullable=False),
    sa.Column('deleted_at', gpustack.schemas.common.UTCDateTime(), nullable=True),
    sa.Column('raw_metrics', sa.JSON(), nullable=True),
    sa.Column('requests_per_second_mean', sa.Float(), nullable=True),
    sa.Column('request_latency_mean', sa.Float(), nullable=True),
    sa.Column('time_per_output_token_mean', sa.Float(), nullable=True),
    sa.Column('inter_token_latency_mean', sa.Float(), nullable=True),
    sa.Column('time_to_first_token_mean', sa.Float(), nullable=True),
    sa.Column('tokens_per_second_mean', sa.Float(), nullable=True),
    sa.Column('output_tokens_per_second_mean', sa.Float(), nullable=True),
    sa.Column('input_tokens_per_second_mean', sa.Float(), nullable=True),
    sa.Column('snapshot', gpustack.schemas.common.JSON(), nullable=True),
    sa.Column('gpu_summary', sa.Text(), nullable=True),
    sa.Column('gpu_vendor_summary', sa.Text(), nullable=True),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('profile', sqlmodel.sql.sqltypes.AutoString(), nullable=True, server_default="Custom"),
    sa.Column('dataset_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('dataset_input_tokens', sa.Integer(), nullable=True),
    sa.Column('dataset_output_tokens', sa.Integer(), nullable=True),
    sa.Column('dataset_seed', sa.Integer(), nullable=True, server_default="42"),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('cluster_id', sa.Integer(), nullable=False),
    sa.Column('model_id', sa.Integer(), nullable=True),
    sa.Column('model_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('model_instance_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('request_rate', sa.Integer(), nullable=False),
    sa.Column('total_requests', sa.Integer(), nullable=True),
    sa.Column('state', sa.Enum('PENDING', 'RUNNING', 'QUEUED', 'STOPPED', 'ERROR', 'UNREACHABLE', 'COMPLETED', name='benchmarkstateenum'), nullable=False),
    sa.Column('state_message', sa.Text(), nullable=True),
    sa.Column('progress', sa.Float(), nullable=True),
    sa.Column('worker_id', sa.Integer(), nullable=True),
    sa.Column('pid', sa.Integer(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('benchmarks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_benchmarks_name'), ['name'], unique=True)

def downgrade() -> None:
    with op.batch_alter_table('inference_backends', schema=None) as batch_op:
        batch_op.drop_column('backend_source')
        batch_op.drop_column('enabled')
        batch_op.drop_column('icon')
        batch_op.drop_column('default_env')
        # Revert description column back to String(255)
        batch_op.alter_column('description',
                              existing_type=sa.Text(),
                              type_=sa.String(length=255),
                              existing_nullable=True)
    with op.batch_alter_table('benchmarks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_benchmarks_name'))
    op.drop_table('benchmarks')
