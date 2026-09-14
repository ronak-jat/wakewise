import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, func
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    """
    User Model matching PostgreSQL table design:
    - id: Primary Key
    - name: User Name
    - email: Unique Email
    - password: Encrypted Password (BCrypt)
    - role: USER / Wellness Coach / Administrator
    - provider: LOCAL or GOOGLE
    - created_at: Creation Timestamp
    - updated_at: Update Timestamp
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="USER")
    provider = Column(String(50), nullable=False, default="LOCAL")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    target_bedtime = Column(String(10), nullable=True, default=None)
    target_wake_time = Column(String(10), nullable=True, default=None)
    phone_number = Column(String(30), nullable=True, default=None)
    inactivity_threshold_minutes = Column(Integer, nullable=False, default=30)
    last_meaningful_activity_at = Column(DateTime(timezone=True), nullable=True)
    estimated_sleep_start = Column(DateTime(timezone=True), nullable=True)
    estimated_sleep_end = Column(DateTime(timezone=True), nullable=True)

    # Relationship to Alarms and Activities
    alarms = relationship("Alarm", back_populates="user", cascade="all, delete-orphan")
    challenge_attempts = relationship("ChallengeAttempt", back_populates="user", cascade="all, delete-orphan")
    snooze_events = relationship("AlarmSnoozeEvent", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    notification_preferences = relationship("UserNotificationPreference", back_populates="user", uselist=False, cascade="all, delete-orphan")
    coach_assigned_users = relationship("CoachUserAssignment", foreign_keys="[CoachUserAssignment.coach_id]", back_populates="coach", cascade="all, delete-orphan")
    user_coach_assignments = relationship("CoachUserAssignment", foreign_keys="[CoachUserAssignment.user_id]", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, name='{self.name}', email='{self.email}', role='{self.role}')>"

class Alarm(Base):
    """
    Alarm Model:
    - id: Primary Key
    - user_id: Foreign Key to User
    - title: Alarm Name
    - alarm_time: Trigger Time (24H format, e.g., "07:30")
    - alarm_type: Daily, Weekday, Weekend, One-Time, Smart Adaptive
    - repeat_days: Comma-separated repeating days (e.g. "Mon,Tue,Wed")
    - is_active: Enabled/Disabled state
    - difficulty_level: Beginner, Easy, Medium, Difficult, Advanced
    - sound: Alarm tone name
    - vibration: Vibration pattern
    - created_at: Timestamp of creation
    - updated_at: Timestamp of update
    """
    __tablename__ = "alarms"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(100), nullable=False)
    alarm_time = Column(String(50), nullable=False)
    alarm_type = Column(String(50), nullable=False, default="One-Time")
    repeat_days = Column(String(100), nullable=False, default="")
    is_active = Column(Boolean, nullable=False, default=True)
    challenge = Column(String(50), nullable=False, default="None")
    difficulty_level = Column(String(50), nullable=False, default="Medium")
    sound = Column(String(100), nullable=False, default="Radar")
    vibration = Column(String(50), nullable=False, default="Standard")
    snooze_duration = Column(Integer, nullable=False, default=5)
    max_snoozes = Column(Integer, nullable=False, default=3)
    # Wake-Up Verification Settings
    verification_method = Column(String(50), nullable=False, default="multi_step") # multi_step, puzzle_completion, consecutive_correct, time_based, accuracy_check
    verification_steps = Column(Integer, nullable=False, default=3)
    required_accuracy = Column(Integer, nullable=False, default=67) # Percentage (e.g. 67 for 2/3)
    consecutive_required = Column(Integer, nullable=False, default=2)
    time_limit = Column(Integer, nullable=False, default=20) # Seconds

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="alarms")
    challenge_attempts = relationship("ChallengeAttempt", back_populates="alarm", cascade="all, delete-orphan")
    snooze_events = relationship("AlarmSnoozeEvent", back_populates="alarm", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Alarm(id={self.id}, title='{self.title}', user_id={self.user_id}, time='{self.alarm_time}', method='{self.verification_method}', active={self.is_active})>"

class ChallengeAttempt(Base):
    """
    Challenge Attempt Model:
    Logs every user challenge interaction, validation result, and timer stats.
    - id: Primary Key
    - user_id: Foreign Key to User
    - alarm_id: Foreign Key to Alarm (nullable if standalone challenge)
    - challenge_type: Math Problems, Logic Puzzles, etc.
    - difficulty: Beginner, Easy, Medium, Difficult, Advanced
    - question: Challenge text/question
    - correct_answer: Expected answer
    - user_answer: User submitted answer
    - is_correct: True if correct, False if wrong/timeout
    - attempt_number: 1, 2, 3...
    - time_taken: Seconds taken to respond
    - time_limit: Configured time limit (40s, 30s, 20s, 15s, 10s)
    - verification_status: pending, in_progress, passed, failed, timeout
    - session_id: Verification session tracking ID
    - created_at: Creation Timestamp
    """
    __tablename__ = "challenge_attempts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    alarm_id = Column(Integer, ForeignKey("alarms.id", ondelete="SET NULL"), nullable=True, index=True)
    challenge_type = Column(String(100), nullable=False)
    difficulty = Column(String(50), nullable=False)
    question = Column(String(500), nullable=False)
    correct_answer = Column(String(255), nullable=False)
    user_answer = Column(String(255), nullable=False, default="")
    is_correct = Column(Boolean, nullable=False, default=False)
    attempt_number = Column(Integer, nullable=False, default=1)
    time_taken = Column(Integer, nullable=False, default=0) # Float/Integer seconds
    time_limit = Column(Integer, nullable=False, default=20)
    verification_status = Column(String(50), nullable=False, default="in_progress") # pending, in_progress, passed, failed, timeout
    session_id = Column(String(100), nullable=True)
    wakefulness_rating = Column(Integer, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="challenge_attempts")
    alarm = relationship("Alarm", back_populates="challenge_attempts")

    def __repr__(self):
        return f"<ChallengeAttempt(id={self.id}, user_id={self.user_id}, type='{self.challenge_type}', difficulty='{self.difficulty}', status='{self.verification_status}', correct={self.is_correct})>"


class AlarmSnoozeEvent(Base):
    """Stores each snooze action as a persisted event so analytics stays accurate across restarts."""
    __tablename__ = "alarm_snooze_events"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    alarm_id = Column(Integer, ForeignKey("alarms.id", ondelete="CASCADE"), nullable=False, index=True)
    snooze_count = Column(Integer, nullable=False, default=1)
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="snooze_events")
    alarm = relationship("Alarm", back_populates="snooze_events")

    def __repr__(self):
        return f"<AlarmSnoozeEvent(id={self.id}, user_id={self.user_id}, alarm_id={self.alarm_id}, snooze_count={self.snooze_count})>"


class Notification(Base):
    """
    Requirement 11 Notification Model:
    Stores user reminders, habit alerts, cognitive challenge prompts, progress updates, and platform announcements.
    """
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    type = Column(String(50), nullable=False, index=True) # bedtime, wake_up, habit_alert, challenge, progress, platform_announcement
    title = Column(String(255), nullable=False)
    message = Column(String(2000), nullable=False)
    priority = Column(String(20), nullable=False, default="normal") # low, normal, high, urgent
    is_read = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    reference_type = Column(String(50), nullable=True) # alarm, habit, challenge, sleep, announcement, streak
    reference_id = Column(String(100), nullable=True)
    action_url = Column(String(255), nullable=True)
    dedup_key = Column(String(255), nullable=True, index=True)
    delivery_channel = Column(String(20), nullable=False, default="in_app") # in_app, email, sms, both
    delivery_status = Column(String(20), nullable=False, default="delivered") # scheduled, sent, delivered, failed, cancelled
    email_status = Column(String(30), nullable=True, default=None) # sent, delivered, failed, unconfigured, disabled
    sms_status = Column(String(30), nullable=True, default=None) # sent, delivered, failed, unconfigured, disabled, no_phone

    user = relationship("User", back_populates="notifications")

    def __repr__(self):
        return f"<Notification(id={self.id}, user_id={self.user_id}, type='{self.type}', title='{self.title}', is_read={self.is_read})>"


class PlatformAnnouncement(Base):
    """
    Admin-controlled broadcast platform announcements.
    """
    __tablename__ = "platform_announcements"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    message = Column(String(3000), nullable=False)
    priority = Column(String(20), nullable=False, default="normal") # low, normal, high, urgent
    target_role = Column(String(50), nullable=False, default="all") # all, user, coach, admin
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<PlatformAnnouncement(id={self.id}, title='{self.title}', target_role='{self.target_role}', active={self.is_active}, priority='{self.priority}')>"


class UserNotificationPreference(Base):
    """
    User-configurable preferences controlling notification category delivery.
    """
    __tablename__ = "user_notification_preferences"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    bedtime_reminders = Column(Boolean, nullable=False, default=True)
    wake_up_reminders = Column(Boolean, nullable=False, default=True)
    habit_alerts = Column(Boolean, nullable=False, default=True)
    challenge_reminders = Column(Boolean, nullable=False, default=True)
    progress_notifications = Column(Boolean, nullable=False, default=True)
    platform_announcements = Column(Boolean, nullable=False, default=True)
    browser_notifications_enabled = Column(Boolean, nullable=False, default=False)

    # Multi-Channel Delivery Matrix & Preferences
    preferred_channel = Column(String(20), nullable=False, default="both") # email, sms, both, disabled
    bedtime_email = Column(Boolean, nullable=False, default=True)
    bedtime_sms = Column(Boolean, nullable=False, default=False)
    wakeup_email = Column(Boolean, nullable=False, default=True)
    wakeup_sms = Column(Boolean, nullable=False, default=True)
    habit_email = Column(Boolean, nullable=False, default=True)
    habit_sms = Column(Boolean, nullable=False, default=False)
    challenge_email = Column(Boolean, nullable=False, default=True)
    challenge_sms = Column(Boolean, nullable=False, default=False)
    progress_email = Column(Boolean, nullable=False, default=True)
    progress_sms = Column(Boolean, nullable=False, default=False)
    announcement_email = Column(Boolean, nullable=False, default=True)
    announcement_sms = Column(Boolean, nullable=False, default=False)

    # Timing / Lead Times
    bedtime_lead_minutes = Column(Integer, nullable=False, default=30)
    wakeup_lead_minutes = Column(Integer, nullable=False, default=10)

    # Report Delivery Settings
    report_delivery_enabled = Column(Boolean, nullable=False, default=False)
    report_delivery_channel = Column(String(20), nullable=False, default="email") # email, sms, both
    report_delivery_frequency = Column(String(20), nullable=False, default="weekly") # weekly, monthly
    report_delivery_type = Column(String(50), nullable=False, default="habit") # habit, wakeup, challenge, sleep, all

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="notification_preferences")

    def __repr__(self):
        return f"<UserNotificationPreference(user_id={self.user_id}, preferred_channel='{self.preferred_channel}', bedtime_email={self.bedtime_email}, wakeup_sms={self.wakeup_sms})>"


class CoachUserAssignment(Base):
    """
    Coach-to-User Assignment Relationship:
    Enforces strict access control and boundaries so coaches can ONLY view, monitor,
    and message users explicitly assigned to them by an Administrator.
    - id: Primary Key
    - coach_id: Foreign Key to User (Role: Coach)
    - user_id: Foreign Key to User (Role: User)
    - assigned_at: Timestamp of assignment
    - assigned_by: Foreign Key to User (Admin who created assignment)
    - is_active: Active/Inactive state of assignment
    """
    __tablename__ = "coach_user_assignments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    coach_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    assigned_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    # Relationships
    coach = relationship("User", foreign_keys=[coach_id], back_populates="coach_assigned_users")
    user = relationship("User", foreign_keys=[user_id], back_populates="user_coach_assignments")
    assigner = relationship("User", foreign_keys=[assigned_by])

    def __repr__(self):
        return f"<CoachUserAssignment(id={self.id}, coach_id={self.coach_id}, user_id={self.user_id}, is_active={self.is_active})>"
