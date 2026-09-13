import asyncio
import datetime
import logging
import uuid
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

async def alarm_scheduler_loop():
    """
    Background loop checking active alarms every 30 seconds.
    """
    logger.info("Background Alarm Scheduler Service started.")
    triggered_cache = set()

    while True:
        try:
            db = SessionLocal()
            now = datetime.datetime.now()
            due_snoozes = [item for item in scheduled_snoozes if item["due_at"] <= now]
            for item in due_snoozes:
                _trigger_snoozed_alarm(db, item)
                scheduled_snoozes.remove(item)
            today_name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][now.weekday()]
            today_is_weekend = now.weekday() in (5, 6)
            current_time_str = now.strftime("%H:%M")
            today_str = now.strftime("%Y-%m-%d")

            cache_to_keep = {item for item in triggered_cache if item[1] == today_str}
            triggered_cache.intersection_update(cache_to_keep)

            active_alarms = db.query(Alarm).filter(Alarm.is_active == True).all()

            for alarm in active_alarms:
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
                    days = [d.strip() for d in alarm.repeat_days.split(",") if d.strip()]
                    is_scheduled_today = today_name in days

                if not is_scheduled_today:
                    continue

                target_time = alarm.alarm_time
                adaptive_info = None

                if alarm.alarm_type == "Smart Adaptive":
                    metrics = check_user_wellness_metrics(db, alarm.user_id)
                    adaptive_info = evaluate_smart_adaptive_rules(alarm, metrics)
                    target_time = adaptive_info["adjusted_time"]

                cache_key = (alarm.id, today_str, target_time)
                if current_time_str == target_time and cache_key not in triggered_cache:
                    triggered_cache.add(cache_key)

                    if alarm.alarm_type == "One-Time":
                        deactivate_one_time_alarm_if_needed(db, alarm)

                    # Query Adaptive Difficulty Engine for personalized difficulty and challenge type
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

                    # Challenge Type from recommendation
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

                    triggered_alarms.append({
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
                    })

                    print("\n" + "="*80)
                    print(f"[ALARM TRIGGERED] Timestamp: {now.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"Alarm ID: {alarm.id} | User ID: {alarm.user_id} | Label: {alarm.title}")
                    print(f"Trigger Time: {target_time} (Configured: {alarm.alarm_time})")
                    print(f"Customization: Sound={alarm.sound if not adaptive_info else adaptive_info['sound']}, "
                          f"Vibration={alarm.vibration}, Difficulty={diff_level}")
                    print(f"Adaptive Difficulty Engine: Level='{diff_level}', Type='{normalized_type}'")
                    print(f"Reason: {rec['reason']}")
                    print(f"Cognitive Challenge Attached: ID='{challenge_payload.get('id')}', Type='{challenge_payload.get('type')}', Question='{challenge_payload.get('question')}'")

                    if adaptive_info:
                        print("Smart Adaptive Rules Applied:")
                        for rule in adaptive_info["rules_applied"]:
                            print(f"  - {rule}")
                    print("="*80 + "\n")

                    logger.info(f"Alarm '{alarm.title}' (ID: {alarm.id}) triggered with personalized {diff_level} challenge for User {alarm.user_id} at {target_time}")

            # Periodically evaluate reminders and alerts for active users
            try:
                active_users = db.query(User).all()
                for u in active_users:
                    evaluate_user_notifications(db, u, now)
            except Exception as notif_err:
                logger.debug(f"Notification evaluation note: {notif_err}")

            db.close()
        except Exception as e:
            logger.error(f"Error in alarm scheduler loop: {e}")

        await asyncio.sleep(30)
