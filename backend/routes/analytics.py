import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import mean
from typing import Dict, List, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from database import get_db
from models import Alarm, ChallengeAttempt, User, AlarmSnoozeEvent
from routes.auth import get_current_user
from services.habit_score_service import (
    calculate_habit_score_snapshot,
    calculate_sleep_adherence_snapshot,
    get_habit_level,
    get_habit_score_history,
    record_user_activity,
    update_user_sleep_schedule,
)
from services.sleep_quality_service import (
    calculate_sleep_quality,
    get_sleep_quality_level,
)
from services.personalization_service import (
    get_adaptive_recommendation,
    calculate_personalized_difficulty,
    normalize_difficulty,
    DIFFICULTY_LEVELS
)
from services.gemini_service import ALLOWED_TYPES
from schemas import AdaptiveRecommendationResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["Performance & Analytics"])

@router.get("/summary")
def get_analytics_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns high-level performance analytics summary for the currently logged-in user:
    - overall_accuracy (%)
    - total_challenges
    - passed_challenges
    - failed_challenges
    - average_completion_time (seconds)
    - current_streak (consecutive active days with passed challenges)
    - recommended_difficulty
    - preferred_challenge_type
    - recommendation_reason
    - cognitive_score
    - trend
    - strong_types
    - weak_types
    """
    attempts = (
        db.query(ChallengeAttempt)
        .filter(ChallengeAttempt.user_id == current_user.id)
        .order_by(desc(ChallengeAttempt.created_at))
        .all()
    )

    rec = get_adaptive_recommendation(db, current_user.id, "Medium")
    analysis = rec["analysis"]

    total = analysis["total_attempts"]
    passed = analysis["passed_attempts"]
    failed = analysis["failed_attempts"]
    overall_accuracy = analysis["overall_accuracy"]
    avg_time = analysis["avg_time_taken"]

    # Calculate streak (consecutive calendar days going back from today with at least 1 passed attempt)
    passed_dates = (
        db.query(func.date(ChallengeAttempt.created_at))
        .filter(ChallengeAttempt.user_id == current_user.id, ChallengeAttempt.is_correct == True)
        .group_by(func.date(ChallengeAttempt.created_at))
        .all()
    )
    
    unique_dates = {str(d[0]) for d in passed_dates if d[0]}
    
    streak = 0
    today = datetime.now().date()
    for i in range(365):
        check_date = str(today - timedelta(days=i))
        if check_date in unique_dates:
            streak += 1
        elif i == 0:
            # Today might not have passed challenge yet, check yesterday
            continue
        else:
            break

    return {
        "user_id": current_user.id,
        "overall_accuracy": overall_accuracy,
        "total_challenges": total,
        "passed_challenges": passed,
        "failed_challenges": failed,
        "average_completion_time": avg_time,
        "current_streak": streak,
        "recommended_difficulty": rec["recommended_difficulty"],
        "preferred_challenge_type": rec["recommended_challenge_type"],
        "recommendation_reason": rec["reason"],
        "cognitive_score": analysis.get("score", 50.0),
        "trend": analysis.get("trend", "stable"),
        "strong_types": analysis.get("strong_types", []),
        "weak_types": analysis.get("weak_types", [])
    }

@router.get("/adaptive-profile", response_model=AdaptiveRecommendationResponse)
def get_adaptive_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns full Adaptive Difficulty Engine profile and breakdown for the logged-in user.
    """
    rec = get_adaptive_recommendation(db, current_user.id, "Medium")
    analysis = rec["analysis"]

    return AdaptiveRecommendationResponse(
        user_id=current_user.id,
        recommended_difficulty=rec["recommended_difficulty"],
        recommended_challenge_type=rec["recommended_challenge_type"],
        reason=rec["reason"],
        strong_types=analysis.get("strong_types", []),
        weak_types=analysis.get("weak_types", []),
        score=analysis.get("score", 50.0),
        trend=analysis.get("trend", "stable"),
        analysis=analysis
    )

@router.get("/by-type")
def get_analytics_by_type(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns accuracy and performance metrics grouped by challenge type for the logged-in user.
    """
    attempts = (
        db.query(ChallengeAttempt)
        .filter(ChallengeAttempt.user_id == current_user.id)
        .all()
    )

    by_type: Dict[str, dict] = {}
    for t in ALLOWED_TYPES:
        by_type[t] = {
            "challenge_type": t,
            "total_attempts": 0,
            "passed": 0,
            "failed": 0,
            "accuracy_percentage": 0.0,
            "avg_time_taken": 0.0
        }

    for a in attempts:
        ctype = a.challenge_type or "Math Problems"
        if ctype not in by_type:
            by_type[ctype] = {
                "challenge_type": ctype,
                "total_attempts": 0,
                "passed": 0,
                "failed": 0,
                "accuracy_percentage": 0.0,
                "avg_time_taken": 0.0
            }
        
        by_type[ctype]["total_attempts"] += 1
        if a.is_correct:
            by_type[ctype]["passed"] += 1
        else:
            by_type[ctype]["failed"] += 1
        by_type[ctype]["avg_time_taken"] += (a.time_taken or 0)

    result = []
    for ctype, data in by_type.items():
        tot = data["total_attempts"]
        if tot > 0:
            data["accuracy_percentage"] = round((data["passed"] / tot * 100.0), 1)
            data["avg_time_taken"] = round((data["avg_time_taken"] / tot), 1)
        result.append(data)

    return result

@router.get("/by-difficulty")
def get_analytics_by_difficulty(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns accuracy and performance metrics grouped by difficulty for the logged-in user.
    """
    attempts = (
        db.query(ChallengeAttempt)
        .filter(ChallengeAttempt.user_id == current_user.id)
        .all()
    )

    by_diff: Dict[str, dict] = {}
    for d in DIFFICULTY_LEVELS:
        by_diff[d] = {
            "difficulty": d,
            "total_attempts": 0,
            "passed": 0,
            "failed": 0,
            "accuracy_percentage": 0.0,
            "avg_time_taken": 0.0
        }

    for a in attempts:
        diff = normalize_difficulty(a.difficulty or "Medium")
        if diff not in by_diff:
            by_diff[diff] = {
                "difficulty": diff,
                "total_attempts": 0,
                "passed": 0,
                "failed": 0,
                "accuracy_percentage": 0.0,
                "avg_time_taken": 0.0
            }
        
        by_diff[diff]["total_attempts"] += 1
        if a.is_correct:
            by_diff[diff]["passed"] += 1
        else:
            by_diff[diff]["failed"] += 1
        by_diff[diff]["avg_time_taken"] += (a.time_taken or 0)

    result = []
    for diff in DIFFICULTY_LEVELS:
        data = by_diff[diff]
        tot = data["total_attempts"]
        if tot > 0:
            data["accuracy_percentage"] = round((data["passed"] / tot * 100.0), 1)
            data["avg_time_taken"] = round((data["avg_time_taken"] / tot), 1)
        result.append(data)

    return result

@router.get("/history")
def get_analytics_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns daily performance history and recent individual attempt logs for the logged-in user.
    """
    attempts = (
        db.query(ChallengeAttempt)
        .filter(ChallengeAttempt.user_id == current_user.id)
        .order_by(desc(ChallengeAttempt.created_at))
        .all()
    )

    daily_map: Dict[str, dict] = {}
    recent_logs = []

    for a in attempts:
        dt_str = a.created_at.strftime("%Y-%m-%d") if a.created_at else datetime.now().strftime("%Y-%m-%d")
        if dt_str not in daily_map:
            daily_map[dt_str] = {
                "date": dt_str,
                "total_attempts": 0,
                "passed": 0,
                "failed": 0,
                "accuracy_percentage": 0.0,
                "avg_time_taken": 0.0
            }
        
        daily_map[dt_str]["total_attempts"] += 1
        if a.is_correct:
            daily_map[dt_str]["passed"] += 1
        else:
            daily_map[dt_str]["failed"] += 1
        daily_map[dt_str]["avg_time_taken"] += (a.time_taken or 0)

        if len(recent_logs) < 20:
            recent_logs.append({
                "id": a.id,
                "date": a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else "Just Now",
                "challenge_type": a.challenge_type,
                "difficulty": a.difficulty,
                "question": a.question,
                "user_answer": a.user_answer,
                "correct_answer": a.correct_answer,
                "is_correct": a.is_correct,
                "attempt_number": a.attempt_number,
                "time_taken": a.time_taken,
                "time_limit": a.time_limit
            })

    daily_history = []
    for dt_str in sorted(daily_map.keys()):
        data = daily_map[dt_str]
        tot = data["total_attempts"]
        if tot > 0:
            data["accuracy_percentage"] = round((data["passed"] / tot * 100.0), 1)
            data["avg_time_taken"] = round((data["avg_time_taken"] / tot), 1)
        daily_history.append(data)

    return {
        "daily_history": daily_history,
        "recent_logs": recent_logs
    }


def _safe_average(values: List[float]) -> float:
    if not values:
        return 0.0
    return round(mean(values), 2)


def _to_hhmm(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "time"):
        dt = value
    else:
        return None
    return dt.strftime("%H:%M")


def _sorted_unique_dates(values: List[datetime]) -> List[str]:
    dates = sorted({v.date().isoformat() for v in values if v is not None})
    return dates


def build_behavioral_analytics(db: Session, user_id: int) -> Dict[str, Any]:
    alarms = db.query(Alarm).filter(Alarm.user_id == user_id).all()
    attempts = (
        db.query(ChallengeAttempt)
        .filter(ChallengeAttempt.user_id == user_id)
        .order_by(ChallengeAttempt.created_at.asc())
        .all()
    )

    try:
        import scheduler
    except Exception:
        scheduler = None

    snooze_events = []
    persisted_snoozes = db.query(AlarmSnoozeEvent).filter(AlarmSnoozeEvent.user_id == user_id).all()
    for event in persisted_snoozes:
        due_at = event.scheduled_for
        snooze_events.append({
            "count": int(event.snooze_count or 0),
            "due_at": due_at,
            "duration": event.alarm.snooze_duration if event.alarm else 0,
            "day": due_at.strftime("%A") if due_at else "Unknown"
        })

    if scheduler:
        for item in getattr(scheduler, "scheduled_snoozes", []):
            alarm = item.get("alarm")
            if getattr(alarm, "user_id", None) == user_id:
                due_at = item.get("due_at")
                snooze_events.append({
                    "count": int(item.get("snooze_count", 0) or 0),
                    "due_at": due_at,
                    "duration": getattr(alarm, "snooze_duration", None) or 0,
                    "day": due_at.strftime("%A") if due_at else "Unknown"
                })
        for item in getattr(scheduler, "triggered_alarms", []):
            if item.get("user_id") == user_id and item.get("snooze_count") is not None:
                snooze_events.append({
                    "count": int(item.get("snooze_count", 0) or 0),
                    "due_at": None,
                    "duration": item.get("snooze_duration") or 0,
                    "day": "Unknown"
                })

    alarm_durations = [a.snooze_duration for a in alarms if a.snooze_duration is not None]
    alarm_snooze_limits = [a.max_snoozes for a in alarms if a.max_snoozes is not None]
    total_snoozes = sum(event["count"] for event in snooze_events)
    avg_snoozes_per_alarm = round(total_snoozes / len(alarms), 2) if alarms else 0.0
    avg_snooze_duration = _safe_average(alarm_durations)
    if snooze_events:
        day_counts = Counter(event["day"] for event in snooze_events if event.get("day") and event["day"] != "Unknown")
        most_snoozed_day = day_counts.most_common(1)[0][0] if day_counts else "Insufficient data"
    else:
        most_snoozed_day = "Insufficient data"

    attempt_datetimes = [a.created_at for a in attempts if a.created_at]
    completion_datetimes = [a.completed_at for a in attempts if a.completed_at]
    first_attempt = min(attempt_datetimes) if attempt_datetimes else None
    final_dismissal = max(completion_datetimes) if completion_datetimes else None
    first_to_final_dismissal = None
    if first_attempt and final_dismissal:
        first_to_final_dismissal = int((final_dismissal - first_attempt).total_seconds() / 60)

    wake_up_behavior = {
        "status": "ok" if attempts else "Insufficient data",
        "records": [],
        "average_wakefulness_rating": None,
        "average_time_to_wake_minutes": None,
        "verification_success_rate": None,
        "average_verification_time_minutes": None
    }

    session_map: Dict[str, List[ChallengeAttempt]] = defaultdict(list)
    for attempt in attempts:
        key = attempt.session_id or f"manual_{attempt.alarm_id}_{attempt.created_at.date().isoformat()}"
        session_map[key].append(attempt)

    if attempts:
        wakeful_scores = []
        verification_times = []
        time_to_wake_minutes = []
        success_count = 0
        behavior_records = []
        for session_id, session_attempts in session_map.items():
            ordered = sorted(session_attempts, key=lambda item: item.created_at or datetime.now())
            completed_at = max((a.completed_at for a in ordered if a.completed_at), default=None)
            started_at = min((a.created_at for a in ordered if a.created_at), default=None)
            if completed_at and started_at:
                time_to_wake_minutes.append((completed_at - started_at).total_seconds() / 60)
            entry = {
                "session_id": session_id,
                "alarm_id": ordered[0].alarm_id,
                "alarm_time": db.query(Alarm).filter(Alarm.id == ordered[0].alarm_id).first().alarm_time if ordered[0].alarm_id else None,
                "actual_wake_up_time": _to_hhmm(completed_at) if completed_at else _to_hhmm(ordered[-1].created_at),
                "verification_completion_time": _to_hhmm(completed_at),
                "challenge_completion_time": _to_hhmm(ordered[-1].created_at),
                "wakefulness_rating": max((a.wakefulness_rating for a in ordered if a.wakefulness_rating is not None), default=None),
                "number_of_snoozes": max((event["count"] for event in snooze_events if event.get("due_at") is None and event.get("count") is not None), default=0),
                "verification_success": any(a.verification_status == "passed" for a in ordered),
                "verification_status": ordered[-1].verification_status
            }
            if entry["wakefulness_rating"] is not None:
                wakeful_scores.append(entry["wakefulness_rating"])
            if entry["verification_completion_time"]:
                verification_times.append(len(entry["verification_completion_time"]))
            if entry["verification_success"]:
                success_count += 1
            behavior_records.append(entry)

        wake_up_behavior["records"] = behavior_records
        wake_up_behavior["average_wakefulness_rating"] = _safe_average(wakeful_scores)
        wake_up_behavior["average_time_to_wake_minutes"] = round(_safe_average(time_to_wake_minutes), 1) if time_to_wake_minutes else 0.0
        wake_up_behavior["verification_success_rate"] = round((success_count / len(behavior_records)) * 100, 1) if behavior_records else 0.0
        wake_up_behavior["average_verification_time_minutes"] = round(_safe_average([float(v) for v in verification_times]) / 60, 2) if verification_times else 0.0

    productivity = {
        "status": "ok" if attempts else "Insufficient data",
        "snooze_frequency_vs_challenge_accuracy": {
            "low_snooze_accuracy": None,
            "high_snooze_accuracy": None,
            "pattern": "Insufficient data"
        },
        "wake_up_consistency_vs_performance": {
            "consistency_score": None,
            "accuracy_score": None,
            "pattern": "Insufficient data"
        },
        "wakefulness_rating_vs_challenge_performance": {
            "average_rating": None,
            "average_accuracy": None,
            "pattern": "Insufficient data"
        }
    }

    if attempts:
        daily_map: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"total": 0, "passed": 0, "snoozes": 0, "wakefulness": []})
        for attempt in attempts:
            day = (attempt.created_at or datetime.now()).date().isoformat() if attempt.created_at else datetime.now().date().isoformat()
            daily_map[day]["total"] += 1
            if attempt.is_correct:
                daily_map[day]["passed"] += 1
            if attempt.wakefulness_rating is not None:
                daily_map[day]["wakefulness"].append(attempt.wakefulness_rating)
        for event in snooze_events:
            if event.get("due_at") is not None:
                day = event["due_at"].date().isoformat()
                daily_map[day]["snoozes"] += int(event.get("count", 0) or 0)

        day_metrics = []
        for day, values in daily_map.items():
            total = values["total"]
            accuracy = round((values["passed"] / total) * 100, 1) if total else 0.0
            snoozes = values["snoozes"]
            rating = _safe_average(values["wakefulness"]) if values["wakefulness"] else 0.0
            day_metrics.append({"date": day, "accuracy": accuracy, "snoozes": snoozes, "rating": rating})

        if day_metrics:
            low_snooze = [item["accuracy"] for item in day_metrics if item["snoozes"] <= 1]
            high_snooze = [item["accuracy"] for item in day_metrics if item["snoozes"] > 1]
            productivity["snooze_frequency_vs_challenge_accuracy"] = {
                "low_snooze_accuracy": round(_safe_average(low_snooze), 1) if low_snooze else 0.0,
                "high_snooze_accuracy": round(_safe_average(high_snooze), 1) if high_snooze else 0.0,
                "pattern": "Lower snooze days align with stronger challenge accuracy." if low_snooze and high_snooze and _safe_average(low_snooze) >= _safe_average(high_snooze) else "The comparison is inconclusive with limited observed data."
            }

            consistency_score = round((len([item for item in day_metrics if item["snoozes"] <= 1]) / len(day_metrics)) * 100, 1) if day_metrics else 0.0
            accuracy_score = round(_safe_average([item["accuracy"] for item in day_metrics]), 1) if day_metrics else 0.0
            productivity["wake_up_consistency_vs_performance"] = {
                "consistency_score": consistency_score,
                "accuracy_score": accuracy_score,
                "pattern": "Wake-up consistency is trending with stronger challenge performance." if consistency_score >= 50 and accuracy_score >= 50 else "Wake-up consistency and challenge performance need more comparable data."
            }

            rating_values = [item["rating"] for item in day_metrics if item["rating"] > 0]
            rating_score = round(_safe_average(rating_values), 1) if rating_values else 0.0
            productivity["wakefulness_rating_vs_challenge_performance"] = {
                "average_rating": rating_score,
                "average_accuracy": accuracy_score,
                "pattern": "Higher wakefulness ratings correspond with stronger performance in the observed records." if rating_score >= 3 and accuracy_score >= 50 else "The relationship between wakefulness and performance is inconclusive with the current data."
            }

    habit_consistency = {
        "status": "ok" if attempts else "Insufficient data",
        "wake_up_consistency_percentage": 0.0,
        "successful_wake_up_days": 0,
        "missed_or_failed_verification_days": 0,
        "average_wake_up_time": None,
        "wake_up_streak": 0,
        "snooze_consistency": "Insufficient data"
    }

    if attempts:
        unique_days = sorted({(a.created_at or datetime.now()).date().isoformat() for a in attempts if a.created_at})
        successful_days = sorted({(a.created_at or datetime.now()).date().isoformat() for a in attempts if a.is_correct and a.verification_status in {"passed", "completed"}})
        failed_days = sorted({(a.created_at or datetime.now()).date().isoformat() for a in attempts if a.verification_status in {"failed", "timeout"}})
        habit_consistency["wake_up_consistency_percentage"] = round((len(successful_days) / len(unique_days)) * 100, 1) if unique_days else 0.0
        habit_consistency["successful_wake_up_days"] = len(successful_days)
        habit_consistency["missed_or_failed_verification_days"] = len(failed_days)

        wake_times = [a.completed_at for a in attempts if a.completed_at is not None]
        if wake_times:
            avg_wake_time = datetime.combine(datetime.today().date(), datetime.min.time())
            total_minutes = sum((wt.hour * 60 + wt.minute) for wt in wake_times)
            habit_consistency["average_wake_up_time"] = (avg_wake_time + timedelta(minutes=round(total_minutes / len(wake_times)))).strftime("%H:%M")

        streak = 0
        current_day = datetime.now().date()
        for offset in range(365):
            check_day = (current_day - timedelta(days=offset)).isoformat()
            if check_day in successful_days:
                streak += 1
            elif offset == 0:
                continue
            else:
                break
        habit_consistency["wake_up_streak"] = streak

        if total_snoozes > 0:
            habit_consistency["snooze_consistency"] = "Detected a recurring snooze pattern across wake-up sessions." if most_snoozed_day != "Insufficient data" else "Some snooze patterns are present but not enough for a confident trend."
        else:
            habit_consistency["snooze_consistency"] = "Insufficient data"

    sleep_pattern = {
        "status": "Insufficient data",
        "message": "No persisted sleep-duration, bedtime, or wake-time records were found in the current project data model.",
        "average_sleep_duration": None,
        "average_bedtime": None,
        "average_wake_up_time": None,
        "sleep_wake_consistency": None,
        "relationship_summary": "Insufficient data"
    }

    insights = []
    if most_snoozed_day != "Insufficient data":
        insights.append(f"You snooze most often on {most_snoozed_day}.")
    if productivity.get("snooze_frequency_vs_challenge_accuracy", {}).get("low_snooze_accuracy") is not None and productivity["snooze_frequency_vs_challenge_accuracy"].get("high_snooze_accuracy") is not None:
        low_val = productivity["snooze_frequency_vs_challenge_accuracy"]["low_snooze_accuracy"]
        high_val = productivity["snooze_frequency_vs_challenge_accuracy"]["high_snooze_accuracy"]
        if low_val >= high_val:
            insights.append("Your challenge accuracy is higher on days with fewer snoozes.")
    if habit_consistency.get("wake_up_consistency_percentage", 0) >= 70:
        insights.append(f"Your wake-up time has been consistent for the last {habit_consistency.get('wake_up_streak', 0) or 1} days.")
    if not insights:
        insights.append("Insufficient data to generate a behavioral trend insight yet.")

    return {
        "snooze_pattern": {
            "total_snoozes": total_snoozes,
            "average_snoozes_per_alarm": avg_snoozes_per_alarm,
            "average_snooze_duration_minutes": avg_snooze_duration,
            "most_frequently_snoozed_days": [most_snoozed_day] if most_snoozed_day != "Insufficient data" else [],
            "time_from_first_alarm_to_final_dismissal_minutes": first_to_final_dismissal,
            "status": "Insufficient data" if total_snoozes == 0 and not alarm_durations else "ok"
        },
        "wake_up_behavior": wake_up_behavior,
        "productivity_correlation": productivity,
        "habit_consistency": habit_consistency,
        "sleep_pattern": sleep_pattern,
        "insights": insights
    }


@router.post("/activity")
def post_user_activity(
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Records meaningful device/application activity around target bedtime.
    Estimates sleep start based on phone inactivity when continuous inactivity >= threshold.
    """
    res = record_user_activity(db, current_user.id)
    return res


@router.post("/sleep-schedule")
def post_sleep_schedule(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Updates the user's target sleep schedule (target_bedtime, target_wake_time, inactivity_threshold_minutes).
    """
    target_bedtime = payload.get("target_bedtime")
    target_wake_time = payload.get("target_wake_time")
    inactivity_threshold = payload.get("inactivity_threshold_minutes", 30)

    res = update_user_sleep_schedule(
        db,
        current_user.id,
        target_bedtime=target_bedtime,
        target_wake_time=target_wake_time,
        inactivity_threshold_minutes=inactivity_threshold
    )
    return res


@router.get("/habit-score")
def get_habit_score(
    period_days: int = 7,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Returns the weighted habit score and component breakdown for the authenticated user for the requested period."""
    snapshot = calculate_habit_score_snapshot(db, current_user.id, period_days=period_days)
    return {
        "habit_score": snapshot["habit_score"],
        "level": snapshot["level"],
        "breakdown": snapshot["breakdown"],
        "weights": snapshot["weights"],
        "insights": snapshot.get("insights", []),
        "sleep_details": snapshot.get("sleep_details", {}),
        "available_components": snapshot.get("available_components", {}),
        "period_days": snapshot.get("period_days", period_days),
    }


@router.get("/habit-score/weekly")
def get_habit_score_weekly(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Returns the selected-period habit score and comparison against previous week."""
    snapshot = calculate_habit_score_snapshot(db, current_user.id, period_days=7)
    history = get_habit_score_history(db, current_user.id, days=14)
    return {
        "habit_score": snapshot["habit_score"],
        "level": snapshot["level"],
        "this_week": history["weekly_scores"].get("This Week", snapshot["habit_score"]),
        "last_week": history["weekly_scores"].get("Last Week", 0.0),
        "change": history["weekly_scores"].get("Change", 0.0),
        "score_changes": history.get("score_changes", {}),
        "daily_scores": history.get("daily_scores", []),
    }


@router.get("/habit-score/history")
def get_habit_score_history_endpoint(
    days: int = 14,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Returns the daily and weekly habit score history including score changes."""
    return get_habit_score_history(db, current_user.id, days=days)


@router.get("/sleep-adherence")
def get_sleep_adherence(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Returns the latest sleep schedule adherence status, target schedule, and estimated sleep time."""
    return calculate_sleep_adherence_snapshot(db, current_user.id)


@router.get("/sleep-quality")
def get_sleep_quality_analytics(
    days: int = 7,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Returns the 0-100 Sleep Quality score, level, component breakdown, and daily trends."""
    return calculate_sleep_quality(db, current_user.id, days=days)


@router.get("/behavioral")
def get_behavioral_analytics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Returns behavioral analytics based on the existing alarm, wake-up verification, and challenge data."""
    return build_behavioral_analytics(db, current_user.id)



