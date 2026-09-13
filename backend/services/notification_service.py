import logging
from datetime import datetime, timedelta, timezone, date
from typing import Dict, List, Any, Optional, Union
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from models import (
    User,
    Alarm,
    ChallengeAttempt,
    AlarmSnoozeEvent,
    Notification,
    PlatformAnnouncement,
    UserNotificationPreference,
)
from services.habit_score_service import calculate_habit_score_snapshot
from services.delivery_service import send_email_notification, send_sms_notification

logger = logging.getLogger("notification_service")


def format_time_ago(dt: Optional[datetime]) -> str:
    """Formats a datetime into a human-readable relative string."""
    if not dt:
        return "Recently"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    secs = int(delta.total_seconds())

    if secs < 60:
        return "Just now"
    if secs < 3600:
        mins = secs // 60
        return f"{mins}m ago"
    if secs < 86400:
        hrs = secs // 3600
        return f"{hrs}h ago"
    days = secs // 86400
    if days == 1:
        return "Yesterday"
    if days < 7:
        return f"{days}d ago"
    return dt.strftime("%b %d")


def get_or_create_user_preferences(db: Session, user_id: int) -> UserNotificationPreference:
    """Fetches user notification preferences or creates standard default preferences."""
    pref = db.query(UserNotificationPreference).filter(UserNotificationPreference.user_id == user_id).first()
    if not pref:
        pref = UserNotificationPreference(
            user_id=user_id,
            bedtime_reminders=True,
            wake_up_reminders=True,
            habit_alerts=True,
            challenge_reminders=True,
            progress_notifications=True,
            platform_announcements=True,
            browser_notifications_enabled=False,
            preferred_channel="both",
            bedtime_email=True,
            bedtime_sms=False,
            wakeup_email=True,
            wakeup_sms=True,
            habit_email=True,
            habit_sms=False,
            challenge_email=True,
            challenge_sms=False,
            progress_email=True,
            progress_sms=False,
            announcement_email=True,
            announcement_sms=False,
            bedtime_lead_minutes=30,
            wakeup_lead_minutes=10,
            report_delivery_enabled=False,
            report_delivery_channel="email",
            report_delivery_frequency="weekly",
            report_delivery_type="habit"
        )
        db.add(pref)
        db.commit()
        db.refresh(pref)
    return pref


def _insert_notification_if_unique(
    db: Session,
    user: User,
    notif_type: str,
    title: str,
    message: str,
    priority: str = "normal",
    reference_type: Optional[str] = None,
    reference_id: Optional[str] = None,
    action_url: Optional[str] = None,
    dedup_key: Optional[str] = None,
    scheduled_for: Optional[datetime] = None,
    email_enabled: bool = False,
    sms_enabled: bool = False,
) -> Optional[Notification]:
    """
    Inserts a notification only if it does not already exist with the same dedup_key.
    Dispatches via active channels (Email, SMS) and records delivery audit statuses.
    """
    if dedup_key:
        existing = db.query(Notification).filter(Notification.dedup_key == dedup_key).first()
        if existing:
            return None

    now = datetime.now(timezone.utc)
    email_status = None
    sms_status = None
    delivery_status = "delivered"

    # Determine delivery channel tag
    if email_enabled and sms_enabled:
        delivery_channel = "both"
    elif email_enabled:
        delivery_channel = "email"
    elif sms_enabled:
        delivery_channel = "sms"
    else:
        delivery_channel = "in_app"

    # 1. Dispatch Email if enabled
    if email_enabled and user.email:
        email_res = send_email_notification(
            to_email=user.email,
            subject=f"[WakeWise AI] {title}",
            body_text=message
        )
        email_status = email_res.get("status", "unconfigured")
    elif email_enabled:
        email_status = "failed"

    # 2. Dispatch SMS if enabled
    if sms_enabled:
        sms_text = f"WakeWise AI: {title}\n{message}"
        sms_res = send_sms_notification(
            to_phone=user.phone_number,
            message=sms_text
        )
        sms_status = sms_res.get("status", "unconfigured")

    # Evaluate aggregate delivery status
    if delivery_channel != "in_app":
        statuses = [s for s in [email_status, sms_status] if s is not None]
        if any(s in ("delivered", "sent") for s in statuses):
            delivery_status = "delivered"
        elif all(s == "failed" for s in statuses):
            delivery_status = "failed"
        elif all(s in ("unconfigured", "no_phone") for s in statuses):
            delivery_status = "unconfigured"
        else:
            delivery_status = "delivered"

    notif = Notification(
        user_id=user.id,
        type=notif_type,
        title=title,
        message=message,
        priority=priority,
        is_read=False,
        reference_type=reference_type,
        reference_id=str(reference_id) if reference_id is not None else None,
        action_url=action_url,
        dedup_key=dedup_key,
        scheduled_for=scheduled_for,
        sent_at=now,
        created_at=now,
        delivery_channel=delivery_channel,
        delivery_status=delivery_status,
        email_status=email_status,
        sms_status=sms_status,
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    logger.info(f"Generated notification [{notif_type}] for user {user.id}: '{title}' via {delivery_channel} (status: {delivery_status}, dedup: {dedup_key})")
    return notif


# 1. Bedtime Reminders
def _evaluate_bedtime_reminders(db: Session, user: User, prefs: UserNotificationPreference, now: datetime):
    if not prefs.bedtime_reminders or prefs.preferred_channel == "disabled":
        return

    today_str = now.strftime("%Y-%m-%d")
    dedup_key = f"user:{user.id}:bedtime:{today_str}"

    bedtime_str = user.target_bedtime
    is_estimate = False

    if not bedtime_str and user.estimated_sleep_start:
        if user.estimated_sleep_start.tzinfo is not None:
            local_sleep = user.estimated_sleep_start.astimezone()
        else:
            local_sleep = user.estimated_sleep_start
        bedtime_str = local_sleep.strftime("%H:%M")
        is_estimate = True

    if not bedtime_str:
        bedtime_str = "23:00"  # Platform baseline target

    try:
        b_h, b_m = map(int, bedtime_str.split(":"))
        target_mins = b_h * 60 + b_m
        curr_mins = now.hour * 60 + now.minute
        lead_mins = getattr(prefs, "bedtime_lead_minutes", 30) or 30

        # Send notification if within configured lead window
        diff_mins = target_mins - curr_mins
        is_approaching = (0 <= diff_mins <= lead_mins + 30) or (curr_mins >= target_mins - lead_mins and curr_mins <= target_mins + 30)

        if is_approaching or now.hour >= 20:
            disclaimer = " (Estimated from phone inactivity)" if is_estimate else ""
            title = "Bedtime Reminder"
            message = f"Your recommended bedtime is approaching at {bedtime_str}{disclaimer}. Start winding down for better sleep consistency."

            email_on = bool(prefs.bedtime_email and prefs.preferred_channel in ("email", "both"))
            sms_on = bool(prefs.bedtime_sms and prefs.preferred_channel in ("sms", "both"))

            _insert_notification_if_unique(
                db=db,
                user=user,
                notif_type="bedtime",
                title=title,
                message=message,
                priority="normal",
                reference_type="sleep",
                reference_id=today_str,
                action_url="user/habits.html",
                dedup_key=dedup_key,
                email_enabled=email_on,
                sms_enabled=sms_on,
            )
    except Exception as e:
        logger.debug(f"Error evaluating bedtime reminder for user {user.id}: {e}")


# 2. Wake-Up Reminders
def _evaluate_wakeup_reminders(db: Session, user: User, prefs: UserNotificationPreference, now: datetime):
    if not prefs.wake_up_reminders or prefs.preferred_channel == "disabled":
        return

    today_name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][now.weekday()]
    today_is_weekend = now.weekday() in (5, 6)
    today_str = now.strftime("%Y-%m-%d")
    lead_mins = getattr(prefs, "wakeup_lead_minutes", 10) or 10

    active_alarms = db.query(Alarm).filter(Alarm.user_id == user.id, Alarm.is_active == True).all()

    for alarm in active_alarms:
        is_scheduled_today = False
        if alarm.alarm_type in ("Daily", "One-Time", "Smart Adaptive"):
            is_scheduled_today = True
        elif alarm.alarm_type in {"Weekday", "Weekdays"}:
            is_scheduled_today = not today_is_weekend
        elif alarm.alarm_type in {"Weekend", "Weekends"}:
            is_scheduled_today = today_is_weekend
        else:
            days = [d.strip() for d in alarm.repeat_days.split(",") if d.strip()]
            is_scheduled_today = today_name in days

        if not is_scheduled_today:
            continue

        try:
            a_h, a_m = map(int, alarm.alarm_time.split(":"))
            alarm_mins = a_h * 60 + a_m
            curr_mins = now.hour * 60 + now.minute
            diff_mins = alarm_mins - curr_mins

            dedup_key = f"user:{user.id}:wakeup:{alarm.id}:{today_str}"
            if 0 <= diff_mins <= lead_mins + 20 or (diff_mins <= 0 and curr_mins <= alarm_mins + 10):
                title = f"Upcoming Alarm: {alarm.title}"
                message = f"Your alarm '{alarm.title}' is scheduled for {alarm.alarm_time}. Prepare for your cognitive wake-up challenge ({alarm.challenge or 'Multi-Step Verification'})."

                email_on = bool(prefs.wakeup_email and prefs.preferred_channel in ("email", "both"))
                sms_on = bool(prefs.wakeup_sms and prefs.preferred_channel in ("sms", "both"))

                _insert_notification_if_unique(
                    db=db,
                    user=user,
                    notif_type="wake_up",
                    title=title,
                    message=message,
                    priority="high",
                    reference_type="alarm",
                    reference_id=str(alarm.id),
                    action_url="user/alarms.html",
                    dedup_key=dedup_key,
                    email_enabled=email_on,
                    sms_enabled=sms_on,
                )
        except Exception as e:
            logger.debug(f"Error evaluating wake-up reminder for alarm {alarm.id}: {e}")


# 3. Habit Alerts
def _evaluate_habit_alerts(db: Session, user: User, prefs: UserNotificationPreference, now: datetime):
    if not prefs.habit_alerts or prefs.preferred_channel == "disabled":
        return

    year_week_str = now.strftime("%Y-W%W")
    snap = calculate_habit_score_snapshot(db, user.id, period_days=7)

    email_on = bool(prefs.habit_email and prefs.preferred_channel in ("email", "both"))
    sms_on = bool(prefs.habit_sms and prefs.preferred_channel in ("sms", "both"))

    # 3a. Excessive Snoozing Alert
    snooze_sub = snap.get("sub_scores", {}).get("snooze_reduction", 100.0)
    recent_snoozes = (
        db.query(AlarmSnoozeEvent)
        .filter(
            AlarmSnoozeEvent.user_id == user.id,
            AlarmSnoozeEvent.created_at >= now - timedelta(days=7),
        )
        .count()
    )

    if (snooze_sub < 60.0 or recent_snoozes >= 3) and recent_snoozes > 0:
        dedup_key = f"user:{user.id}:habit_alert_snooze:{year_week_str}"
        _insert_notification_if_unique(
            db=db,
            user=user,
            notif_type="habit_alert",
            title="Snooze Habit Alert",
            message=f"Your snooze count has increased this week ({recent_snoozes} snooze events logged). Try keeping your first alarm as your final wake-up.",
            priority="high",
            reference_type="habit",
            reference_id="snooze",
            action_url="user/habits.html",
            dedup_key=dedup_key,
            email_enabled=email_on,
            sms_enabled=sms_on,
        )

    # 3b. Wake-Up Schedule Inconsistency Alert
    consist_sub = snap.get("sub_scores", {}).get("wake_up_consistency", 100.0)
    if consist_sub < 60.0:
        dedup_key = f"user:{user.id}:habit_alert_consistency:{year_week_str}"
        _insert_notification_if_unique(
            db=db,
            user=user,
            notif_type="habit_alert",
            title="Wake-Up Inconsistency Alert",
            message="Your wake-up schedule has been inconsistent recently. Sticking to a regular wake-up window helps stabilize morning alertness.",
            priority="normal",
            reference_type="habit",
            reference_id="consistency",
            action_url="user/habits.html",
            dedup_key=dedup_key,
            email_enabled=email_on,
            sms_enabled=sms_on,
        )

    # 3c. Sleep Schedule Adherence Alert
    sleep_sub = snap.get("sub_scores", {}).get("sleep_schedule_adherence", 100.0)
    if sleep_sub < 60.0 and user.target_bedtime:
        dedup_key = f"user:{user.id}:habit_alert_sleep:{year_week_str}"
        _insert_notification_if_unique(
            db=db,
            user=user,
            notif_type="habit_alert",
            title="Sleep Schedule Alert",
            message="Your sleep schedule has been inconsistent recently. Establishing a relaxing pre-sleep routine can improve bedtime adherence.",
            priority="normal",
            reference_type="habit",
            reference_id="sleep_schedule",
            action_url="user/habits.html",
            dedup_key=dedup_key,
            email_enabled=email_on,
            sms_enabled=sms_on,
        )


# 4. Challenge Reminders
def _evaluate_challenge_reminders(db: Session, user: User, prefs: UserNotificationPreference, now: datetime):
    if not prefs.challenge_reminders or prefs.preferred_channel == "disabled":
        return

    today_str = now.strftime("%Y-%m-%d")
    dedup_key = f"user:{user.id}:challenge_remind:{today_str}"

    user_alarms = db.query(Alarm).filter(Alarm.user_id == user.id, Alarm.is_active == True).all()
    if user_alarms:
        sample_alarm = user_alarms[0]
        v_method = sample_alarm.verification_method or "multi_step"
        c_type = sample_alarm.challenge or "Math Problems"

        email_on = bool(prefs.challenge_email and prefs.preferred_channel in ("email", "both"))
        sms_on = bool(prefs.challenge_sms and prefs.preferred_channel in ("sms", "both"))

        _insert_notification_if_unique(
            db=db,
            user=user,
            notif_type="challenge",
            title="Cognitive Challenge Scheduled",
            message=f"Your '{sample_alarm.title}' alarm includes a {c_type} verification puzzle ({v_method.replace('_', ' ').title()}). Solve it upon ringing to silence the tone.",
            priority="normal",
            reference_type="challenge",
            reference_id=str(sample_alarm.id),
            action_url="user/challenges.html",
            dedup_key=dedup_key,
            email_enabled=email_on,
            sms_enabled=sms_on,
        )


# 5. Progress Notifications
def _evaluate_progress_notifications(db: Session, user: User, prefs: UserNotificationPreference, now: datetime):
    if not prefs.progress_notifications or prefs.preferred_channel == "disabled":
        return

    today_str = now.strftime("%Y-%m-%d")
    year_week_str = now.strftime("%Y-W%W")

    snap = calculate_habit_score_snapshot(db, user.id, period_days=7)
    streak = snap.get("current_streak", 0)
    score = snap.get("habit_score", 0.0)

    email_on = bool(prefs.progress_email and prefs.preferred_channel in ("email", "both"))
    sms_on = bool(prefs.progress_sms and prefs.preferred_channel in ("sms", "both"))

    # 5a. Consecutive Wake-Up Streak Milestones (e.g. 3, 7, 14, 21, 30 days)
    if streak >= 3 and (streak == 3 or streak % 7 == 0 or streak == 5):
        dedup_key = f"user:{user.id}:progress_streak_{streak}:{today_str}"
        _insert_notification_if_unique(
            db=db,
            user=user,
            notif_type="progress",
            title="Wake-Up Streak Milestone!",
            message=f"Great progress! You completed {streak} consecutive successful wake-ups without missing your schedule.",
            priority="high",
            reference_type="streak",
            reference_id=str(streak),
            action_url="user/dashboard-user.html",
            dedup_key=dedup_key,
            email_enabled=email_on,
            sms_enabled=sms_on,
        )

    # 5b. Habit Score Improvement
    prev_snap = calculate_habit_score_snapshot(db, user.id, period_days=14)
    prev_score = prev_snap.get("habit_score", score)
    if score >= prev_score + 4.0 and score >= 65.0:
        dedup_key = f"user:{user.id}:progress_habit_score:{year_week_str}"
        delta = round(score - prev_score, 1)
        _insert_notification_if_unique(
            db=db,
            user=user,
            notif_type="progress",
            title="Habit Score Improvement!",
            message=f"Great progress! Your Habit Score improved by +{delta} points this week (Current: {round(score, 1)}/100).",
            priority="high",
            reference_type="habit",
            reference_id="habit_score",
            action_url="user/dashboard-user.html",
            dedup_key=dedup_key,
            email_enabled=email_on,
            sms_enabled=sms_on,
        )

    # 5c. High Challenge Accuracy
    attempts = (
        db.query(ChallengeAttempt)
        .filter(
            ChallengeAttempt.user_id == user.id,
            ChallengeAttempt.created_at >= now - timedelta(days=7),
        )
        .all()
    )
    if len(attempts) >= 3:
        correct_count = sum(1 for a in attempts if a.is_correct)
        acc = (correct_count / len(attempts)) * 100.0
        if acc >= 80.0:
            dedup_key = f"user:{user.id}:progress_accuracy_{round(acc)}:{year_week_str}"
            _insert_notification_if_unique(
                db=db,
                user=user,
                notif_type="progress",
                title="Cognitive Accuracy Peak!",
                message=f"Sharp cognitive performance! You achieved {round(acc, 1)}% accuracy across {len(attempts)} wake-up challenges this week.",
                priority="normal",
                reference_type="challenge",
                reference_id="accuracy",
                action_url="user/analytics.html",
                dedup_key=dedup_key,
                email_enabled=email_on,
                sms_enabled=sms_on,
            )


# 6. Platform Announcements Sync
def _evaluate_platform_announcements(db: Session, user: User, prefs: UserNotificationPreference, now: datetime):
    if not prefs.platform_announcements or prefs.preferred_channel == "disabled":
        return

    active_announcements = (
        db.query(PlatformAnnouncement)
        .filter(PlatformAnnouncement.is_active == True)
        .order_by(desc(PlatformAnnouncement.created_at))
        .all()
    )

    email_on = bool(prefs.announcement_email and prefs.preferred_channel in ("email", "both"))
    sms_on = bool(prefs.announcement_sms and prefs.preferred_channel in ("sms", "both"))

    for ann in active_announcements:
        if ann.start_time and ann.start_time > now:
            continue
        if ann.end_time and ann.end_time < now:
            continue

        dedup_key = f"user:{user.id}:announcement:{ann.id}"
        _insert_notification_if_unique(
            db=db,
            user=user,
            notif_type="platform_announcement",
            title=f"Announcement: {ann.title}",
            message=ann.message,
            priority=ann.priority or "normal",
            reference_type="announcement",
            reference_id=str(ann.id),
            action_url="user/notifications.html",
            dedup_key=dedup_key,
            email_enabled=email_on,
            sms_enabled=sms_on,
        )


# 7. Scheduled Report Delivery Integration
def dispatch_scheduled_report_notification(
    db: Session,
    user: User,
    report_type: str = "habit",
    download_url: Optional[str] = None
) -> Optional[Notification]:
    """
    Sends scheduled report notifications via configured channels (Email, SMS link).
    """
    prefs = get_or_create_user_preferences(db, user.id)
    if not prefs.report_delivery_enabled or prefs.preferred_channel == "disabled":
        return None

    channel = prefs.report_delivery_channel or "email"
    email_on = channel in ("email", "both")
    sms_on = channel in ("sms", "both")

    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    report_name = f"{report_type.replace('_', ' ').title()} Analytics Report"
    link_str = download_url or f"/user/analytics.html?report={report_type}"

    title = f"Scheduled Report Ready: {report_name}"
    message = f"Your scheduled {report_name} for {today_str} has been generated and is ready for review. Access link: {link_str}"
    dedup_key = f"user:{user.id}:report_{report_type}:{today_str}"

    return _insert_notification_if_unique(
        db=db,
        user=user,
        notif_type="report_delivery",
        title=title,
        message=message,
        priority="normal",
        reference_type="report",
        reference_id=report_type,
        action_url=link_str,
        dedup_key=dedup_key,
        email_enabled=email_on,
        sms_enabled=sms_on,
    )


def broadcast_announcements_to_users(db: Session, now_dt: Optional[datetime] = None):
    """
    Broadcasts all active announcements to all active users.
    """
    now = now_dt or datetime.now(timezone.utc)
    users = db.query(User).all()
    for u in users:
        prefs = get_or_create_user_preferences(db, u.id)
        _evaluate_platform_announcements(db, u, prefs, now)


def evaluate_user_notifications(db: Session, user: Any, now_dt: Optional[datetime] = None) -> List[Notification]:
    """
    Evaluates real user data across all 6 notification categories.
    Idempotent and safe to run on every notification fetch and periodic scheduler loop.
    """
    if not user:
        return []

    if isinstance(user, int):
        user_obj = db.query(User).filter(User.id == user).first()
        if not user_obj:
            return []
        user = user_obj

    now = now_dt or datetime.now(timezone.utc)
    prefs = get_or_create_user_preferences(db, user.id)

    _evaluate_bedtime_reminders(db, user, prefs, now)
    _evaluate_wakeup_reminders(db, user, prefs, now)
    _evaluate_habit_alerts(db, user, prefs, now)
    _evaluate_challenge_reminders(db, user, prefs, now)
    _evaluate_progress_notifications(db, user, prefs, now)
    _evaluate_platform_announcements(db, user, prefs, now)

    # Return top recent notifications for the user
    return (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(desc(Notification.created_at))
        .limit(50)
        .all()
    )
