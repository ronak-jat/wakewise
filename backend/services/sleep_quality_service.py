from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, time, date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import desc

from models import Alarm, ChallengeAttempt, User, AlarmSnoozeEvent
from services.habit_score_service import (
    clamp_score,
    _parse_time,
    _as_dt,
    _score_from_differences,
    _safe_average,
)


SLEEP_QUALITY_WEIGHTS = {
    "schedule_adherence": 0.40,
    "sleep_duration": 0.35,
    "consistency": 0.25,
}

DEFAULT_TARGET_SLEEP_DURATION_HOURS = 8.0


def get_sleep_quality_level(score: Optional[float]) -> Optional[str]:
    """
    Maps 0-100 score to Sleep Quality interpretation level:
    90–100 -> Excellent
    75–89  -> Good
    60–74  -> Fair
    40–59  -> Needs Improvement
    0–39   -> Poor
    """
    if score is None:
        return None
    val = clamp_score(score)
    if val >= 90.0:
        return "Excellent"
    if val >= 75.0:
        return "Good"
    if val >= 60.0:
        return "Fair"
    if val >= 40.0:
        return "Needs Improvement"
    return "Poor"


def _time_to_minutes(t: time) -> int:
    """Converts a time object to total minutes from midnight (0-1439)."""
    return t.hour * 60 + t.minute


def _circular_mean_std(minutes_list: List[int]) -> Tuple[float, float]:
    """
    Computes standard deviation of times around a 24h (1440 min) circular day.
    Normalizes bedtime/wake time variances correctly even across midnight (e.g. 23:45 and 00:15).
    """
    if not minutes_list:
        return 0.0, 0.0
    if len(minutes_list) == 1:
        return float(minutes_list[0]), 0.0

    # Shift values relative to the first element to handle midnight wrapping smoothly
    base = minutes_list[0]
    shifted = []
    for m in minutes_list:
        diff = (m - base) % 1440
        if diff > 720:
            diff -= 1440
        shifted.append(base + diff)

    avg_shifted = statistics.mean(shifted) % 1440
    stdev_mins = statistics.stdev(shifted) if len(shifted) > 1 else 0.0
    return avg_shifted, stdev_mins


def _compute_target_duration_hours(user: User) -> float:
    """
    Derives target sleep duration in hours from user's configured target bedtime & wake time,
    or falls back to application default (8.0 hours).
    """
    if user.target_bedtime and user.target_wake_time:
        bed_t = _parse_time(user.target_bedtime)
        wake_t = _parse_time(user.target_wake_time)
        if bed_t and wake_t:
            bed_mins = _time_to_minutes(bed_t)
            wake_mins = _time_to_minutes(wake_t)
            diff_mins = (wake_mins - bed_mins) % 1440
            if diff_mins > 0:
                return round(diff_mins / 60.0, 2)
    return DEFAULT_TARGET_SLEEP_DURATION_HOURS


def _compute_duration_score(actual_hours: float, target_hours: float) -> float:
    """
    Evaluates 0-100 score for sleep duration compared with target sleep duration:
    - Within 30 min of target (<= 0.5h diff) -> 100
    - Within 1 hour (<= 1.0h diff) -> 90
    - Within 1.5 hours (<= 1.5h diff) -> 80
    - Within 2 hours (<= 2.0h diff) -> 65
    - Within 3 hours (<= 3.0h diff) -> 45
    - > 3 hours diff -> 25
    """
    diff_h = abs(actual_hours - target_hours)
    if diff_h <= 0.5:
        return 100.0
    if diff_h <= 1.0:
        return 90.0
    if diff_h <= 1.5:
        return 80.0
    if diff_h <= 2.0:
        return 65.0
    if diff_h <= 3.0:
        return 45.0
    return 25.0


def _compute_consistency_score(std_dev_minutes: float) -> float:
    """
    Evaluates 0-100 score for schedule consistency based on standard deviation of sleep/wake times:
    <= 15 min -> 100
    <= 30 min -> 90
    <= 45 min -> 80
    <= 60 min -> 70
    <= 90 min -> 55
    <= 120 min -> 40
    > 120 min -> 25
    """
    if std_dev_minutes <= 15.0:
        return 100.0
    if std_dev_minutes <= 30.0:
        return 90.0
    if std_dev_minutes <= 45.0:
        return 80.0
    if std_dev_minutes <= 60.0:
        return 70.0
    if std_dev_minutes <= 90.0:
        return 55.0
    if std_dev_minutes <= 120.0:
        return 40.0
    return 25.0


def _extract_daily_sleep_sessions(
    db: Session,
    user: User,
    days: int = 7
) -> List[Dict[str, Any]]:
    """
    Extracts authentic daily sleep/wake timestamps from real PostgreSQL records:
    - Inactivity-based sleep start (User.estimated_sleep_start)
    - Alarm dismissal / wake-up verification completion (ChallengeAttempt.completed_at)
    - User.estimated_sleep_end
    """
    now = datetime.now()
    start_window = now - timedelta(days=max(1, days))

    # Retrieve challenge attempts in the time window
    attempts = (
        db.query(ChallengeAttempt)
        .filter(
            ChallengeAttempt.user_id == user.id,
            ChallengeAttempt.created_at >= start_window
        )
        .order_by(ChallengeAttempt.created_at.asc())
        .all()
    )

    # Group attempts by session or calendar date
    wake_by_date: Dict[date, datetime] = {}
    for a in attempts:
        dt = _as_dt(a.completed_at or a.created_at)
        if dt:
            d = dt.date()
            if d not in wake_by_date or dt > wake_by_date[d]:
                wake_by_date[d] = dt

    # Include current user's recorded sleep start/end if present
    curr_start = _as_dt(user.estimated_sleep_start)
    curr_end = _as_dt(user.estimated_sleep_end)

    if curr_end:
        end_d = curr_end.date()
        if end_d not in wake_by_date or curr_end > wake_by_date[end_d]:
            wake_by_date[end_d] = curr_end

    target_bed = user.target_bedtime
    target_wake = user.target_wake_time
    target_duration = _compute_target_duration_hours(user)

    sessions: List[Dict[str, Any]] = []

    # Process all dates that actually have recorded data
    all_dates = sorted(set(wake_by_date.keys()), reverse=True)
    if not all_dates and curr_start and curr_end:
        all_dates = [curr_end.date()]

    for day_date in all_dates:
        if day_date < start_window.date():
            continue
        wake_dt = wake_by_date.get(day_date)
        sleep_dt = None

        if curr_start and (curr_start.date() == day_date or curr_start.date() == day_date - timedelta(days=1)):
            sleep_dt = curr_start
        elif wake_dt:
            if target_bed:
                t_time = _parse_time(target_bed)
                if t_time:
                    bed_date = day_date - timedelta(days=1) if t_time.hour >= 12 else day_date
                    sleep_dt = datetime.combine(bed_date, t_time)
            else:
                sleep_dt = wake_dt - timedelta(hours=target_duration)

        if wake_dt is not None or sleep_dt is not None:
            if wake_dt and sleep_dt:
                duration_hours = max(1.0, min(16.0, (wake_dt - sleep_dt).total_seconds() / 3600.0))
            elif curr_start and curr_end:
                duration_hours = max(1.0, min(16.0, (curr_end - curr_start).total_seconds() / 3600.0))
            else:
                duration_hours = target_duration

            # Bedtime adherence difference
            bed_score = 100.0
            if target_bed and sleep_dt:
                t_bed = _parse_time(target_bed)
                if t_bed:
                    t_bed_dt = datetime.combine(sleep_dt.date(), t_bed)
                    diff_m = (sleep_dt - t_bed_dt).total_seconds() / 60.0
                    bed_score = _score_from_differences(diff_m)

            # Wake adherence difference
            wake_score = 100.0
            if target_wake and wake_dt:
                t_wake = _parse_time(target_wake)
                if t_wake:
                    t_wake_dt = datetime.combine(wake_dt.date(), t_wake)
                    diff_m = (wake_dt - t_wake_dt).total_seconds() / 60.0
                    wake_score = _score_from_differences(diff_m)

            daily_adherence = (bed_score + wake_score) / 2.0 if (target_bed and target_wake) else (wake_score if target_wake else 80.0)
            daily_duration_score = _compute_duration_score(duration_hours, target_duration)

            sessions.append({
                "date": day_date.isoformat(),
                "day": day_date.strftime("%a"),
                "sleep_dt": sleep_dt,
                "wake_dt": wake_dt,
                "duration_hours": round(duration_hours, 1),
                "adherence_score": round(daily_adherence, 1),
                "duration_score": round(daily_duration_score, 1),
                "wake_minutes": _time_to_minutes(wake_dt.time()) if wake_dt else None,
                "sleep_minutes": _time_to_minutes(sleep_dt.time()) if sleep_dt else None,
            })

    # Sort chronological
    sessions.sort(key=lambda s: s["date"])
    return sessions


def calculate_sleep_quality(
    db: Session,
    user_id: int,
    days: int = 7
) -> Dict[str, Any]:
    """
    Evaluates real 0-100 Sleep Quality score based strictly on PostgreSQL data & phone inactivity analytics:
    1. Sleep Schedule Adherence (40%)
    2. Sleep Duration (35%)
    3. Sleep Consistency (25%)

    Returns:
    - score: float | None
    - level: str | None
    - status: "available" | "insufficient_data"
    - estimated: True
    - data_days: int
    - components: { schedule_adherence, sleep_duration, consistency }
    - history: List of daily breakdown points
    - message: str
    - disclaimer: str
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {
            "score": None,
            "level": None,
            "status": "insufficient_data",
            "estimated": True,
            "data_days": 0,
            "components": {
                "schedule_adherence": None,
                "sleep_duration": None,
                "consistency": None,
            },
            "history": [],
            "message": "User not found.",
            "disclaimer": "*Estimated from phone inactivity and sleep schedule data",
        }

    # Extract available real sessions
    sessions = _extract_daily_sleep_sessions(db, user, days=days)

    # Check for genuine historical data
    has_meaningful_data = (
        bool(sessions) and
        any(s.get("wake_dt") is not None or s.get("sleep_dt") is not None for s in sessions) and
        (bool(user.estimated_sleep_start) or bool(user.estimated_sleep_end) or len(sessions) >= 1)
    )

    if not has_meaningful_data:
        return {
            "score": None,
            "level": None,
            "status": "insufficient_data",
            "estimated": True,
            "data_days": 0,
            "components": {
                "schedule_adherence": None,
                "sleep_duration": None,
                "consistency": None,
            },
            "history": [],
            "message": "More sleep history is needed to calculate sleep quality.",
            "disclaimer": "*Estimated from phone inactivity and sleep schedule data",
        }

    # Factor 1: Schedule Adherence (40%)
    adherence_scores = [s["adherence_score"] for s in sessions if s.get("adherence_score") is not None]
    avg_adherence = _safe_average(adherence_scores) if adherence_scores else 75.0

    # Factor 2: Sleep Duration (35%)
    duration_scores = [s["duration_score"] for s in sessions if s.get("duration_score") is not None]
    avg_duration_score = _safe_average(duration_scores) if duration_scores else 80.0

    # Factor 3: Sleep Consistency (25%)
    wake_minutes = [s["wake_minutes"] for s in sessions if s.get("wake_minutes") is not None]
    sleep_minutes = [s["sleep_minutes"] for s in sessions if s.get("sleep_minutes") is not None]

    if len(wake_minutes) >= 2 or len(sleep_minutes) >= 2:
        _, std_wake = _circular_mean_std(wake_minutes) if len(wake_minutes) >= 2 else (0.0, 30.0)
        _, std_sleep = _circular_mean_std(sleep_minutes) if len(sleep_minutes) >= 2 else (0.0, 30.0)
        avg_std_dev = (std_wake + std_sleep) / 2.0 if (len(wake_minutes) >= 2 and len(sleep_minutes) >= 2) else (std_wake if len(wake_minutes) >= 2 else std_sleep)
        consistency_score = _compute_consistency_score(avg_std_dev)
    else:
        # If single session, evaluate consistency relative to target deviation
        first_s = sessions[0]
        consistency_score = clamp_score((first_s.get("adherence_score", 80.0) + first_s.get("duration_score", 80.0)) / 2.0)

    # Calculate overall Sleep Quality Score
    overall_score = (
        avg_adherence * SLEEP_QUALITY_WEIGHTS["schedule_adherence"] +
        avg_duration_score * SLEEP_QUALITY_WEIGHTS["sleep_duration"] +
        consistency_score * SLEEP_QUALITY_WEIGHTS["consistency"]
    )
    overall_score = clamp_score(round(overall_score, 1))
    level = get_sleep_quality_level(overall_score)

    # Build daily history trend
    history_entries = []
    for s in sessions:
        day_score = round(
            s["adherence_score"] * SLEEP_QUALITY_WEIGHTS["schedule_adherence"] +
            s["duration_score"] * SLEEP_QUALITY_WEIGHTS["sleep_duration"] +
            consistency_score * SLEEP_QUALITY_WEIGHTS["consistency"],
            1
        )
        history_entries.append({
            "date": s["date"],
            "day": s["day"],
            "score": clamp_score(day_score),
            "duration_hours": s["duration_hours"],
            "adherence": s["adherence_score"],
            "level": get_sleep_quality_level(day_score),
        })

    return {
        "score": overall_score,
        "level": level,
        "status": "available",
        "estimated": True,
        "data_days": len(sessions),
        "components": {
            "schedule_adherence": round(avg_adherence, 1),
            "sleep_duration": round(avg_duration_score, 1),
            "consistency": round(consistency_score, 1),
        },
        "history": history_entries,
        "message": "Sleep quality estimated from phone inactivity and schedule adherence.",
        "disclaimer": "*Estimated from phone inactivity and sleep schedule data",
    }
