import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc

from models import User, CoachUserAssignment, Alarm, ChallengeAttempt
from services.habit_score_service import calculate_habit_score_snapshot
from services.sleep_quality_service import calculate_sleep_quality

logger = logging.getLogger(__name__)


def is_coach_assigned_to_user(db: Session, coach_id: int, user_id: int) -> bool:
    """
    Checks whether a coach has an active assignment to the specified user.
    Uses indexed (coach_id, user_id, is_active) lookup.
    """
    if not coach_id or not user_id:
        return False
    assignment = (
        db.query(CoachUserAssignment)
        .filter(
            CoachUserAssignment.coach_id == coach_id,
            CoachUserAssignment.user_id == user_id,
            CoachUserAssignment.is_active == True,
        )
        .first()
    )
    return assignment is not None


def get_coach_assigned_user_ids(db: Session, coach_id: int) -> List[int]:
    """
    Returns list of user IDs actively assigned to the given coach.
    """
    if not coach_id:
        return []
    records = (
        db.query(CoachUserAssignment.user_id)
        .filter(
            CoachUserAssignment.coach_id == coach_id,
            CoachUserAssignment.is_active == True,
        )
        .all()
    )
    return [r[0] for r in records]


def enforce_coach_user_access(db: Session, current_user: User, target_user_id: int) -> None:
    """
    Reusable authorization enforcement:
    - Admins have system-wide access.
    - Regular users can only access their own data.
    - Coaches can ONLY access users explicitly and actively assigned to them.
    Raises HTTP 403 Forbidden if access is denied.
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required."
        )

    user_role = (current_user.role or "").strip().upper()

    # 1. Admin has global access
    if "ADMIN" in user_role:
        return

    # 2. Self-access
    if current_user.id == target_user_id:
        return

    # 3. Coach access check
    if "COACH" in user_role:
        if is_coach_assigned_to_user(db, current_user.id, target_user_id):
            return
        logger.warning(
            f"Unauthorized coach access attempt: Coach ID={current_user.id} tried to access unassigned User ID={target_user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied. User #{target_user_id} is not assigned to your wellness coach roster."
        )

    # 4. Standard user trying to access other user's data
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to access this user's data."
    )


def assign_user_to_coach(
    db: Session,
    coach_id: int,
    user_id: int,
    admin_id: Optional[int] = None
) -> CoachUserAssignment:
    """
    Assigns a user to a coach.
    - Validates coach exists and has COACH role.
    - Validates target user exists and has USER role.
    - Prevents self-assignment.
    - Deactivates previous active assignments for this user if reassigned (or prevents duplicate active).
    """
    if coach_id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot assign a user/coach to themselves."
        )

    coach = db.query(User).filter(User.id == coach_id).first()
    if not coach:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Coach with ID {coach_id} not found."
        )
    coach_role = (coach.role or "").upper()
    if "COACH" not in coach_role and "ADMIN" not in coach_role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User #{coach_id} ('{coach.name}') does not have a Coach role."
        )

    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target user with ID {user_id} not found."
        )

    # Deactivate existing active assignment for this specific coach-user pair or other coaches (reassignment)
    existing_assignments = (
        db.query(CoachUserAssignment)
        .filter(
            CoachUserAssignment.user_id == user_id,
            CoachUserAssignment.is_active == True
        )
        .all()
    )
    for existing in existing_assignments:
        if existing.coach_id == coach_id:
            # Already actively assigned to this coach
            return existing
        else:
            # Reassignment: deactivate old coach assignment
            existing.is_active = False

    # Create new assignment
    new_assignment = CoachUserAssignment(
        coach_id=coach_id,
        user_id=user_id,
        assigned_by=admin_id,
        is_active=True,
        assigned_at=datetime.now(timezone.utc)
    )
    db.add(new_assignment)
    db.commit()
    db.refresh(new_assignment)

    logger.info(
        f"Assigned User ID={user_id} to Coach ID={coach_id} by Admin ID={admin_id}"
    )
    return new_assignment


def unassign_user_from_coach(
    db: Session,
    coach_id: int,
    user_id: int
) -> bool:
    """
    Deactivates the assignment between a coach and a user.
    """
    assignments = (
        db.query(CoachUserAssignment)
        .filter(
            CoachUserAssignment.coach_id == coach_id,
            CoachUserAssignment.user_id == user_id,
            CoachUserAssignment.is_active == True
        )
        .all()
    )
    if not assignments:
        return False

    for a in assignments:
        a.is_active = False

    db.commit()
    logger.info(f"Unassigned User ID={user_id} from Coach ID={coach_id}")
    return True


def get_assigned_users_for_coach(db: Session, coach_id: int) -> List[Dict[str, Any]]:
    """
    Retrieves detailed patient cards for all users actively assigned to a coach.
    Calculates habit score and sleep quality snapshots efficiently.
    """
    assigned_records = (
        db.query(CoachUserAssignment, User)
        .join(User, CoachUserAssignment.user_id == User.id)
        .filter(
            CoachUserAssignment.coach_id == coach_id,
            CoachUserAssignment.is_active == True
        )
        .all()
    )

    results = []
    for assignment, user in assigned_records:
        h_snap = calculate_habit_score_snapshot(db, user.id, period_days=7)
        sq_snap = calculate_sleep_quality(db, user.id, days=7)
        recent_alarm_count = db.query(Alarm).filter(Alarm.user_id == user.id, Alarm.is_active == True).count()

        breakdown = h_snap.get("breakdown", {})
        wake_val = breakdown.get("wake_up_consistency", 0.0) if isinstance(breakdown, dict) else 0.0
        if isinstance(wake_val, dict):
            wake_val = wake_val.get("rate", 0.0)
        wake_up_consistency = float(wake_val or 0.0)

        results.append({
            "id": user.id,
            "name": user.name or f"User #{user.id}",
            "email": user.email,
            "role": user.role,
            "target_bedtime": user.target_bedtime or "23:00",
            "target_wake_time": user.target_wake_time or "07:00",
            "inactivity_threshold_minutes": user.inactivity_threshold_minutes or 30,
            "habit_score": h_snap.get("habit_score", 0.0),
            "sleep_quality_score": sq_snap.get("score"),
            "wake_up_consistency": wake_up_consistency,
            "recent_alarm_count": recent_alarm_count,
            "assigned_at": assignment.assigned_at,
            "assigned_by": assignment.assigned_by
        })

    return results


def get_all_coach_assignments_overview(db: Session) -> Dict[str, Any]:
    """
    Builds the full admin cockpit overview:
    - All coaches with their active assigned user counts & user details.
    - All normal users who are either unassigned or assigned to coaches (for easy reassignment).
    """
    all_coaches = (
        db.query(User)
        .filter(
            or_(
                User.role.ilike("%coach%"),
                User.role.ilike("%wellness%")
            )
        )
        .all()
    )

    all_normal_users = (
        db.query(User)
        .filter(
            and_(
                ~User.role.ilike("%admin%"),
                ~User.role.ilike("%coach%"),
                ~User.role.ilike("%wellness%")
            )
        )
        .order_by(User.name)
        .all()
    )

    # Active assignment map: user_id -> CoachUserAssignment
    active_assignments = (
        db.query(CoachUserAssignment)
        .filter(CoachUserAssignment.is_active == True)
        .all()
    )
    user_to_assignment = {a.user_id: a for a in active_assignments}
    coach_map = {c.id: c for c in all_coaches}

    coaches_list = []
    total_assigned = 0

    for coach in all_coaches:
        assigned_patients = get_assigned_users_for_coach(db, coach.id)
        total_assigned += len(assigned_patients)
        coaches_list.append({
            "id": coach.id,
            "name": coach.name or f"Coach #{coach.id}",
            "email": coach.email,
            "role": coach.role,
            "assigned_count": len(assigned_patients),
            "assigned_users": assigned_patients
        })

    # Build available/all users list
    available_users = []
    for u in all_normal_users:
        current_assign = user_to_assignment.get(u.id)
        current_coach = coach_map.get(current_assign.coach_id) if current_assign else None
        h_snap = calculate_habit_score_snapshot(db, u.id, period_days=7)

        available_users.append({
            "id": u.id,
            "name": u.name or f"User #{u.id}",
            "email": u.email,
            "role": u.role,
            "current_coach_id": current_assign.coach_id if current_assign else None,
            "current_coach_name": current_coach.name if current_coach else None,
            "habit_score": h_snap.get("habit_score", 0.0)
        })

    total_unassigned = len([u for u in available_users if not u["current_coach_id"]])

    return {
        "total_coaches": len(all_coaches),
        "total_assigned_users": total_assigned,
        "total_unassigned_users": total_unassigned,
        "coaches": coaches_list,
        "available_users": available_users
    }
