"""Add system_settings table.

Revision ID: 2026_01_08_1700-add_system_settings_table
Revises: 2026_01_08_1400-add_tenant_management_tables
Create Date: 2026-01-08 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '2026_01_08_1700'
down_revision = '2026_01_08_1400'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create system_settings table
    op.create_table('system_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('value', sa.JSON(), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('category', sa.String(), nullable=False, server_default='basic'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_required', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_editable', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('default_value', sa.JSON(), nullable=True),
        sa.Column('labels', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key')
    )
    op.create_index('idx_system_settings_deleted_at_created_at', 'system_settings', ['deleted_at', 'created_at'])
    op.create_index(op.f('ix_system_settings_id'), 'system_settings', ['id'], unique=False)
    op.create_index(op.f('ix_system_settings_key'), 'system_settings', ['key'], unique=True)
    op.create_index(op.f('ix_system_settings_category'), 'system_settings', ['category'], unique=False)
    
    # Insert initial system settings data
    # Basic Settings
    op.execute("""INSERT INTO system_settings (key, value, type, category, description, is_required, is_editable, default_value, labels, created_at, updated_at) VALUES
    ('system_name', '算力管理平台', 'string', 'basic', '系统名称', true, true, '算力管理平台', null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('system_version', 'v1.0.0', 'string', 'basic', '系统版本', true, false, 'v1.0.0', null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('deployment_environment', 'production', 'string', 'basic', '部署环境', true, true, 'production', '{"options": ["production", "testing", "development"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('timezone', 'Asia/Shanghai', 'string', 'basic', '系统时区', true, true, 'Asia/Shanghai', '{"options": ["Asia/Shanghai", "UTC", "Europe/London", "America/New_York"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('ntp_server', 'pool.ntp.org', 'string', 'basic', 'NTP服务器', true, true, 'pool.ntp.org', null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_ntp_sync', true, 'boolean', 'basic', '启用NTP同步', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('system_language', 'zh_CN', 'string', 'basic', '系统语言', true, true, 'zh_CN', '{"options": ["zh_CN", "en_US", "ja_JP"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('auto_detect_browser_language', true, 'boolean', 'basic', '自动检测浏览器语言', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    
    # Network Settings
    op.execute("""INSERT INTO system_settings (key, value, type, category, description, is_required, is_editable, default_value, labels, created_at, updated_at) VALUES
    ('network_mode', 'bridge', 'string', 'network', '网络模式', true, true, 'bridge', '{"options": ["bridge", "nat", "host"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('default_gateway', '192.168.1.1', 'string', 'network', '默认网关', true, true, '192.168.1.1', null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('subnet_mask', '255.255.255.0', 'string', 'network', '子网掩码', true, true, '255.255.255.0', null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('dns_servers', '8.8.8.8,114.114.114.114', 'string', 'network', 'DNS服务器', true, true, '8.8.8.8,114.114.114.114', null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('backup_dns_servers', '1.1.1.1,223.5.5.5', 'string', 'network', '备用DNS服务器', false, true, '1.1.1.1,223.5.5.5', null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_http', false, 'boolean', 'network', '启用HTTP服务', false, true, false, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_https', true, 'boolean', 'network', '启用HTTPS服务', true, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('http_port', 80, 'integer', 'network', 'HTTP端口', false, true, 80, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('https_port', 443, 'integer', 'network', 'HTTPS端口', true, true, 443, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_websocket', true, 'boolean', 'network', '启用WebSocket', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_firewall', true, 'boolean', 'network', '启用防火墙', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    
    # Security Settings
    op.execute("""INSERT INTO system_settings (key, value, type, category, description, is_required, is_editable, default_value, labels, created_at, updated_at) VALUES
    ('authentication_mode', 'local', 'string', 'security', '认证模式', true, true, 'local', '{"options": ["local", "ldap", "oidc", "radius"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_two_factor_auth', false, 'boolean', 'security', '启用双因素认证', false, true, false, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('password_auth_type', 'password', 'string', 'security', '密码认证类型', true, true, 'password', '{"options": ["password", "sms", "authenticator"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('password_expiry_days', 30, 'integer', 'security', '密码有效期（天）', true, true, 30, '{"options": [30, 60, 90, 180, 0]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enforce_password_complexity', true, 'boolean', 'security', '强制密码复杂度', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('disable_reused_passwords', true, 'boolean', 'security', '禁用重复密码', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_ip_whitelist', false, 'boolean', 'security', '启用IP白名单', false, true, false, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('allowed_ip_ranges', '192.168.10.0/24,10.0.0.0/8', 'string', 'security', '允许的IP范围', false, true, '192.168.10.0/24,10.0.0.0/8', null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_session_timeout', true, 'boolean', 'security', '启用会话超时', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('session_timeout_minutes', 30, 'integer', 'security', '会话超时时间（分钟）', true, true, 30, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('encryption_algorithm', 'aes-256', 'string', 'security', '加密算法', true, true, 'aes-256', '{"options": ["aes-256", "aes-128"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('encrypt_sensitive_data', true, 'boolean', 'security', '加密存储敏感数据', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    
    # Storage Settings
    op.execute("""INSERT INTO system_settings (key, value, type, category, description, is_required, is_editable, default_value, labels, created_at, updated_at) VALUES
    ('storage_type', 'local', 'string', 'storage', '存储类型', true, true, 'local', '{"options": ["local", "nfs", "s3", "ceph"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('default_storage_pool', 'storage-pool-01', 'string', 'storage', '默认存储池', true, true, 'storage-pool-01', null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_auto_expand', true, 'boolean', 'storage', '启用自动扩展', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_data_compression', true, 'boolean', 'storage', '启用数据压缩', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_data_deduplication', false, 'boolean', 'storage', '启用数据去重', false, true, false, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('storage_retention_days', 365, 'integer', 'storage', '存储期限（天）', true, true, 365, '{"options": [30, 90, 180, 365, 0]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_auto_archive', true, 'boolean', 'storage', '启用自动归档', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('archive_threshold_days', 90, 'integer', 'storage', '归档阈值（天）', true, true, 90, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_auto_backup', true, 'boolean', 'storage', '启用自动备份', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('backup_frequency', 'daily', 'string', 'storage', '备份频率', true, true, 'daily', '{"options": ["daily", "weekly", "monthly"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    
    # Compute Resource Settings
    op.execute("""INSERT INTO system_settings (key, value, type, category, description, is_required, is_editable, default_value, labels, created_at, updated_at) VALUES
    ('gpu_scheduling_policy', 'load_balancing', 'string', 'compute', 'GPU调度策略', true, true, 'load_balancing', '{"options": ["load_balancing", "priority", "affinity"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('gpu_sharing_mode', 'exclusive', 'string', 'compute', 'GPU共享模式', true, true, 'exclusive', '{"options": ["exclusive", "time_sharing", "memory_isolation"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_gpu_monitoring', true, 'boolean', 'compute', '启用GPU监控', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_gpu_auto_downclock', true, 'boolean', 'compute', '启用GPU自动降频', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('gpu_temperature_threshold', 85, 'integer', 'compute', 'GPU温度阈值（°C）', true, true, 85, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('cpu_scheduling_policy', 'cfs', 'string', 'compute', 'CPU调度策略', true, true, 'cfs', '{"options": ["cfs", "realtime"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_hyperthreading', true, 'boolean', 'compute', '启用超线程', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('cpu_core_count', 16, 'integer', 'compute', 'CPU核心数量', true, true, 16, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('memory_capacity_gb', 128, 'integer', 'compute', '内存容量（GB）', true, true, 128, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_memory_compression', false, 'boolean', 'compute', '启用内存压缩', false, true, false, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_memory_hot_add', true, 'boolean', 'compute', '启用内存热添加', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('storage_io_scheduler', 'cfq', 'string', 'compute', '存储IO调度策略', true, true, 'cfq', '{"options": ["noop", "cfq", "deadline"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    
    # Monitoring Settings
    op.execute("""INSERT INTO system_settings (key, value, type, category, description, is_required, is_editable, default_value, labels, created_at, updated_at) VALUES
    ('monitoring_interval', 15, 'integer', 'monitoring', '监控频率（秒）', true, true, 15, '{"options": [15, 30, 60, 300, 600]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('monitor_cpu_usage', true, 'boolean', 'monitoring', '监控CPU使用率', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('monitor_cpu_temperature', true, 'boolean', 'monitoring', '监控CPU温度', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('monitor_gpu_usage', true, 'boolean', 'monitoring', '监控GPU使用率', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('monitor_gpu_temperature', true, 'boolean', 'monitoring', '监控GPU温度', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('monitor_memory_usage', true, 'boolean', 'monitoring', '监控内存使用率', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('monitor_disk_usage', true, 'boolean', 'monitoring', '监控磁盘使用率', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('monitor_network_io', true, 'boolean', 'monitoring', '监控网络IO', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('monitor_disk_io', true, 'boolean', 'monitoring', '监控磁盘IO', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_email_alert', true, 'boolean', 'monitoring', '启用邮件告警', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_sms_alert', false, 'boolean', 'monitoring', '启用短信告警', false, true, false, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_webhook_alert', false, 'boolean', 'monitoring', '启用Webhook告警', false, true, false, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_dingtalk_alert', false, 'boolean', 'monitoring', '启用钉钉告警', false, true, false, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_wechat_alert', false, 'boolean', 'monitoring', '启用微信告警', false, true, false, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('cpu_usage_threshold', 85, 'integer', 'monitoring', 'CPU使用率阈值（%）', true, true, 85, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('cpu_temperature_threshold', 85, 'integer', 'monitoring', 'CPU温度阈值（°C）', true, true, 85, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('gpu_usage_threshold', 90, 'integer', 'monitoring', 'GPU使用率阈值（%）', true, true, 90, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('gpu_temperature_threshold_monitoring', 90, 'integer', 'monitoring', 'GPU温度阈值（°C）', true, true, 90, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('memory_usage_threshold', 80, 'integer', 'monitoring', '内存使用率阈值（%）', true, true, 80, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    
    # Logging Settings
    op.execute("""INSERT INTO system_settings (key, value, type, category, description, is_required, is_editable, default_value, labels, created_at, updated_at) VALUES
    ('system_log_level', 'DEBUG', 'string', 'logging', '系统日志级别', true, true, 'INFO', '{"options": ["DEBUG", "INFO", "WARN", "ERROR", "FATAL"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('app_log_level', 'DEBUG', 'string', 'logging', '应用日志级别', true, true, 'INFO', '{"options": ["DEBUG", "INFO", "WARN", "ERROR", "FATAL"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('log_format', 'text', 'string', 'logging', '日志格式', true, true, 'text', '{"options": ["text", "json", "syslog"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('log_retention_days', 7, 'integer', 'logging', '日志存储天数', true, true, 7, '{"options": [7, 30, 90, 180, 365]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_log_rotation', true, 'boolean', 'logging', '启用日志轮转', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('log_rotation_type', 'time', 'string', 'logging', '日志轮转类型', true, true, 'time', '{"options": ["size", "time"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('log_file_size', 100, 'integer', 'logging', '日志文件大小（MB）', true, true, 100, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('output_to_file', true, 'boolean', 'logging', '输出到文件', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('output_to_console', true, 'boolean', 'logging', '输出到控制台', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('output_to_syslog', false, 'boolean', 'logging', '输出到Syslog', false, true, false, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('output_to_elk', false, 'boolean', 'logging', '输出到ELK', false, true, false, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    
    # Maintenance Settings
    op.execute("""INSERT INTO system_settings (key, value, type, category, description, is_required, is_editable, default_value, labels, created_at, updated_at) VALUES
    ('enable_auto_backup', true, 'boolean', 'maintenance', '启用自动备份', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('backup_frequency_maintenance', 'weekly', 'string', 'maintenance', '备份频率', true, true, 'daily', '{"options": ["daily", "weekly", "monthly"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('backup_retention_count', 7, 'integer', 'maintenance', '备份保留份数', true, true, 7, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_incremental_backup', true, 'boolean', 'maintenance', '启用增量备份', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_backup_encryption', true, 'boolean', 'maintenance', '启用备份加密', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_auto_update', true, 'boolean', 'maintenance', '自动检查更新', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_auto_install_update', false, 'boolean', 'maintenance', '自动安装更新', false, true, false, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_auto_restart', true, 'boolean', 'maintenance', '启用自动重启', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_auto_clean_temp_files', true, 'boolean', 'maintenance', '自动清理临时文件', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_auto_clean_log_files', true, 'boolean', 'maintenance', '自动清理日志文件', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    
    # Integration Settings
    op.execute("""INSERT INTO system_settings (key, value, type, category, description, is_required, is_editable, default_value, labels, created_at, updated_at) VALUES
    ('enable_api_access', true, 'boolean', 'integration', '启用API访问', false, true, true, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('api_key', 'sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', 'string', 'integration', 'API密钥', true, true, 'sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('integrate_prometheus', false, 'boolean', 'integration', '集成Prometheus', false, true, false, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('integrate_grafana', false, 'boolean', 'integration', '集成Grafana', false, true, false, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('integrate_ldap', false, 'boolean', 'integration', '集成LDAP', false, true, false, null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)


def downgrade() -> None:
    # Drop system_settings table
    op.drop_index(op.f('ix_system_settings_category'), table_name='system_settings')
    op.drop_index(op.f('ix_system_settings_key'), table_name='system_settings')
    op.drop_index(op.f('ix_system_settings_id'), table_name='system_settings')
    op.drop_index('idx_system_settings_deleted_at_created_at', table_name='system_settings')
    op.drop_table('system_settings')
