import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database import get_db
from models import User, Alarm, ChallengeAttempt, AlarmSnoozeEvent
from routes.auth import get_current_user, get_current_coach_user
from schemas import CoachAssignedUserItem
from services.coach_service import (
    get_assigned_users_for_coach,
    enforce_coach_user_access,
    is_coach_assigned_to_user,
)
from services.habit_score_service import (
    calculate_habit_score_snapshot,
    get_habit_score_history,
    calculate_sleep_adherence_snapshot,
)
from services.sleep_quality_service import calculate_sleep_quality
from routes.analytics import build_behavioral_analytics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/coach", tags=["Wellness Coach Operations"])


@router.get("/users", response_model=List[CoachAssignedUserItem], summary="Get users assigned to authenticated coach")
def get_coach_assigned_users(
    db: Session = Depends(get_db),
    current_coach: User = Depends(get_current_coach_user)
):
    """
    Returns only the patient accounts assigned to the currently authenticated coach.
    Never trusts a coach_id provided in the frontend request.
    """
    assigned_patients = get_assigned_users_for_coach(db, current_coach.id)
    return [CoachAssignedUserItem(**p) for p in assigned_patients]


@router.get("/users/{user_id}/history", summary="Get assigned user alarm & verification history")
def get_assigned_user_history(
    user_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_coach: User = Depends(get_current_coach_user)
):
    """
    Retrieves alarm history and verification attempts for an assigned patient.
    Enforces server-side assignment verification: returns HTTP 403 if unassigned.
    """
    enforce_coach_user_access(db, current_coach, user_id)

    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User #{user_id} not found.")

    alarms = db.query(Alarm).filter(Alarm.user_id == user_id).all()
    alarm_map = {a.id: a for a in alarms}

    attempts = (
        db.query(ChallengeAttempt)
        .filter(ChallengeAttempt.user_id == user_id)
        .order_by(desc(ChallengeAttempt.created_at))
        .limit(limit)
        .all()
    )

    snoozes = (
        db.query(AlarmSnoozeEvent)
        .filter(AlarmSnoozeEvent.user_id == user_id)
        .order_by(desc(AlarmSnoozeEvent.created_at))
        .limit(limit)
        .all()
    )

    return {
        "user_id": user_id,
        "user_name": target_user.name,
        "user_email": target_user.email,
        "total_alarms": len(alarms),
        "active_alarms": len([a for a in alarms if a.is_active]),
        "recent_challenge_attempts": [
            {
                "id": a.id,
                "alarm_id": a.alarm_id,
                "alarm_title": alarm_map.get(a.alarm_id).title if a.alarm_id in alarm_map else "Quick Challenge",
                "challenge_type": a.challenge_type,
                "difficulty": a.difficulty,
                "is_correct": a.is_correct,
                "time_taken": a.time_taken,
                "verification_status": a.verification_status,
                "completed_at": a.completed_at.isoformat() if a.completed_at else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in attempts
        ],
        "recent_snoozes": [
            {
                "id": s.id,
                "alarm_id": s.alarm_id,
                "snooze_count": s.snooze_count,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in snoozes
        ]
    }


@router.get("/users/{user_id}/analytics", summary="Get assigned user behavioral & habit analytics")
def get_assigned_user_analytics(
    user_id: int,
    period_days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    current_coach: User = Depends(get_current_coach_user)
):
    """
    Retrieves habit score breakdowns, sleep adherence, and behavioral patterns for an assigned patient.
    Enforces server-side assignment verification: returns HTTP 403 if unassigned.
    """
    enforce_coach_user_access(db, current_coach, user_id)

    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User #{user_id} not found.")

    habit_snap = calculate_habit_score_snapshot(db, user_id, period_days=period_days)
    habit_hist = get_habit_score_history(db, user_id, days=max(14, period_days * 2))
    sleep_adherence = calculate_sleep_adherence_snapshot(db, user_id)
    sleep_quality = calculate_sleep_quality(db, user_id, days=period_days)
    behavioral = build_behavioral_analytics(db, user_id)

    return {
        "user_id": user_id,
        "user_name": target_user.name,
        "user_email": target_user.email,
        "period_days": period_days,
        "habit_score": habit_snap.get("habit_score", 0.0),
        "habit_breakdown": habit_snap.get("breakdown", {}),
        "habit_history": habit_hist,
        "sleep_adherence": sleep_adherence,
        "sleep_quality": sleep_quality,
        "behavioral_patterns": behavioral,
    }
