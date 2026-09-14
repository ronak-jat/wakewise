import asyncio
import datetime
import logging
import uuid
from typing import Optional
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Alarm, User

from services.gemini_service import generate_cognitive_challenge, map_challenge_type
from services.challenge_store import add_session, find_session_by_alarm
from services.personalization_service import (
    get_adaptive_recommendation,
    calculate_personalized_difficulty,
    get_time_limit_for_difficulty,
    normalize_difficulty
)
from services.notification_service import evaluate_user_notifications

logger = logging.getLogger("alarm_scheduler")

triggered_alarms = []
scheduled_snoozes = []
_scheduler_task: Optional[asyncio.Task] = None


def schedule_snooze(alarm: Alarm, due_at: datetime.datetime, snooze_count: int) -> None:
    scheduled_snoozes.append({"alarm": alarm, "due_at": due_at, "snooze_count": snooze_count})
    logger.info("Alarm snoozed: alarm_id=%s due_at=%s snooze_count=%s", alarm.id, due_at, snooze_count)


def _trigger_snoozed_alarm(db: Session, item: dict) -> None:
    alarm = item["alarm"]
    rec = get_adaptive_recommendation(
        db=db,
        user_id=alarm.user_id,
        base_difficulty=alarm.difficulty_level or "Medium",
        preferred_type=alarm.challenge
    )
    diff_level = rec["recommended_difficulty"]
    challenge_payload = generate_cognitive_challenge(map_challenge_type(rec["recommended_challenge_type"]), diff_level)
    challenge_payload["id"] = f"chal_{uuid.uuid4().hex[:12]}"
    challenge_payload["user_id"] = alarm.user_id
    challenge_payload["alarm_id"] = alarm.id
    challenge_payload["recommended_difficulty"] = diff_level
    challenge_payload["recommended_challenge_type"] = rec["recommended_challenge_type"]
    challenge_payload["time_limit"] = alarm.time_limit or 20
    challenge_payload["source"] = "scheduler"
    challenge_payload["scheduler_generated"] = True
    challenge_payload["occurrence_id"] = f"snooze_{uuid.uuid4().hex[:12]}"
    add_session(challenge_payload["id"], challenge_payload)
    triggered_alarms.append({
        "id": alarm.id,
        "user_id": alarm.user_id,
        "title": alarm.title,
        "sound": alarm.sound,
        "difficulty": diff_level,
        "time": item["due_at"].strftime("%H:%M"),
        "alarm_type": alarm.alarm_type,
        "challenge_type": rec["recommended_challenge_type"],
        "adaptive_reason": rec["reason"],
        "verification_method": alarm.verification_method or "puzzle_completion",
        "verification_steps": alarm.verification_steps or 1,
        "required_accuracy": alarm.required_accuracy or 100,
        "consecutive_required": alarm.consecutive_required or 1,
        "time_limit": alarm.time_limit or 20,
        "snooze_duration": alarm.snooze_duration or 5,
        "max_snoozes": alarm.max_snoozes if alarm.max_snoozes is not None else 3,
        "snooze_count": item["snooze_count"],
        "occurrence_id": challenge_payload["occurrence_id"],
        "challenge": challenge_payload
    })
    logger.info("Snoozed alarm triggered: alarm_id=%s occurrence_id=%s challenge_id=%s", alarm.id, challenge_payload["occurrence_id"], challenge_payload["id"])


def deactivate_one_time_alarm_if_needed(db_session: Session, alarm: Alarm) -> bool:
    """Disable one-time alarms immediately after they trigger to prevent repeat firings."""
    if alarm.alarm_type == "One-Time" and alarm.is_active:
        alarm.is_active = False
        if db_session is not None:
            db_session.commit()
        return True
    return False


# Mock function simulating checking user sleep/cognitive metrics for smart adaptive alarms
def check_user_wellness_metrics(db_session: Session, user_id: int):
    user = db_session.query(User).filter(User.id == user_id).first()
    if user and user.name.lower() == "john":
        return {
            "sleep_quality_score": 62, # Poor sleep (< 70)
            "sleep_hours": 5.5,        # Low sleep duration (< 6 hrs)
            "cognitive_accuracy": 68   # Low cognitive score (< 70)
        }
    return {
        "sleep_quality_score": 85,
        "sleep_hours": 7.5,
        "cognitive_accuracy": 92
    }

def evaluate_smart_adaptive_rules(alarm: Alarm, metrics: dict):
    """
    Evaluates rule-based adaptive parameters for Smart Adaptive Alarms.
    Returns:
        dict containing adjusted_time, difficulty, sound, and message detailing the rule triggered.
    """
    adjusted_time = alarm.alarm_time
    difficulty = alarm.difficulty_level
    sound = alarm.sound
    rules_applied = []

    # Rule 1: Poor sleep duration (< 6 hours) -> Delay alarm by 15 minutes to guarantee sleep recovery
    if metrics["sleep_hours"] < 6.0:
        try:
            h, m = map(int, alarm.alarm_time.split(":"))
            m += 15
            if m >= 60:
                h = (h + 1) % 24
                m -= 60
            adjusted_time = f"{h:02d}:{m:02d}"
            rules_applied.append(f"Sleep hours low ({metrics['sleep_hours']}h) -> Delayed alarm by +15 mins to {adjusted_time}")
        except Exception as e:
            logger.error(f"Error adjusting time for smart adaptive alarm: {e}")

    # Rule 2: Low cognitive score (< 70) -> Set challenge difficulty to Easy and use Forest Bird tone to mitigate sleep inertia
    if metrics["cognitive_accuracy"] < 70:
        difficulty = "Easy"
        sound = "Forest Bird"
        rules_applied.append(f"Cognitive accuracy low ({metrics['cognitive_accuracy']}%) -> Reduced difficulty to 'Easy', changed tone to 'Forest Bird'")

    # Rule 3: High sleep quality & high cognitive score -> Standby with configured settings
    if not rules_applied:
        rules_applied.append("Circadian metrics normal -> Retained standard configuration")

    return {
        "adjusted_time": adjusted_time,
        "difficulty": difficulty,
        "sound": sound,
        "rules_applied": rules_applied
    }


# Timezone offset cache (offset in minutes from UTC, e.g., +330 for IST)
user_timezone_offsets: dict = {}
triggered_cache: set = set()


def get_user_timezone_offset(user_id: Optional[int]) -> int:
    """
    Returns timezone offset in minutes from UTC for a user.
    Checks:
    1. In-memory user_timezone_offsets registered via frontend requests.
    2. DEFAULT_TIMEZONE_OFFSET environment variable (default: 330 for IST UTC+05:30).
    """
    if user_id is not None and user_id in user_timezone_offsets:
        return user_timezone_offsets[user_id]

    env_offset = os.getenv("DEFAULT_TIMEZONE_OFFSET")
    if env_offset:
        try:
            return int(env_offset)
        except ValueError:
            pass

    tz_env = os.getenv("TZ", "")
    if "kolkata" in tz_env.lower() or "calcutta" in tz_env.lower() or "ist" in tz_env.lower():
        return 330

    return int(os.getenv("DEFAULT_TIMEZONE_OFFSET", "330"))


def get_user_now(user_id: Optional[int]) -> datetime.datetime:
    """Returns datetime localized to the user's specific timezone."""
    offset_min = get_user_timezone_offset(user_id)
    tz = datetime.timezone(datetime.timedelta(minutes=offset_min))
    return datetime.datetime.now(datetime.timezone.utc).astimezone(tz)


def is_alarm_due(alarm: Alarm, user_now: datetime.datetime) -> tuple:
    """
    Evaluates whether an active alarm is due for trigger at the user's localized datetime.
    Returns: (is_due: bool, target_time: str, adaptive_info: Optional[dict])
    """
    today_name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][user_now.weekday()]
    today_is_weekend = user_now.weekday() in (5, 6)

    is_scheduled_today = False
    if alarm.alarm_type == "Daily":
        is_scheduled_today = True
    elif alarm.alarm_type in {"Weekday", "Weekdays"}:
        is_scheduled_today = not today_is_weekend
    elif alarm.alarm_type in {"Weekend", "Weekends"}:
        is_scheduled_today = today_is_weekend
    elif alarm.alarm_type == "One-Time":
        is_scheduled_today = True
    elif alarm.alarm_type == "Smart Adaptive":
        is_scheduled_today = True
    else:
        days = [d.strip() for d in (alarm.repeat_days or "").split(",") if d.strip()]
        is_scheduled_today = today_name in days

    if not is_scheduled_today:
        return False, alarm.alarm_time, None

    target_time = alarm.alarm_time
    adaptive_info = None

    if alarm.alarm_type == "Smart Adaptive":
        try:
            metrics = {"sleep_hours": 7.5, "cognitive_accuracy": 92}
            adaptive_info = evaluate_smart_adaptive_rules(alarm, metrics)
            target_time = adaptive_info["adjusted_time"]
        except Exception:
            target_time = alarm.alarm_time

    today_str = user_now.strftime("%Y-%m-%d")
    cache_key = (alarm.id, today_str, target_time)

    if cache_key in triggered_cache:
        return False, target_time, adaptive_info

    # Minute comparison with 1-minute grace window for loop interval tolerance
    try:
        target_h, target_m = map(int, target_time.split(":"))
        target_minute_of_day = target_h * 60 + target_m
        current_minute_of_day = user_now.hour * 60 + user_now.minute
        minute_diff = current_minute_of_day - target_minute_of_day
    except Exception:
        minute_diff = 999

    due = (0 <= minute_diff <= 1)
    return due, target_time, adaptive_info


def trigger_alarm_for_user(db: Session, alarm: Alarm, user_now: datetime.datetime, adaptive_info: Optional[dict] = None) -> dict:
    """
    Constructs challenge, registers session, adds to triggered_alarms queue, and logs event.
    """
    target_time = adaptive_info["adjusted_time"] if adaptive_info else alarm.alarm_time
    today_str = user_now.strftime("%Y-%m-%d")

    if alarm.alarm_type == "One-Time":
        deactivate_one_time_alarm_if_needed(db, alarm)

    rec = get_adaptive_recommendation(
        db=db,
        user_id=alarm.user_id,
        base_difficulty=alarm.difficulty_level or "Medium",
        preferred_type=alarm.challenge
    )

    if alarm.alarm_type == "Smart Adaptive" and adaptive_info:
        diff_level = adaptive_info["difficulty"]
    else:
        diff_level = rec["recommended_difficulty"]

    ch_type = rec["recommended_challenge_type"]
    normalized_type = map_challenge_type(ch_type)

    existing = find_session_by_alarm(alarm.id, alarm.user_id)
    if existing:
        challenge_payload = existing
    else:
        challenge_payload = generate_cognitive_challenge(normalized_type, diff_level)
        session_id = f"chal_{uuid.uuid4().hex[:12]}"
        challenge_payload["id"] = session_id
        challenge_payload["user_id"] = alarm.user_id
        challenge_payload["recommended_difficulty"] = diff_level
        challenge_payload["recommended_challenge_type"] = ch_type
        challenge_payload["adaptive_reason"] = rec["reason"]
        challenge_payload["alarm_id"] = alarm.id
        challenge_payload["time_limit"] = get_time_limit_for_difficulty(diff_level)
        challenge_payload["source"] = "scheduler"
        challenge_payload["scheduler_generated"] = True
        add_session(session_id, challenge_payload)

    alarm_item = {
        "id": alarm.id,
        "user_id": alarm.user_id,
        "title": alarm.title,
        "sound": adaptive_info["sound"] if adaptive_info else alarm.sound,
        "difficulty": diff_level,
        "time": target_time,
        "alarm_type": alarm.alarm_type,
        "challenge_type": ch_type,
        "adaptive_reason": rec["reason"],
        "verification_method": getattr(alarm, "verification_method", "puzzle_completion") or "puzzle_completion",
        "verification_steps": getattr(alarm, "verification_steps", 1) or 1,
        "required_accuracy": getattr(alarm, "required_accuracy", 100) or 100,
        "consecutive_required": getattr(alarm, "consecutive_required", 1) or 1,
        "time_limit": getattr(alarm, "time_limit", 20) or 20,
        "snooze_duration": getattr(alarm, "snooze_duration", 5) or 5,
        "max_snoozes": getattr(alarm, "max_snoozes", 3) if getattr(alarm, "max_snoozes", None) is not None else 3,
        "snooze_count": 0,
        "occurrence_id": f"alarm_{alarm.id}_{today_str}_{target_time}",
        "challenge": challenge_payload
    }

    triggered_alarms.append(alarm_item)

    logger.info(
        "[ALARM TRIGGERED] Alarm ID=%s (User ID=%s, Title='%s', Time=%s, Difficulty=%s)",
        alarm.id, alarm.user_id, alarm.title, target_time, diff_level
    )
    return alarm_item


def check_and_trigger_user_due_alarms(db: Session, user_id: int, offset_minutes: Optional[int] = None) -> list:
    """
    Checks and triggers any due alarms for a user in real-time when polling.
    Ensures zero latency without waiting for the 30s background loop.
    """
    if offset_minutes is not None:
        user_timezone_offsets[user_id] = offset_minutes

    user_now = get_user_now(user_id)
    user_alarms = db.query(Alarm).filter(Alarm.user_id == user_id, Alarm.is_active == True).all()

    newly_triggered = []
    for alarm in user_alarms:
        due, target_time, adaptive_info = is_alarm_due(alarm, user_now)
        logger.debug(
            "[SCHEDULER] User %d Alarm ID=%d (Target=%s, LocalNow=%s) -> due=%s",
            user_id, alarm.id, target_time, user_now.strftime("%H:%M"), due
        )
        if due:
            today_str = user_now.strftime("%Y-%m-%d")
            cache_key = (alarm.id, today_str, target_time)
            triggered_cache.add(cache_key)
            logger.info(
                "[SCHEDULER] Alarm ID=%d is DUE for User %d (Target=%s, LocalNow=%s)",
                alarm.id, user_id, target_time, user_now.strftime("%H:%M")
            )
            item = trigger_alarm_for_user(db, alarm, user_now, adaptive_info)
            newly_triggered.append(item)

    return newly_triggered


async def alarm_scheduler_loop():
    """
    Background loop checking active alarms every 30 seconds.
    """
    logger.info("[SCHEDULER] Background Alarm Scheduler Service started.")

    while True:
        db = None
        try:
            db = SessionLocal()
            utc_now = datetime.datetime.now(datetime.timezone.utc)

            # Check snoozed alarms
            due_snoozes = [item for item in scheduled_snoozes if item["due_at"] <= utc_now]
            for item in due_snoozes:
                _trigger_snoozed_alarm(db, item)
                scheduled_snoozes.remove(item)

            active_alarms = db.query(Alarm).filter(Alarm.is_active == True).all()
            logger.info("[SCHEDULER] Checked %d active alarms across users.", len(active_alarms))

            # Prune cache to keep only today's entries
            today_date_strs = {
                get_user_now(a.user_id).strftime("%Y-%m-%d") for a in active_alarms
            }
            if not today_date_strs:
                today_date_strs = {utc_now.strftime("%Y-%m-%d")}
            cache_to_keep = {item for item in triggered_cache if item[1] in today_date_strs}
            triggered_cache.intersection_update(cache_to_keep)

            for alarm in active_alarms:
                user_now = get_user_now(alarm.user_id)
                user_time_str = user_now.strftime("%H:%M")
                due, target_time, adaptive_info = is_alarm_due(alarm, user_now)

                logger.debug(
                    "[SCHEDULER] Evaluating Alarm ID=%d for User %d (Target: %s, User Time: %s)...",
                    alarm.id, alarm.user_id, target_time, user_time_str
                )

                if due:
                    today_str = user_now.strftime("%Y-%m-%d")
                    cache_key = (alarm.id, today_str, target_time)
                    triggered_cache.add(cache_key)
                    logger.info(
                        "[SCHEDULER] Alarm ID=%d is DUE (Target: %s, User Time: %s)",
                        alarm.id, target_time, user_time_str
                    )
                    trigger_alarm_for_user(db, alarm, user_now, adaptive_info)
                else:
                    logger.debug(
                        "[SCHEDULER] Alarm ID=%d is not due (Target: %s, User Time: %s)",
                        alarm.id, target_time, user_time_str
                    )

            # Periodically evaluate reminders and alerts for active users
            try:
                active_users = db.query(User).all()
                for u in active_users:
                    u_now = get_user_now(u.id)
                    evaluate_user_notifications(db, u, u_now)
            except Exception as notif_err:
                logger.debug(f"Notification evaluation note: {notif_err}")

        except Exception as e:
            logger.error(f"Error in alarm scheduler loop: {e}")
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    pass

        await asyncio.sleep(30)


async def start_scheduler_if_not_running() -> asyncio.Task:
    """
    Ensures the background alarm scheduler loop starts exactly once.
    Avoids duplicate scheduler tasks if re-triggered.
    """
    global _scheduler_task
    if _scheduler_task is not None and not _scheduler_task.done():
        logger.info("Alarm scheduler loop is already running.")
        return _scheduler_task
    _scheduler_task = asyncio.create_task(alarm_scheduler_loop(), name="wakewise_alarm_scheduler")
    return _scheduler_task


def stop_scheduler_task() -> None:
    """Gracefully cancels the background alarm scheduler loop if running."""
    global _scheduler_task
    if _scheduler_task is not None and not _scheduler_task.done():
        logger.info("Stopping alarm scheduler background task...")
        _scheduler_task.cancel()

