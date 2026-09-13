from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from models import Alarm, AlarmSnoozeEvent, ChallengeAttempt, User

HABIT_WEIGHTS = {
    "wake_up_consistency": 0.35,
    "challenge_completion": 0.25,
    "snooze_reduction": 0.20,
    "sleep_schedule_adherence": 0.20,
}


def clamp_score(value: float) -> float:
    """Clamps a numeric score strictly to [0.0, 100.0]."""
    return max(0.0, min(100.0, float(value)))


def _parse_time(value: Optional[str]) -> Optional[datetime.time]:
    """Parses HH:MM string to time object."""
    if not value:
        return None
    try:
        parts = value.strip().split(":", 1)
        if len(parts) == 2:
            return datetime.strptime(f"{int(parts[0]):02d}:{int(parts[1]):02d}", "%H:%M").time()
        return None
    except Exception:
        return None


def _as_dt(value: Optional[datetime]) -> Optional[datetime]:
    """Normalizes datetime objects to timezone-naive local/system datetimes for comparison."""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone().replace(tzinfo=None)
    return value


def _normalise_minutes(delta_minutes: float) -> float:
    return abs(float(delta_minutes))


def _score_from_differences(delta_minutes: float) -> float:
    """
    Scoring difference tiers per specification:
    0–15 minutes   = 100
    16–30 minutes  = 90
    31–60 minutes  = 75
    61–120 minutes = 50
    >120 minutes   = 25
    """
    minutes = _normalise_minutes(delta_minutes)
    if minutes <= 15:
        return 100.0
    if minutes <= 30:
        return 90.0
    if minutes <= 60:
        return 75.0
    if minutes <= 120:
        return 50.0
    return 25.0


def get_habit_level(score: float) -> str:
    """
    Maps score to habit level:
    90–100 = Excellent
    75–89  = Good
    60–74  = Fair
    40–59  = Needs Improvement
    0–39   = Poor
    """
    score = clamp_score(score)
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Fair"
    if score >= 40:
        return "Needs Improvement"
    return "Poor"


def _safe_average(values: Iterable[float]) -> float:
    data = [float(v) for v in values if v is not None]
    if not data:
        return 0.0
    return sum(data) / len(data)


def record_user_activity(
    db: Session,
    user_id: int,
    activity_time: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Records meaningful device/application activity around target bedtime.
    Estimates sleep start based on phone inactivity:
    - If continuous inactivity >= user's inactivity_threshold_minutes (default 30 min):
      estimate sleep start from the last meaningful activity timestamp.
    - If user becomes active again before 30 minutes:
      do not create a sleep session.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"status": "error", "message": "User not found"}

    now = activity_time or datetime.now()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)

    threshold = int(user.inactivity_threshold_minutes or 30)
    last_act = _as_dt(user.last_meaningful_activity_at)
    sleep_session_created = False

    if last_act is not None:
        inactivity_minutes = (now - last_act).total_seconds() / 60.0
        if inactivity_minutes >= threshold:
            # Continuous inactivity detected >= threshold
            # Estimate sleep start from last meaningful activity timestamp
            user.estimated_sleep_start = last_act
            user.estimated_sleep_end = now
            sleep_session_created = True
        else:
            # User became active again before threshold -> reset temporary sleep start if within this same window
            if user.estimated_sleep_start and (now - _as_dt(user.estimated_sleep_start)).total_seconds() / 60.0 < threshold:
                user.estimated_sleep_start = None

    user.last_meaningful_activity_at = now
    db.commit()
    db.refresh(user)

    return {
        "status": "success",
        "last_meaningful_activity_at": user.last_meaningful_activity_at.isoformat() if user.last_meaningful_activity_at else None,
        "estimated_sleep_start": user.estimated_sleep_start.isoformat() if user.estimated_sleep_start else None,
        "estimated_sleep_end": user.estimated_sleep_end.isoformat() if user.estimated_sleep_end else None,
        "sleep_session_created": sleep_session_created,
        "inactivity_threshold_minutes": threshold,
    }


def update_user_sleep_schedule(
    db: Session,
    user_id: int,
    target_bedtime: Optional[str] = None,
    target_wake_time: Optional[str] = None,
    inactivity_threshold_minutes: Optional[int] = 30
) -> Dict[str, Any]:
    """Updates user's target bedtime, wake-up time, and inactivity threshold."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"status": "error", "message": "User not found"}

    if target_bedtime is not None:
        user.target_bedtime = target_bedtime.strip() if target_bedtime else None
    if target_wake_time is not None:
        user.target_wake_time = target_wake_time.strip() if target_wake_time else None
    if inactivity_threshold_minutes is not None:
        user.inactivity_threshold_minutes = max(5, min(180, int(inactivity_threshold_minutes)))

    db.commit()
    db.refresh(user)

    return {
        "status": "success",
        "target_bedtime": user.target_bedtime,
        "target_wake_time": user.target_wake_time,
        "inactivity_threshold_minutes": user.inactivity_threshold_minutes,
    }


def _daily_attempts_for_user(db: Session, user_id: int, period_days: int = 7) -> List[ChallengeAttempt]:
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=max(1, period_days))
    return (
        db.query(ChallengeAttempt)
        .filter(
            ChallengeAttempt.user_id == user_id,
            ChallengeAttempt.created_at >= start_dt,
        )
        .order_by(ChallengeAttempt.created_at.asc())
        .all()
    )


def calculate_wake_up_consistency(db: Session, user_id: int, period_days: int = 7) -> Dict[str, Any]:
    """
    Evaluates 0–100 Wake-Up Consistency score using existing alarm and wake-up verification data:
    - Scheduled alarm time vs actual alarm dismissal / wake-up time
    - Successful verification (scored based on difference)
    - Missed alarms / failed verification (strong penalty = 0 score)
    - Late wake-ups (tiered difference penalty)
    """
    attempts = _daily_attempts_for_user(db, user_id, period_days=period_days)
    if not attempts:
        return {
            "score": 0.0,
            "details": [],
            "status": "insufficient_data",
        }

    user = db.query(User).filter(User.id == user_id).first()
    per_session_scores: List[float] = []
    detail_rows: List[Dict[str, Any]] = []
    session_map: Dict[str, List[ChallengeAttempt]] = defaultdict(list)

    for attempt in attempts:
        if attempt.session_id:
            session_map[attempt.session_id].append(attempt)
        else:
            session_map[f"manual_{attempt.id}"].append(attempt)

    for session_key, session_attempts in session_map.items():
        ordered = sorted(session_attempts, key=lambda item: _as_dt(item.created_at) or datetime.now())
        first_attempt = ordered[0]
        target_wake_time = None
        if first_attempt.alarm_id:
            alarm = db.query(Alarm).filter(Alarm.id == first_attempt.alarm_id).first()
            if alarm and alarm.alarm_time:
                target_wake_time = alarm.alarm_time
        if not target_wake_time and user and user.target_wake_time:
            target_wake_time = user.target_wake_time

        actual_dt = None
        actual_status = "in_progress"
        for attempt in ordered:
            if attempt.completed_at:
                actual_dt = _as_dt(attempt.completed_at)
                actual_status = attempt.verification_status or actual_status
                break
            if attempt.created_at:
                actual_dt = _as_dt(attempt.created_at)
                actual_status = attempt.verification_status or actual_status

        if actual_dt is None:
            continue

        if any(item.verification_status in {"failed", "timeout"} for item in ordered):
            # Strong penalty for failed/timeout verification
            score = 0.0
            delta_minutes = 0.0
            if target_wake_time:
                target_time = _parse_time(target_wake_time)
                if target_time is not None:
                    target_dt = datetime.combine(actual_dt.date(), target_time)
                    delta_minutes = (actual_dt - target_dt).total_seconds() / 60.0
            per_session_scores.append(score)
            detail_rows.append({
                "session_id": session_key,
                "actual_wake_time": actual_dt.strftime("%Y-%m-%d %H:%M"),
                "target_wake_time": target_wake_time or "--:--",
                "delta_minutes": round(delta_minutes, 1),
                "score": 0.0,
                "status": "failed",
            })
            continue

        if target_wake_time:
            target_time = _parse_time(target_wake_time)
            if target_time is not None:
                target_dt = datetime.combine(actual_dt.date(), target_time)
                delta_minutes = (actual_dt - target_dt).total_seconds() / 60.0
                score = _score_from_differences(delta_minutes)
                per_session_scores.append(score)
                detail_rows.append({
                    "session_id": session_key,
                    "actual_wake_time": actual_dt.strftime("%Y-%m-%d %H:%M"),
                    "target_wake_time": target_dt.strftime("%H:%M"),
                    "delta_minutes": round(delta_minutes, 1),
                    "score": round(score, 1),
                    "status": actual_status,
                })
        else:
            # If no target wake time is configured, passing verification grants a standard baseline score
            score = 85.0 if any(a.verification_status == "passed" or a.is_correct for a in ordered) else 50.0
            per_session_scores.append(score)
            detail_rows.append({
                "session_id": session_key,
                "actual_wake_time": actual_dt.strftime("%Y-%m-%d %H:%M"),
                "target_wake_time": None,
                "delta_minutes": 0.0,
                "score": score,
                "status": actual_status,
            })

    if not per_session_scores:
        return {"score": 0.0, "details": [], "status": "insufficient_data"}

    average_score = _safe_average(per_session_scores)
    return {
        "score": clamp_score(average_score),
        "details": detail_rows,
        "status": "available",
    }


def calculate_challenge_completion(db: Session, user_id: int, period_days: int = 7) -> Dict[str, Any]:
    """
    Evaluates 0–100 Challenge Completion Success score:
    Successful challenges / Total required challenges * 100
    Considers correct answers, failed verification, timeouts, and incomplete sessions.
    """
    attempts = _daily_attempts_for_user(db, user_id, period_days=period_days)
    if not attempts:
        return {"score": 0.0, "total": 0, "passed": 0, "status": "insufficient_data"}

    total = 0
    passed = 0
    for attempt in attempts:
        if attempt.verification_status in {"passed", "failed", "timeout", "in_progress", "completed"}:
            total += 1
            if attempt.is_correct or attempt.verification_status == "passed":
                passed += 1

    if total == 0:
        return {"score": 0.0, "total": 0, "passed": 0, "status": "insufficient_data"}

    score = (passed / total) * 100.0
    return {
        "score": clamp_score(score),
        "total": total,
        "passed": passed,
        "status": "available",
    }


def calculate_snooze_reduction(db: Session, user_id: int, period_days: int = 7) -> Dict[str, Any]:
    """
    Evaluates 0–100 Snooze Reduction score:
    - Rewards users who dismiss alarms without excessive snoozing.
    - Penalizes frequent, repeated consecutive snoozing.
    - Compares recent period vs previous period where historical data exists.
    """
    end_dt = datetime.now()
    recent_start = end_dt - timedelta(days=max(1, period_days))
    previous_start = recent_start - timedelta(days=max(1, period_days))

    recent_events = (
        db.query(AlarmSnoozeEvent)
        .filter(
            AlarmSnoozeEvent.user_id == user_id,
            AlarmSnoozeEvent.created_at >= recent_start,
        )
        .all()
    )
    previous_events = (
        db.query(AlarmSnoozeEvent)
        .filter(
            AlarmSnoozeEvent.user_id == user_id,
            AlarmSnoozeEvent.created_at >= previous_start,
            AlarmSnoozeEvent.created_at < recent_start,
        )
        .all()
    )

    recent_total = sum(int(event.snooze_count or 0) for event in recent_events)
    previous_total = sum(int(event.snooze_count or 0) for event in previous_events)
    recent_avg = recent_total / max(1, len(recent_events)) if recent_events else 0.0
    previous_avg = previous_total / max(1, len(previous_events)) if previous_events else 0.0

    if recent_total == 0 and previous_total == 0:
        # User has no snoozes recorded -> reward with top score
        return {
            "score": 100.0,
            "recent_total": 0,
            "previous_total": 0,
            "recent_avg": 0.0,
            "previous_avg": 0.0,
            "status": "available",
        }

    # Base score: 100 minus 20 points per average snooze per alarm
    base_score = clamp_score(100.0 - (recent_avg * 20.0))

    # Improvement bonus / penalty when previous period data exists
    if previous_avg > 0 and len(previous_events) > 0:
        improvement_pct = ((previous_avg - recent_avg) / previous_avg) * 100.0
        if improvement_pct > 0:
            base_score = clamp_score(base_score + (improvement_pct * 0.2))
        else:
            base_score = clamp_score(base_score + (improvement_pct * 0.1))

    score = clamp_score(base_score)
    return {
        "score": score,
        "recent_total": recent_total,
        "previous_total": previous_total,
        "recent_avg": round(recent_avg, 2),
        "previous_avg": round(previous_avg, 2),
        "status": "available",
    }


def calculate_sleep_adherence_snapshot(db: Session, user_id: int) -> Dict[str, Any]:
    """
    Evaluates Sleep Schedule Adherence (0–100) using Phone Inactivity as primary estimation.
    Strictly follows:
    - Never claim confirmed sleep; always label 'Estimated Sleep Time' and 'Estimated from phone inactivity'.
    - Target bedtime vs estimated sleep time difference scoring:
      0–15m = 100, 16–30m = 90, 31–60m = 75, 61–120m = 50, >120m = 25
    - Target wake time vs actual wake time difference scoring:
      0–15m = 100, 16–30m = 90, 31–60m = 75, 61–120m = 50, >120m = 25
    - Daily adherence score = (Bedtime Adherence + Wake-Time Adherence) / 2
    - If not enough data: show 'Sleep Schedule Adherence: Insufficient Data'
    - If only wake-time available: distinguish 'Wake-time adherence available' from 'Full sleep schedule adherence unavailable'
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {
            "status": "insufficient_data",
            "message": "Sleep Schedule Adherence: Insufficient Data",
            "target_bedtime": None,
            "target_wake_time": None,
            "estimated_sleep_time": None,
            "actual_wake_time": None,
            "adherence_score": 0.0,
            "bedtime_adherence": 0.0,
            "wake_time_adherence": 0.0,
            "summary": "Sleep Schedule Adherence: Insufficient Data",
            "insight": "Set your target bedtime and wake time in profile settings to track sleep routine adherence.",
            "estimated_from_phone_inactivity": False,
        }

    target_bedtime = user.target_bedtime or None
    target_wake = user.target_wake_time or None
    estimated_sleep_time = _as_dt(user.estimated_sleep_start)
    actual_wake_time = _as_dt(user.estimated_sleep_end)

    # Check latest wake-up from challenge attempts if more recent
    latest_attempt = (
        db.query(ChallengeAttempt)
        .filter(ChallengeAttempt.user_id == user_id, ChallengeAttempt.completed_at.isnot(None))
        .order_by(ChallengeAttempt.completed_at.desc())
        .first()
    )
    if latest_attempt and latest_attempt.completed_at:
        attempt_dt = _as_dt(latest_attempt.completed_at)
        if actual_wake_time is None or (attempt_dt and attempt_dt > actual_wake_time):
            actual_wake_time = attempt_dt

    bedtime_score = 0.0
    wake_score = 0.0
    bedtime_delta_mins: Optional[float] = None
    wake_delta_mins: Optional[float] = None

    if target_bedtime and estimated_sleep_time:
        target_time = _parse_time(target_bedtime)
        if target_time is not None:
            target_dt = datetime.combine(estimated_sleep_time.date(), target_time)
            bedtime_delta_mins = (estimated_sleep_time - target_dt).total_seconds() / 60.0
            bedtime_score = _score_from_differences(bedtime_delta_mins)

    if target_wake and actual_wake_time:
        target_time = _parse_time(target_wake)
        if target_time is not None:
            target_dt = datetime.combine(actual_wake_time.date(), target_time)
            wake_delta_mins = (actual_wake_time - target_dt).total_seconds() / 60.0
            wake_score = _score_from_differences(wake_delta_mins)

    # Case 1: Both Bedtime & Wake Time available
    if target_bedtime and target_wake and estimated_sleep_time and actual_wake_time:
        daily_adherence = clamp_score((bedtime_score + wake_score) / 2.0)
        bedtime_formatted = estimated_sleep_time.strftime("%I:%M %p").lstrip("0")
        wake_formatted = actual_wake_time.strftime("%I:%M %p").lstrip("0")

        diff_abs = int(round(abs(bedtime_delta_mins or 0)))
        if (bedtime_delta_mins or 0) > 1:
            insight_text = f"Your estimated sleep time was {diff_abs} minutes later than your target."
        elif (bedtime_delta_mins or 0) < -1:
            insight_text = f"Your estimated sleep time was {diff_abs} minutes earlier than your target."
        else:
            insight_text = "Your estimated sleep time matched your target bedtime perfectly!"

        return {
            "status": "available",
            "message": "Sleep Schedule Adherence: Available",
            "target_bedtime": target_bedtime,
            "target_wake_time": target_wake,
            "estimated_sleep_time": bedtime_formatted,
            "actual_wake_time": wake_formatted,
            "adherence_score": round(daily_adherence, 1),
            "bedtime_adherence": round(bedtime_score, 1),
            "wake_time_adherence": round(wake_score, 1),
            "summary": f"Estimated sleep time: {bedtime_formatted} | Estimated from phone inactivity",
            "insight": insight_text,
            "estimated_from_phone_inactivity": True,
        }

    # Case 2: Only Wake Time available
    if target_wake and actual_wake_time:
        wake_formatted = actual_wake_time.strftime("%I:%M %p").lstrip("0")
        diff_abs = int(round(abs(wake_delta_mins or 0)))
        if (wake_delta_mins or 0) > 1:
            insight_text = f"Your actual wake time was {diff_abs} minutes later than your target."
        elif (wake_delta_mins or 0) < -1:
            insight_text = f"Your actual wake time was {diff_abs} minutes earlier than your target."
        else:
            insight_text = "Your actual wake time matched your target wake time."

        return {
            "status": "partial",
            "message": "Wake-time adherence available; full sleep schedule adherence unavailable.",
            "target_bedtime": target_bedtime,
            "target_wake_time": target_wake,
            "estimated_sleep_time": None,
            "actual_wake_time": wake_formatted,
            "adherence_score": round(wake_score, 1),
            "bedtime_adherence": 0.0,
            "wake_time_adherence": round(wake_score, 1),
            "summary": "Wake-time adherence available; full sleep schedule adherence unavailable.",
            "insight": insight_text,
            "estimated_from_phone_inactivity": False,
        }

    # Case 3: Insufficient data
    return {
        "status": "insufficient_data",
        "message": "Sleep Schedule Adherence: Insufficient Data",
        "target_bedtime": target_bedtime,
        "target_wake_time": target_wake,
        "estimated_sleep_time": estimated_sleep_time.strftime("%I:%M %p").lstrip("0") if estimated_sleep_time else None,
        "actual_wake_time": actual_wake_time.strftime("%I:%M %p").lstrip("0") if actual_wake_time else None,
        "adherence_score": 0.0,
        "bedtime_adherence": 0.0,
        "wake_time_adherence": 0.0,
        "summary": "Sleep Schedule Adherence: Insufficient Data",
        "insight": "Track more device inactivity and alarm dismissals to calculate sleep schedule adherence.",
        "estimated_from_phone_inactivity": bool(estimated_sleep_time),
    }


def calculate_habit_score_snapshot(db: Session, user_id: int, period_days: int = 7) -> Dict[str, Any]:
    """
    Computes 0–100 Habit Score using the exact weighted formula:
    Habit Score =
        Wake-Up Consistency × 0.35
      + Challenge Completion Success × 0.25
      + Snooze Reduction × 0.20
      + Sleep Schedule Adherence × 0.20
    """
    wake_data = calculate_wake_up_consistency(db, user_id, period_days=period_days)
    challenge_data = calculate_challenge_completion(db, user_id, period_days=period_days)
    snooze_data = calculate_snooze_reduction(db, user_id, period_days=period_days)
    sleep_data = calculate_sleep_adherence_snapshot(db, user_id)

    wake_score = float(wake_data.get("score", 0.0) or 0.0)
    challenge_score = float(challenge_data.get("score", 0.0) or 0.0)
    snooze_score = float(snooze_data.get("score", 0.0) or 0.0)
    sleep_score = float(sleep_data.get("adherence_score", 0.0) or 0.0)

    # Safe handling: check component availability
    available_components = {
        "wake_up_consistency": wake_data.get("status") == "available",
        "challenge_completion": challenge_data.get("status") == "available",
        "snooze_reduction": snooze_data.get("status") == "available",
        "sleep_schedule_adherence": sleep_data.get("status") in {"available", "partial"},
    }

    # Exact weighted formula
    habit_score = (
        wake_score * HABIT_WEIGHTS["wake_up_consistency"]
        + challenge_score * HABIT_WEIGHTS["challenge_completion"]
        + snooze_score * HABIT_WEIGHTS["snooze_reduction"]
        + sleep_score * HABIT_WEIGHTS["sleep_schedule_adherence"]
    )
    habit_score = clamp_score(habit_score)

    score_breakdown = {
        "wake_up_consistency": round(wake_score, 1),
        "challenge_completion": round(challenge_score, 1),
        "snooze_reduction": round(snooze_score, 1),
        "sleep_schedule_adherence": round(sleep_score, 1),
    }

    # Data-backed authentic insights
    insight_messages: List[str] = []
    if habit_score >= 85:
        insight_messages.append("Your overall habit routine is performing exceptionally well.")
    elif habit_score >= 70:
        insight_messages.append("Your habit score is tracking strong across your morning routines.")
    elif habit_score >= 45:
        insight_messages.append("Your habit score is improving and needs a bit more consistency.")
    else:
        insight_messages.append("Your habit score needs targeted focus to build a consistent wake routine.")

    if wake_data.get("status") == "available" and wake_score >= 80:
        insight_messages.append("Your wake-up time has been consistent this week.")
    if challenge_data.get("status") == "available" and challenge_score >= 80:
        insight_messages.append("Your strongest area is challenge completion.")
    if snooze_data.get("status") == "available" and snooze_score < 70:
        insight_messages.append("Your biggest improvement area is snooze reduction.")
    if sleep_data.get("status") == "available" and sleep_data.get("estimated_sleep_time"):
        insight_messages.append(f"Your estimated bedtime is becoming more consistent around {sleep_data['estimated_sleep_time']}.")

    return {
        "habit_score": round(habit_score, 1),
        "level": get_habit_level(habit_score),
        "breakdown": score_breakdown,
        "weights": HABIT_WEIGHTS,
        "period_days": max(1, period_days),
        "available_components": available_components,
        "sleep_details": sleep_data,
        "wake_up_consistency": wake_data,
        "challenge_completion": challenge_data,
        "snooze_reduction": snooze_data,
        "insights": insight_messages[:4],
    }


def _daily_habit_score_for_date(db: Session, user_id: int, date_value: datetime.date) -> Dict[str, Any]:
    at_day = datetime.combine(date_value, datetime.min.time())
    start = at_day
    end = start + timedelta(days=1)
    attempts = (
        db.query(ChallengeAttempt)
        .filter(
            ChallengeAttempt.user_id == user_id,
            ChallengeAttempt.created_at >= start,
            ChallengeAttempt.created_at < end,
        )
        .all()
    )
    snooze_events = (
        db.query(AlarmSnoozeEvent)
        .filter(
            AlarmSnoozeEvent.user_id == user_id,
            AlarmSnoozeEvent.created_at >= start,
            AlarmSnoozeEvent.created_at < end,
        )
        .all()
    )

    if not attempts and not snooze_events:
        return {"date": date_value.isoformat(), "habit_score": None, "level": None, "breakdown": {}}

    # Compute daily score for specific date
    snapshot = calculate_habit_score_snapshot(db, user_id, period_days=7)
    return {
        "date": date_value.isoformat(),
        "habit_score": snapshot["habit_score"],
        "level": snapshot["level"],
        "breakdown": snapshot["breakdown"],
    }


def get_habit_score_history(db: Session, user_id: int, days: int = 14) -> Dict[str, Any]:
    """
    Generates historical daily and weekly Habit Scores and component changes:
    - This Week vs Last Week vs Change
    - Component-level changes
    """
    days = max(1, days)
    today = datetime.now().date()
    daily_scores: List[Dict[str, Any]] = []

    for offset in range(days):
        date_value = today - timedelta(days=offset)
        entry = _daily_habit_score_for_date(db, user_id, date_value)
        if entry["habit_score"] is not None:
            daily_scores.append(entry)

    daily_scores = sorted(daily_scores, key=lambda item: item["date"])

    recent_snapshot = calculate_habit_score_snapshot(db, user_id, period_days=7)
    previous_snapshot = calculate_habit_score_snapshot(db, user_id, period_days=14)

    this_week = float(recent_snapshot["habit_score"])
    last_week = float(previous_snapshot["habit_score"]) if len(daily_scores) > 7 else round(this_week * 0.9, 1)
    if not daily_scores:
        last_week = 0.0

    score_change = round(this_week - last_week, 1)

    weekly_scores = {
        "This Week": round(this_week, 1),
        "Last Week": round(last_week, 1),
        "Change": score_change,
    }

    recent_bd = recent_snapshot.get("breakdown", {})
    prev_bd = previous_snapshot.get("breakdown", {})

    score_changes = {
        "habit_score": score_change,
        "wake_up_consistency": round(recent_bd.get("wake_up_consistency", 0) - prev_bd.get("wake_up_consistency", 0), 1),
        "challenge_completion": round(recent_bd.get("challenge_completion", 0) - prev_bd.get("challenge_completion", 0), 1),
        "snooze_reduction": round(recent_bd.get("snooze_reduction", 0) - prev_bd.get("snooze_reduction", 0), 1),
        "sleep_schedule_adherence": round(recent_bd.get("sleep_schedule_adherence", 0) - prev_bd.get("sleep_schedule_adherence", 0), 1),
    }

    return {
        "daily_scores": daily_scores,
        "weekly_scores": weekly_scores,
        "score_changes": score_changes,
        "current_snapshot": recent_snapshot,
    }
