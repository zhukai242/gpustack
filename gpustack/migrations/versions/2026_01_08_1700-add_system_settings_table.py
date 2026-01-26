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
    ('system_name', to_json('算力管理平台'::text), 'STRING', 'BASIC', '系统名称', true, true, to_json('算力管理平台'::text), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('system_version', to_json('v1.0.0'::text), 'STRING', 'BASIC', '系统版本', true, false, to_json('v1.0.0'::text), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('deployment_environment', to_json('production'::text), 'STRING', 'BASIC', '部署环境', true, true, to_json('production'::text), '{"options": ["production", "testing", "development"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('timezone', to_json('Asia/Shanghai'::text), 'STRING', 'BASIC', '系统时区', true, true, to_json('Asia/Shanghai'::text), '{"options": ["Asia/Shanghai", "UTC", "Europe/London", "America/New_York"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('ntp_server', to_json('pool.ntp.org'::text), 'STRING', 'BASIC', 'NTP服务器', true, true, to_json('pool.ntp.org'::text), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_ntp_sync', to_json(true::boolean), 'BOOLEAN', 'BASIC', '启用NTP同步', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('system_language', to_json('zh_CN'::text), 'STRING', 'BASIC', '系统语言', true, true, to_json('zh_CN'::text), '{"options": ["zh_CN", "en_US", "ja_JP"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('auto_detect_browser_language', to_json(true::boolean), 'BOOLEAN', 'BASIC', '自动检测浏览器语言', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    
    # Network Settings
    op.execute("""INSERT INTO system_settings (key, value, type, category, description, is_required, is_editable, default_value, labels, created_at, updated_at) VALUES
    ('network_mode', to_json('bridge'::text), 'STRING', 'NETWORK', '网络模式', true, true, to_json('bridge'::text), '{"options": ["bridge", "nat", "host"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('default_gateway', to_json('192.168.1.1'::text), 'STRING', 'NETWORK', '默认网关', true, true, to_json('192.168.1.1'::text), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('subnet_mask', to_json('255.255.255.0'::text), 'STRING', 'NETWORK', '子网掩码', true, true, to_json('255.255.255.0'::text), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('dns_servers', to_json('8.8.8.8,114.114.114.114'::text), 'STRING', 'NETWORK', 'DNS服务器', true, true, to_json('8.8.8.8,114.114.114.114'::text), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('backup_dns_servers', to_json('1.1.1.1,223.5.5.5'::text), 'STRING', 'NETWORK', '备用DNS服务器', false, true, to_json('1.1.1.1,223.5.5.5'::text), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_http', to_json(false::boolean), 'BOOLEAN', 'NETWORK', '启用HTTP服务', false, true, to_json(false::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_https', to_json(true::boolean), 'BOOLEAN', 'NETWORK', '启用HTTPS服务', true, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('http_port', to_json(80::integer), 'INTEGER', 'NETWORK', 'HTTP端口', false, true, to_json(80::integer), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('https_port', to_json(443::integer), 'INTEGER', 'NETWORK', 'HTTPS端口', true, true, to_json(443::integer), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_websocket', to_json(true::boolean), 'BOOLEAN', 'NETWORK', '启用WebSocket', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_firewall', to_json(true::boolean), 'BOOLEAN', 'NETWORK', '启用防火墙', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    
    # Security Settings
    op.execute("""INSERT INTO system_settings (key, value, type, category, description, is_required, is_editable, default_value, labels, created_at, updated_at) VALUES
    ('authentication_mode', to_json('local'::text), 'STRING', 'SECURITY', '认证模式', true, true, to_json('local'::text), '{"options": ["local", "ldap", "oidc", "radius"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_two_factor_auth', to_json(false::boolean), 'BOOLEAN', 'SECURITY', '启用双因素认证', false, true, to_json(false::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('password_auth_type', to_json('password'::text), 'STRING', 'SECURITY', '密码认证类型', true, true, to_json('password'::text), '{"options": ["password", "sms", "authenticator"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('password_expiry_days', to_json(30::integer), 'INTEGER', 'SECURITY', '密码有效期（天）', true, true, to_json(30::integer), '{"options": [30, 60, 90, 180, 0]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enforce_password_complexity', to_json(true::boolean), 'BOOLEAN', 'SECURITY', '强制密码复杂度', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('disable_reused_passwords', to_json(true::boolean), 'BOOLEAN', 'SECURITY', '禁用重复密码', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_ip_whitelist', to_json(false::boolean), 'BOOLEAN', 'SECURITY', '启用IP白名单', false, true, to_json(false::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('allowed_ip_ranges', to_json('192.168.10.0/24,10.0.0.0/8'::text), 'STRING', 'SECURITY', '允许的IP范围', false, true, to_json('192.168.10.0/24,10.0.0.0/8'::text), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_session_timeout', to_json(true::boolean), 'BOOLEAN', 'SECURITY', '启用会话超时', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('session_timeout_minutes', to_json(30::integer), 'INTEGER', 'SECURITY', '会话超时时间（分钟）', true, true, to_json(30::integer), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('encryption_algorithm', to_json('aes-256'::text), 'STRING', 'SECURITY', '加密算法', true, true, to_json('aes-256'::text), '{"options": ["aes-256", "aes-128"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('encrypt_sensitive_data', to_json(true::boolean), 'BOOLEAN', 'SECURITY', '加密存储敏感数据', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    
    # Storage Settings
    op.execute("""INSERT INTO system_settings (key, value, type, category, description, is_required, is_editable, default_value, labels, created_at, updated_at) VALUES
    ('storage_type', to_json('local'::text), 'STRING', 'STORAGE', '存储类型', true, true, to_json('local'::text), '{"options": ["local", "nfs", "s3", "ceph"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('default_storage_pool', to_json('storage-pool-01'::text), 'STRING', 'STORAGE', '默认存储池', true, true, to_json('storage-pool-01'::text), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_auto_expand', to_json(true::boolean), 'BOOLEAN', 'STORAGE', '启用自动扩展', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_data_compression', to_json(true::boolean), 'BOOLEAN', 'STORAGE', '启用数据压缩', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_data_deduplication', to_json(false::boolean), 'BOOLEAN', 'STORAGE', '启用数据去重', false, true, to_json(false::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('storage_retention_days', to_json(365::integer), 'INTEGER', 'STORAGE', '存储期限（天）', true, true, to_json(365::integer), '{"options": [30, 90, 180, 365, 0]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_auto_archive', to_json(true::boolean), 'BOOLEAN', 'STORAGE', '启用自动归档', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('archive_threshold_days', to_json(90::integer), 'INTEGER', 'STORAGE', '归档阈值（天）', true, true, to_json(90::integer), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_auto_backup', to_json(true::boolean), 'BOOLEAN', 'STORAGE', '启用自动备份', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('backup_frequency', to_json('daily'::text), 'STRING', 'STORAGE', '备份频率', true, true, to_json('daily'::text), '{"options": ["daily", "weekly", "monthly"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    
    # Compute Resource Settings
    op.execute("""INSERT INTO system_settings (key, value, type, category, description, is_required, is_editable, default_value, labels, created_at, updated_at) VALUES
    ('gpu_scheduling_policy', to_json('load_balancing'::text), 'STRING', 'COMPUTE', 'GPU调度策略', true, true, to_json('load_balancing'::text), '{"options": ["load_balancing", "priority", "affinity"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('gpu_sharing_mode', to_json('exclusive'::text), 'STRING', 'COMPUTE', 'GPU共享模式', true, true, to_json('exclusive'::text), '{"options": ["exclusive", "time_sharing", "memory_isolation"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_gpu_monitoring', to_json(true::boolean), 'BOOLEAN', 'COMPUTE', '启用GPU监控', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_gpu_auto_downclock', to_json(true::boolean), 'BOOLEAN', 'COMPUTE', '启用GPU自动降频', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('gpu_temperature_threshold', to_json(85::integer), 'INTEGER', 'COMPUTE', 'GPU温度阈值（°C）', true, true, to_json(85::integer), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('cpu_scheduling_policy', to_json('cfs'::text), 'STRING', 'COMPUTE', 'CPU调度策略', true, true, to_json('cfs'::text), '{"options": ["cfs", "realtime"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_hyperthreading', to_json(true::boolean), 'BOOLEAN', 'COMPUTE', '启用超线程', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('cpu_core_count', to_json(16::integer), 'INTEGER', 'COMPUTE', 'CPU核心数量', true, true, to_json(16::integer), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('memory_capacity_gb', to_json(128::integer), 'INTEGER', 'COMPUTE', '内存容量（GB）', true, true, to_json(128::integer), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_memory_compression', to_json(false::boolean), 'BOOLEAN', 'COMPUTE', '启用内存压缩', false, true, to_json(false::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_memory_hot_add', to_json(true::boolean), 'BOOLEAN', 'COMPUTE', '启用内存热添加', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('storage_io_scheduler', to_json('cfq'::text), 'STRING', 'COMPUTE', '存储IO调度策略', true, true, to_json('cfq'::text), '{"options": ["noop", "cfq", "deadline"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    
    # Monitoring Settings
    op.execute("""INSERT INTO system_settings (key, value, type, category, description, is_required, is_editable, default_value, labels, created_at, updated_at) VALUES
    ('monitoring_interval', to_json(15::integer), 'INTEGER', 'MONITORING', '监控频率（秒）', true, true, to_json(15::integer), '{"options": [15, 30, 60, 300, 600]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('monitor_cpu_usage', to_json(true::boolean), 'BOOLEAN', 'MONITORING', '监控CPU使用率', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('monitor_cpu_temperature', to_json(true::boolean), 'BOOLEAN', 'MONITORING', '监控CPU温度', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('monitor_gpu_usage', to_json(true::boolean), 'BOOLEAN', 'MONITORING', '监控GPU使用率', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('monitor_gpu_temperature', to_json(true::boolean), 'BOOLEAN', 'MONITORING', '监控GPU温度', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('monitor_memory_usage', to_json(true::boolean), 'BOOLEAN', 'MONITORING', '监控内存使用率', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('monitor_disk_usage', to_json(true::boolean), 'BOOLEAN', 'MONITORING', '监控磁盘使用率', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('monitor_network_io', to_json(true::boolean), 'BOOLEAN', 'MONITORING', '监控网络IO', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('monitor_disk_io', to_json(true::boolean), 'BOOLEAN', 'MONITORING', '监控磁盘IO', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_email_alert', to_json(true::boolean), 'BOOLEAN', 'MONITORING', '启用邮件告警', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_sms_alert', to_json(false::boolean), 'BOOLEAN', 'MONITORING', '启用短信告警', false, true, to_json(false::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_webhook_alert', to_json(false::boolean), 'BOOLEAN', 'MONITORING', '启用Webhook告警', false, true, to_json(false::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_dingtalk_alert', to_json(false::boolean), 'BOOLEAN', 'MONITORING', '启用钉钉告警', false, true, to_json(false::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_wechat_alert', to_json(false::boolean), 'BOOLEAN', 'MONITORING', '启用微信告警', false, true, to_json(false::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('cpu_usage_threshold', to_json(85::integer), 'INTEGER', 'MONITORING', 'CPU使用率阈值（%）', true, true, to_json(85::integer), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('cpu_temperature_threshold', to_json(85::integer), 'INTEGER', 'MONITORING', 'CPU温度阈值（°C）', true, true, to_json(85::integer), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('gpu_usage_threshold', to_json(90::integer), 'INTEGER', 'MONITORING', 'GPU使用率阈值（%）', true, true, to_json(90::integer), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('gpu_temperature_threshold_monitoring', to_json(90::integer), 'INTEGER', 'MONITORING', 'GPU温度阈值（°C）', true, true, to_json(90::integer), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('memory_usage_threshold', to_json(80::integer), 'INTEGER', 'MONITORING', '内存使用率阈值（%）', true, true, to_json(80::integer), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    
    # Logging Settings
    op.execute("""INSERT INTO system_settings (key, value, type, category, description, is_required, is_editable, default_value, labels, created_at, updated_at) VALUES
    ('system_log_level', to_json('DEBUG'::text), 'STRING', 'LOGGING', '系统日志级别', true, true, to_json('INFO'::text), '{"options": ["DEBUG", "INFO", "WARN", "ERROR", "FATAL"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('app_log_level', to_json('DEBUG'::text), 'STRING', 'LOGGING', '应用日志级别', true, true, to_json('INFO'::text), '{"options": ["DEBUG", "INFO", "WARN", "ERROR", "FATAL"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('log_format', to_json('text'::text), 'STRING', 'LOGGING', '日志格式', true, true, to_json('text'::text), '{"options": ["text", "json", "syslog"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('log_retention_days', to_json(7::integer), 'INTEGER', 'LOGGING', '日志存储天数', true, true, to_json(7::integer), '{"options": [7, 30, 90, 180, 365]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_log_rotation', to_json(true::boolean), 'BOOLEAN', 'LOGGING', '启用日志轮转', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('log_rotation_type', to_json('time'::text), 'STRING', 'LOGGING', '日志轮转类型', true, true, to_json('time'::text), '{"options": ["size", "time"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('log_file_size', to_json(100::integer), 'INTEGER', 'LOGGING', '日志文件大小（MB）', true, true, to_json(100::integer), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('output_to_file', to_json(true::boolean), 'BOOLEAN', 'LOGGING', '输出到文件', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('output_to_console', to_json(true::boolean), 'BOOLEAN', 'LOGGING', '输出到控制台', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('output_to_syslog', to_json(false::boolean), 'BOOLEAN', 'LOGGING', '输出到Syslog', false, true, to_json(false::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('output_to_elk', to_json(false::boolean), 'BOOLEAN', 'LOGGING', '输出到ELK', false, true, to_json(false::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    
    # Maintenance Settings
    op.execute("""INSERT INTO system_settings (key, value, type, category, description, is_required, is_editable, default_value, labels, created_at, updated_at) VALUES
    ('enable_auto_backup', to_json(true::boolean), 'BOOLEAN', 'MAINTENANCE', '启用自动备份', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('backup_frequency_maintenance', to_json('weekly'::text), 'STRING', 'MAINTENANCE', '备份频率', true, true, to_json('daily'::text), '{"options": ["daily", "weekly", "monthly"]}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('backup_retention_count', to_json(7::integer), 'INTEGER', 'MAINTENANCE', '备份保留份数', true, true, to_json(7::integer), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_incremental_backup', to_json(true::boolean), 'BOOLEAN', 'MAINTENANCE', '启用增量备份', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_backup_encryption', to_json(true::boolean), 'BOOLEAN', 'MAINTENANCE', '启用备份加密', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_auto_update', to_json(true::boolean), 'BOOLEAN', 'MAINTENANCE', '自动检查更新', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_auto_install_update', to_json(false::boolean), 'BOOLEAN', 'MAINTENANCE', '自动安装更新', false, true, to_json(false::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_auto_restart', to_json(true::boolean), 'BOOLEAN', 'MAINTENANCE', '启用自动重启', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_auto_clean_temp_files', to_json(true::boolean), 'BOOLEAN', 'MAINTENANCE', '自动清理临时文件', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('enable_auto_clean_log_files', to_json(true::boolean), 'BOOLEAN', 'MAINTENANCE', '自动清理日志文件', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    
    # Integration Settings
    op.execute("""INSERT INTO system_settings (key, value, type, category, description, is_required, is_editable, default_value, labels, created_at, updated_at) VALUES
    ('enable_api_access', to_json(true::boolean), 'BOOLEAN', 'INTEGRATION', '启用API访问', false, true, to_json(true::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('api_key', to_json('sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'::text), 'STRING', 'INTEGRATION', 'API密钥', true, true, to_json('sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'::text), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('integrate_prometheus', to_json(false::boolean), 'BOOLEAN', 'INTEGRATION', '集成Prometheus', false, true, to_json(false::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('integrate_grafana', to_json(false::boolean), 'BOOLEAN', 'INTEGRATION', '集成Grafana', false, true, to_json(false::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('integrate_ldap', to_json(false::boolean), 'BOOLEAN', 'INTEGRATION', '集成LDAP', false, true, to_json(false::boolean), null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)


def downgrade() -> None:
    # Drop system_settings table
    op.drop_index(op.f('ix_system_settings_category'), table_name='system_settings')
    op.drop_index(op.f('ix_system_settings_key'), table_name='system_settings')
    op.drop_index(op.f('ix_system_settings_id'), table_name='system_settings')
    op.drop_index('idx_system_settings_deleted_at_created_at', table_name='system_settings')
    op.drop_table('system_settings')
