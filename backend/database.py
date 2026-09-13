import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from config import settings

logger = logging.getLogger(__name__)

DATABASE_URL = settings.DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()

def run_db_migrations():
    """
    Ensures new verification and user columns exist on PostgreSQL / SQLite tables and defaults existing alarms to multi_step with 3 questions.
    """
    migration_sqls = [
        "ALTER TABLE alarms ADD COLUMN IF NOT EXISTS verification_method VARCHAR(50) DEFAULT 'multi_step';",
        "ALTER TABLE alarms ADD COLUMN IF NOT EXISTS verification_steps INTEGER DEFAULT 3;",
        "ALTER TABLE alarms ADD COLUMN IF NOT EXISTS required_accuracy FLOAT DEFAULT 67.0;",
        "ALTER TABLE alarms ADD COLUMN IF NOT EXISTS consecutive_required INTEGER DEFAULT 2;",
        "ALTER TABLE alarms ADD COLUMN IF NOT EXISTS time_limit INTEGER DEFAULT 20;",
        "ALTER TABLE alarms ADD COLUMN IF NOT EXISTS snooze_duration INTEGER DEFAULT 5;",
        "ALTER TABLE alarms ADD COLUMN IF NOT EXISTS max_snoozes INTEGER DEFAULT 3;",
        "ALTER TABLE challenge_attempts ADD COLUMN IF NOT EXISTS verification_status VARCHAR(50) DEFAULT 'passed';",
        "ALTER TABLE challenge_attempts ADD COLUMN IF NOT EXISTS session_id VARCHAR(100);",
        "ALTER TABLE challenge_attempts ADD COLUMN IF NOT EXISTS wakefulness_rating INTEGER;",
        "ALTER TABLE challenge_attempts ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP WITH TIME ZONE;",
        "CREATE TABLE IF NOT EXISTS alarm_snooze_events (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, alarm_id INTEGER NOT NULL, snooze_count INTEGER NOT NULL DEFAULT 1, scheduled_for TIMESTAMP WITH TIME ZONE, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP);",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS target_bedtime VARCHAR(10);",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS target_wake_time VARCHAR(10);",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS inactivity_threshold_minutes INTEGER DEFAULT 30;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_meaningful_activity_at TIMESTAMP WITH TIME ZONE;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS estimated_sleep_start TIMESTAMP WITH TIME ZONE;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS estimated_sleep_end TIMESTAMP WITH TIME ZONE;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_number VARCHAR(30);",
        "CREATE TABLE IF NOT EXISTS notifications (id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, type VARCHAR(50) NOT NULL, title VARCHAR(255) NOT NULL, message VARCHAR(2000) NOT NULL, priority VARCHAR(20) NOT NULL DEFAULT 'normal', is_read BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, scheduled_for TIMESTAMP WITH TIME ZONE, sent_at TIMESTAMP WITH TIME ZONE, expires_at TIMESTAMP WITH TIME ZONE, reference_type VARCHAR(50), reference_id VARCHAR(100), action_url VARCHAR(255), dedup_key VARCHAR(255), delivery_channel VARCHAR(20) DEFAULT 'in_app', delivery_status VARCHAR(20) DEFAULT 'delivered', email_status VARCHAR(30), sms_status VARCHAR(30));",
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS delivery_channel VARCHAR(20) DEFAULT 'in_app';",
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS delivery_status VARCHAR(20) DEFAULT 'delivered';",
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS email_status VARCHAR(30);",
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS sms_status VARCHAR(30);",
        "CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications (user_id);",
        "CREATE INDEX IF NOT EXISTS ix_notifications_type ON notifications (type);",
        "CREATE INDEX IF NOT EXISTS ix_notifications_is_read ON notifications (is_read);",
        "CREATE INDEX IF NOT EXISTS ix_notifications_dedup_key ON notifications (dedup_key);",
        "CREATE TABLE IF NOT EXISTS platform_announcements (id SERIAL PRIMARY KEY, title VARCHAR(255) NOT NULL, message VARCHAR(3000) NOT NULL, priority VARCHAR(20) NOT NULL DEFAULT 'normal', is_active BOOLEAN NOT NULL DEFAULT TRUE, start_time TIMESTAMP WITH TIME ZONE, end_time TIMESTAMP WITH TIME ZONE, created_by INTEGER REFERENCES users(id) ON DELETE SET NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP);",
        "CREATE TABLE IF NOT EXISTS user_notification_preferences (id SERIAL PRIMARY KEY, user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE, bedtime_reminders BOOLEAN NOT NULL DEFAULT TRUE, wake_up_reminders BOOLEAN NOT NULL DEFAULT TRUE, habit_alerts BOOLEAN NOT NULL DEFAULT TRUE, challenge_reminders BOOLEAN NOT NULL DEFAULT TRUE, progress_notifications BOOLEAN NOT NULL DEFAULT TRUE, platform_announcements BOOLEAN NOT NULL DEFAULT TRUE, browser_notifications_enabled BOOLEAN NOT NULL DEFAULT FALSE, preferred_channel VARCHAR(20) DEFAULT 'both', bedtime_email BOOLEAN DEFAULT TRUE, bedtime_sms BOOLEAN DEFAULT FALSE, wakeup_email BOOLEAN DEFAULT TRUE, wakeup_sms BOOLEAN DEFAULT TRUE, habit_email BOOLEAN DEFAULT TRUE, habit_sms BOOLEAN DEFAULT FALSE, challenge_email BOOLEAN DEFAULT TRUE, challenge_sms BOOLEAN DEFAULT FALSE, progress_email BOOLEAN DEFAULT TRUE, progress_sms BOOLEAN DEFAULT FALSE, announcement_email BOOLEAN DEFAULT TRUE, announcement_sms BOOLEAN DEFAULT FALSE, bedtime_lead_minutes INTEGER DEFAULT 30, wakeup_lead_minutes INTEGER DEFAULT 10, report_delivery_enabled BOOLEAN DEFAULT FALSE, report_delivery_channel VARCHAR(20) DEFAULT 'email', report_delivery_frequency VARCHAR(20) DEFAULT 'weekly', report_delivery_type VARCHAR(50) DEFAULT 'habit', created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP);",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS preferred_channel VARCHAR(20) DEFAULT 'both';",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS bedtime_email BOOLEAN DEFAULT TRUE;",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS bedtime_sms BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS wakeup_email BOOLEAN DEFAULT TRUE;",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS wakeup_sms BOOLEAN DEFAULT TRUE;",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS habit_email BOOLEAN DEFAULT TRUE;",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS habit_sms BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS challenge_email BOOLEAN DEFAULT TRUE;",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS challenge_sms BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS progress_email BOOLEAN DEFAULT TRUE;",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS progress_sms BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS announcement_email BOOLEAN DEFAULT TRUE;",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS announcement_sms BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS bedtime_lead_minutes INTEGER DEFAULT 30;",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS wakeup_lead_minutes INTEGER DEFAULT 10;",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS report_delivery_enabled BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS report_delivery_channel VARCHAR(20) DEFAULT 'email';",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS report_delivery_frequency VARCHAR(20) DEFAULT 'weekly';",
        "ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS report_delivery_type VARCHAR(50) DEFAULT 'habit';",
        "UPDATE alarms SET verification_method = 'multi_step', verification_steps = 3, required_accuracy = 67.0 WHERE verification_method IS NULL OR verification_method = '' OR verification_method = 'puzzle_completion' OR verification_steps <= 1;"
    ]

    for sql in migration_sqls:
        try:
            with engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
        except Exception as ex:
            logger.debug(f"Migration statement note for '{sql}': {ex}")

    logger.info("Database schema verification columns and user columns migration check complete.")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()