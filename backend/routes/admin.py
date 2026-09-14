import logging
from collections import defaultdict
from datetime import datetime, timedelta, date, timezone
from statistics import mean
from typing import Dict, List, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from database import get_db
from models import Alarm, ChallengeAttempt, User, AlarmSnoozeEvent, PlatformAnnouncement, Notification
from routes.auth import get_current_admin_user
from services.habit_score_service import calculate_habit_score_snapshot
from services.personalization_service import ALLOWED_TYPES, DIFFICULTY_LEVELS
from services.performance_metrics_service import calculate_performance_metrics
from services.notification_service import broadcast_announcements_to_users
from services.coach_service import (
    get_all_coach_assignments_overview,
    assign_user_to_coach,
    unassign_user_from_coach,
)
from schemas import (
    AdminDashboardResponse,
    AdminUserItem,
    AdminRoleUpdateRequest,
    AdminAnalyticsResponse,
    AdminRecommendationsResponse,
    AdminReportsResponse,
    AdminAuditLogItem,
    AdminAuditLogsResponse,
    AdminAlarmItem,
    AdminAlarmListResponse,
    AnnouncementCreateRequest,
    AnnouncementUpdateRequest,
    AnnouncementResponse,
    AnnouncementListResponse,
    AdminPerformanceMetricsResponse,
    CoachAssignmentsOverviewResponse,
    AssignUserRequest,
    UnassignUserRequest,
    AssignmentActionResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Administrator Cockpit"])


@router.get("/dashboard", response_model=AdminDashboardResponse)
def get_admin_dashboard(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    Returns platform summary statistics calculated from PostgreSQL database.
    Requires server-side Administrator permissions.
    """
    total_users = db.query(User).count()
    
    # Active users: users who had activity, challenge attempts, or active alarms in last 30 days
    recent_cutoff = datetime.now() - timedelta(days=30)
    active_user_ids = set(
        u[0] for u in db.query(ChallengeAttempt.user_id)
        .filter(ChallengeAttempt.created_at >= recent_cutoff)
        .distinct()
        .all()
    )
    active_user_ids.update(
        u[0] for u in db.query(Alarm.user_id)
        .filter(Alarm.is_active == True)
        .distinct()
        .all()
    )
    active_users = len(active_user_ids)

    total_alarms = db.query(Alarm).count()
    active_alarms = db.query(Alarm).filter(Alarm.is_active == True).count()
    total_challenges = db.query(ChallengeAttempt).count()
    total_snoozes = sum(int(s.snooze_count or 0) for s in db.query(AlarmSnoozeEvent).all())

    return AdminDashboardResponse(
        total_users=total_users,
        active_users=active_users,
        total_alarms=total_alarms,
        active_alarms=active_alarms,
        total_challenges=total_challenges,
        total_snoozes=total_snoozes,
        system_health="operational"
    )


@router.get("/users", response_model=List[AdminUserItem])
def get_admin_users(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    Returns list of all users from PostgreSQL with non-sensitive fields.
    Never exposes passwords, tokens, or secret keys.
    """
    users = db.query(User).order_by(desc(User.created_at)).all()
    result: List[AdminUserItem] = []

    for u in users:
        alarm_count = db.query(Alarm).filter(Alarm.user_id == u.id).count()
        habit_snap = calculate_habit_score_snapshot(db, u.id, period_days=7)

        last_attempt = (
            db.query(ChallengeAttempt)
            .filter(ChallengeAttempt.user_id == u.id)
            .order_by(desc(ChallengeAttempt.created_at))
            .first()
        )
        last_active = None
        if last_attempt and last_attempt.created_at:
            last_active = last_attempt.created_at.strftime("%Y-%m-%d %H:%M")
        elif u.last_meaningful_activity_at:
            last_active = u.last_meaningful_activity_at.strftime("%Y-%m-%d %H:%M")
        elif u.updated_at:
            last_active = u.updated_at.strftime("%Y-%m-%d %H:%M")

        result.append(
            AdminUserItem(
                id=u.id,
                name=u.name,
                email=u.email,
                role=u.role,
                provider=u.provider,
                total_alarms=alarm_count,
                habit_score=habit_snap.get("habit_score", 0.0),
                created_at=u.created_at.strftime("%Y-%m-%d %H:%M") if u.created_at else None,
                last_active=last_active,
            )
        )

    return result


@router.get("/alarms", response_model=AdminAlarmListResponse)
def get_admin_alarms(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    Returns list of all configured alarms across all users directly from the alarms table.
    """
    alarms = db.query(Alarm).order_by(desc(Alarm.created_at)).all()
    user_map = {u.id: u for u in db.query(User).all()}

    alarm_items = []
    for a in alarms:
        u = user_map.get(a.user_id)
        alarm_items.append(
            AdminAlarmItem(
                id=a.id,
                user_id=a.user_id,
                user_name=u.name if u else "Unknown User",
                user_email=u.email if u else "unknown@example.com",
                title=a.title,
                alarm_time=a.alarm_time,
                alarm_type=a.alarm_type or "One-Time",
                repeat_days=a.repeat_days or "",
                is_active=bool(a.is_active),
                challenge=a.challenge or "None",
                difficulty_level=a.difficulty_level or "Medium",
                sound=a.sound or "Radar",
                vibration=a.vibration or "Standard",
                verification_method=a.verification_method or "multi_step",
                created_at=a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else None
            )
        )

    active_count = sum(1 for a in alarms if a.is_active)
    return AdminAlarmListResponse(
        total_alarms=len(alarms),
        active_alarms=active_count,
        alarms=alarm_items
    )


@router.delete("/users/{email}")
def delete_admin_user_by_email(
    email: str,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    Deletes user account by email. Prevents self-deletion.
    """
    if admin_user.email.lower() == email.lower().strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the currently logged-in administrator account."
        )

    target_user = db.query(User).filter(User.email == email.lower().strip()).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with email '{email}' not found."
        )

    db.delete(target_user)
    db.commit()
    return {"status": "success", "message": f"User account '{email}' deleted successfully."}


@router.put("/users/{user_id}/role")
def update_user_role(
    user_id: int,
    payload: AdminRoleUpdateRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    Updates user role (e.g., USER, Wellness Coach, Administrator).
    """
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found."
        )

    valid_roles = {"USER", "WELLNESS COACH", "COACH", "ADMINISTRATOR", "ADMIN", "STUDENT"}
    new_role = payload.role.strip()
    if new_role.upper() not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {valid_roles}"
        )

    target_user.role = new_role
    db.commit()
    db.refresh(target_user)

    return {
        "status": "success",
        "message": f"Updated role for {target_user.email} to {target_user.role}.",
        "user_id": target_user.id,
        "new_role": target_user.role
    }


@router.get("/analytics", response_model=AdminAnalyticsResponse)
def get_admin_analytics(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    Calculates aggregated platform analytics from real PostgreSQL data.
    """
    total_users = db.query(User).count()
    users = db.query(User).all()

    # Role distribution
    role_dist: Dict[str, int] = defaultdict(int)
    for u in users:
        r = (u.role or "USER").upper()
        if "ADMIN" in r:
            role_dist["Admin"] += 1
        elif "COACH" in r:
            role_dist["Coach"] += 1
        else:
            role_dist["User"] += 1

    total_alarms = db.query(Alarm).count()
    active_alarms = db.query(Alarm).filter(Alarm.is_active == True).count()
    all_attempts = db.query(ChallengeAttempt).all()
    total_challenges = len(all_attempts)

    correct_challenges = sum(1 for a in all_attempts if a.is_correct)
    chal_accuracy = round((correct_challenges / total_challenges) * 100.0, 1) if total_challenges else 0.0

    # Verification times & results
    verif_times = [a.time_taken for a in all_attempts if a.time_taken and a.time_taken > 0]
    avg_verif_time = round(mean(verif_times), 1) if verif_times else 0.0

    passed_attempts = sum(1 for a in all_attempts if a.verification_status in {"passed", "completed"} or a.is_correct)
    failed_verif = sum(1 for a in all_attempts if a.verification_status in {"failed", "timeout"})
    triggered_alarms = max(len(set(a.session_id for a in all_attempts if a.session_id)), passed_attempts)

    total_snoozes = sum(int(s.snooze_count or 0) for s in db.query(AlarmSnoozeEvent).all())

    # Most used challenge types
    type_counts: Dict[str, int] = defaultdict(int)
    for a in all_attempts:
        t = a.challenge_type or "Math Problems"
        type_counts[t] += 1

    most_used_types = [
        {"challenge_type": t, "count": type_counts.get(t, 0)}
        for t in ALLOWED_TYPES
    ]
    most_used_types.sort(key=lambda x: x["count"], reverse=True)

    # Most used difficulty levels
    diff_counts: Dict[str, int] = defaultdict(int)
    for a in all_attempts:
        d = a.difficulty or "Medium"
        diff_counts[d] += 1

    most_used_diffs = [
        {"difficulty": d, "count": diff_counts.get(d, 0)}
        for d in DIFFICULTY_LEVELS
    ]
    most_used_diffs.sort(key=lambda x: x["count"], reverse=True)

    # Habit score distribution across users
    score_dist = {
        "0-39 (Poor)": 0,
        "40-59 (Needs Improvement)": 0,
        "60-74 (Fair)": 0,
        "75-89 (Good)": 0,
        "90-100 (Excellent)": 0,
    }
    for u in users:
        snap = calculate_habit_score_snapshot(db, u.id, period_days=7)
        score = snap.get("habit_score", 0.0)
        if score >= 90:
            score_dist["90-100 (Excellent)"] += 1
        elif score >= 75:
            score_dist["75-89 (Good)"] += 1
        elif score >= 60:
            score_dist["60-74 (Fair)"] += 1
        elif score >= 40:
            score_dist["40-59 (Needs Improvement)"] += 1
        else:
            score_dist["0-39 (Poor)"] += 1

    # Helper for timezone safe comparison
    def _dt_to_utc(dt_val):
        if dt_val is None:
            return None
        if getattr(dt_val, "tzinfo", None) is not None:
            return dt_val.astimezone(timezone.utc).replace(tzinfo=None)
        return dt_val

    active_cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).replace(tzinfo=None)
    active_users = len(set(
        a.user_id for a in all_attempts if a.created_at and _dt_to_utc(a.created_at) >= active_cutoff
    ))

    # Monthly user growth trend for admin chart
    growth_trend = []
    all_alarms = db.query(Alarm).all()
    alarm_types_dist: Dict[str, int] = defaultdict(int)
    for al in all_alarms:
        c_name = al.challenge if (al.challenge and al.challenge != "None") else al.verification_method
        if not c_name or c_name == "None":
            c_name = "Standard Alarm"
        alarm_types_dist[c_name] += 1

    # Build chronological 6-month growth trend from real user creation dates
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    for i in range(5, -1, -1):
        m_dt = now_utc - timedelta(days=i * 30)
        m_label = m_dt.strftime("%b %Y")
        u_count = sum(1 for u in users if u.created_at and _dt_to_utc(u.created_at) <= m_dt)
        growth_trend.append({"month": m_label, "count": u_count})

    return AdminAnalyticsResponse(
        total_users=total_users,
        active_users=active_users,
        total_alarms=total_alarms,
        active_alarms=active_alarms,
        triggered_alarms=triggered_alarms,
        successful_wakeups=passed_attempts,
        failed_verifications=failed_verif,
        total_snoozes=total_snoozes,
        total_challenges=total_challenges,
        challenge_accuracy=chal_accuracy,
        average_verification_time_seconds=avg_verif_time,
        most_used_challenge_types=most_used_types,
        most_used_difficulty_levels=most_used_diffs,
        habit_score_distribution=score_dist,
        role_distribution=dict(role_dist),
        user_growth_trend=growth_trend,
        alarm_types_distribution=dict(alarm_types_dist)
    )


@router.get("/recommendations", response_model=AdminRecommendationsResponse)
def get_admin_recommendations_stats(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    Returns aggregated recommendation statistics calculated from real PostgreSQL database.
    """
    users = db.query(User).all()
    total_users = len(users)
    all_attempts = db.query(ChallengeAttempt).all()
    all_alarms = db.query(Alarm).all()
    all_snoozes = db.query(AlarmSnoozeEvent).all()

    # Real metrics from users, alarms, challenges
    sleep_count = sum(1 for u in users if u.target_bedtime or u.estimated_sleep_start)
    wake_count = sum(1 for a in all_alarms if a.is_active)
    habit_count = total_users
    prod_count = sum(1 for a in all_attempts if a.is_correct)
    chal_count = len(all_attempts)

    by_cat = {
        "Sleep Improvement": sleep_count,
        "Wake-Up Optimization": wake_count,
        "Habit Improvement": habit_count,
        "Productivity": prod_count,
        "Personalized Challenge": chal_count,
    }
    total_recs = sum(by_cat.values())

    failed_attempts = sum(1 for a in all_attempts if not a.is_correct)
    high_prio = failed_attempts + len(all_snoozes)
    med_prio = sum(1 for a in all_attempts if a.is_correct)
    low_prio = max(0, total_recs - high_prio - med_prio)

    by_priority = {
        "High": high_prio,
        "Medium": med_prio,
        "Low": low_prio,
    }

    common_types = [
        {"type": "Adaptive Challenge Calibration", "count": chal_count},
        {"type": "Snooze Inertia Reduction", "count": len(all_snoozes)},
        {"type": "Bedtime Regularity Tracking", "count": sleep_count},
        {"type": "Circadian Rhythm Alignment", "count": wake_count},
        {"type": "Morning Routine Habit Booster", "count": habit_count},
    ]

    recent_act = []
    recent_attempts = (
        db.query(ChallengeAttempt)
        .order_by(desc(ChallengeAttempt.created_at))
        .limit(10)
        .all()
    )
    for a in recent_attempts:
        status_desc = "passed" if a.is_correct else "failed"
        recent_act.append({
            "timestamp": a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else "Recently",
            "event": f"Verification attempt for {a.challenge_type} ({a.difficulty}) - {status_desc}",
            "category": "Personalized Challenge"
        })

    return AdminRecommendationsResponse(
        total_recommendations_generated=total_recs,
        by_category=by_cat,
        by_priority=by_priority,
        most_common_recommendation_types=common_types,
        recent_activity=recent_act,
    )


@router.get("/logs", response_model=AdminAuditLogsResponse)
def get_admin_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    Returns chronological system audit ledger generated from real PostgreSQL tables.
    """
    events = []

    # 1. Users registered
    users = db.query(User).order_by(desc(User.created_at)).limit(limit).all()
    for u in users:
        if u.created_at:
            events.append({
                "dt": u.created_at,
                "time": u.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "module": "ACCOUNT",
                "msg": f"Account '{u.name}' ({u.email}) registered with role [{u.role}].",
                "status": "success"
            })

    # 2. Alarms created/configured
    alarms = db.query(Alarm).order_by(desc(Alarm.created_at)).limit(limit).all()
    for a in alarms:
        if a.created_at:
            events.append({
                "dt": a.created_at,
                "time": a.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "module": "ALARMS",
                "msg": f"Alarm '{a.title}' configured for {a.alarm_time} (Method: {a.verification_method}, Active: {a.is_active}).",
                "status": "info"
            })

    # 3. Challenge attempts
    attempts = db.query(ChallengeAttempt).order_by(desc(ChallengeAttempt.created_at)).limit(limit).all()
    for att in attempts:
        if att.created_at:
            st = "success" if att.is_correct else "warning"
            result_str = "Solved successfully" if att.is_correct else "Verification failed/timed out"
            events.append({
                "dt": att.created_at,
                "time": att.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "module": "VERIFICATION",
                "msg": f"Cognitive challenge '{att.challenge_type}' ({att.difficulty}) - {result_str} ({att.time_taken}s).",
                "status": st
            })

    # 4. Snooze events
    snoozes = db.query(AlarmSnoozeEvent).order_by(desc(AlarmSnoozeEvent.created_at)).limit(limit).all()
    for sn in snoozes:
        if sn.created_at:
            events.append({
                "dt": sn.created_at,
                "time": sn.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "module": "SNOOZE",
                "msg": f"Alarm snooze event recorded (Snooze count: {sn.snooze_count}).",
                "status": "warning"
            })

    # 5. Announcements
    announcements = db.query(PlatformAnnouncement).order_by(desc(PlatformAnnouncement.created_at)).limit(limit).all()
    for ann in announcements:
        if ann.created_at:
            events.append({
                "dt": ann.created_at,
                "time": ann.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "module": "ANNOUNCEMENT",
                "msg": f"Broadcast announcement '{ann.title}' created with [{ann.priority}] priority.",
                "status": "info"
            })

    # 6. Notifications
    notifications = db.query(Notification).order_by(desc(Notification.created_at)).limit(limit).all()
    for n in notifications:
        if n.created_at:
            events.append({
                "dt": n.created_at,
                "time": n.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "module": "NOTIFICATIONS",
                "msg": f"Notification '{n.title}' dispatched via {n.delivery_channel} ({n.delivery_status}).",
                "status": "success" if n.delivery_status in {"sent", "delivered"} else "info"
            })

    # Sort descending by timestamp
    def _sort_key(x):
        dt = x["dt"]
        if dt is None:
            return datetime.min
        if getattr(dt, "tzinfo", None) is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    events.sort(key=_sort_key, reverse=True)
    trimmed = events[:limit]

    log_items = [
        AdminAuditLogItem(time=e["time"], module=e["module"], msg=e["msg"], status=e["status"])
        for e in trimmed
    ]
    return AdminAuditLogsResponse(total=len(log_items), logs=log_items)


@router.get("/reports", response_model=AdminReportsResponse)
def get_admin_system_reports(
    period: str = Query("daily", description="Period granularity: daily, weekly, monthly"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    Generates real platform audit and activity reports with date filtering.
    """
    today = date.today()
    query_start = today - timedelta(days=14)
    query_end = today

    if start_date:
        try:
            query_start = datetime.strptime(start_date, "%Y-%m-%d").date()
        except Exception:
            pass
    if end_date:
        try:
            query_end = datetime.strptime(end_date, "%Y-%m-%d").date()
        except Exception:
            pass

    start_dt = datetime.combine(query_start, datetime.min.time())
    end_dt = datetime.combine(query_end, datetime.max.time())

    attempts = (
        db.query(ChallengeAttempt)
        .filter(ChallengeAttempt.created_at >= start_dt, ChallengeAttempt.created_at <= end_dt)
        .order_by(ChallengeAttempt.created_at.asc())
        .all()
    )

    snoozes = (
        db.query(AlarmSnoozeEvent)
        .filter(AlarmSnoozeEvent.created_at >= start_dt, AlarmSnoozeEvent.created_at <= end_dt)
        .all()
    )

    users = db.query(User).all()
    active_user_ids = set(a.user_id for a in attempts)
    total_active_users = len(active_user_ids) if active_user_ids else len(users)

    total_attempts = len(attempts)
    passed_attempts = sum(1 for a in attempts if a.is_correct or a.verification_status in {"passed", "completed"})
    verif_rate = round((passed_attempts / total_attempts) * 100.0, 1) if total_attempts else 100.0
    chal_acc = round((sum(1 for a in attempts if a.is_correct) / total_attempts) * 100.0, 1) if total_attempts else 100.0

    habit_scores = [calculate_habit_score_snapshot(db, u.id, period_days=7)["habit_score"] for u in users]
    avg_habit = round(mean(habit_scores), 1) if habit_scores else 75.0
    snooze_rate = round(len(snoozes) / max(1, len(attempts)), 2)

    # Daily platform activity
    daily_map: Dict[str, dict] = defaultdict(lambda: {"wakeups": 0, "challenges": 0, "snoozes": 0, "accuracy": []})
    for a in attempts:
        d_str = a.created_at.strftime("%Y-%m-%d") if a.created_at else "Unknown"
        daily_map[d_str]["challenges"] += 1
        if a.is_correct:
            daily_map[d_str]["wakeups"] += 1
            daily_map[d_str]["accuracy"].append(100.0)
        else:
            daily_map[d_str]["accuracy"].append(0.0)

    for s in snoozes:
        d_str = s.created_at.strftime("%Y-%m-%d") if s.created_at else "Unknown"
        daily_map[d_str]["snoozes"] += int(s.snooze_count or 1)

    daily_activity = []
    for d_str in sorted(daily_map.keys()):
        item = daily_map[d_str]
        acc = round(mean(item["accuracy"]), 1) if item["accuracy"] else 0.0
        daily_activity.append({
            "date": d_str,
            "total_wakeups": item["wakeups"],
            "total_challenges": item["challenges"],
            "total_snoozes": item["snoozes"],
            "accuracy_percentage": acc,
        })

    return AdminReportsResponse(
        period=period,
        start_date=query_start.isoformat(),
        end_date=query_end.isoformat(),
        total_active_users=total_active_users,
        alarm_events_count=total_attempts,
        verification_success_rate=verif_rate,
        challenge_accuracy_rate=chal_acc,
        average_habit_score=avg_habit,
        snooze_frequency_rate=snooze_rate,
        daily_platform_activity=daily_activity,
    )


# =========================================================================
# Requirement 11: Admin Platform Announcement Management Endpoints
# =========================================================================

def _map_announcement(a: PlatformAnnouncement) -> AnnouncementResponse:
    return AnnouncementResponse(
        id=a.id,
        title=a.title,
        message=a.message,
        priority=a.priority or "normal",
        target_role=getattr(a, "target_role", "all") or "all",
        is_active=a.is_active,
        start_time=a.start_time.strftime("%Y-%m-%d %H:%M:%S") if a.start_time else None,
        end_time=a.end_time.strftime("%Y-%m-%d %H:%M:%S") if a.end_time else None,
        created_by=a.created_by,
        created_at=a.created_at.strftime("%Y-%m-%d %H:%M:%S") if a.created_at else None,
        updated_at=a.updated_at.strftime("%Y-%m-%d %H:%M:%S") if a.updated_at else None,
    )


@router.get("/announcements", response_model=AnnouncementListResponse)
def get_admin_announcements(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """
    Returns all platform announcements (active and inactive). Requires Admin permissions.
    """
    announcements = db.query(PlatformAnnouncement).order_by(desc(PlatformAnnouncement.created_at)).all()
    active_count = sum(1 for a in announcements if a.is_active)
    return AnnouncementListResponse(
        total=len(announcements),
        active_count=active_count,
        announcements=[_map_announcement(a) for a in announcements],
    )


@router.post("/announcements", response_model=AnnouncementResponse, status_code=status.HTTP_201_CREATED)
def create_admin_announcement(
    payload: AnnouncementCreateRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """
    Creates a new platform announcement and broadcasts to targeted users. Requires Admin permissions.
    """
    if not payload.title.strip() or not payload.message.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Title and message cannot be empty.",
        )

    valid_priorities = {"low", "normal", "high", "urgent"}
    priority = (payload.priority or "normal").lower()
    if priority not in valid_priorities:
        priority = "normal"

    target_role = (payload.target_role or "all").strip().lower()

    ann = PlatformAnnouncement(
        title=payload.title.strip(),
        message=payload.message.strip(),
        priority=priority,
        target_role=target_role,
        is_active=payload.is_active if payload.is_active is not None else True,
        start_time=payload.start_time,
        end_time=payload.end_time,
        created_by=admin_user.id,
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    logger.info(f"Created platform announcement ID {ann.id}: '{ann.title}' (target: {target_role}) by admin {admin_user.email}")

    if ann.is_active:
        try:
            broadcast_announcements_to_users(db)
        except Exception as e:
            logger.warning(f"Error broadcasting announcement {ann.id}: {e}")

    return _map_announcement(ann)


@router.put("/announcements/{announcement_id}", response_model=AnnouncementResponse)
def update_admin_announcement(
    announcement_id: int,
    payload: AnnouncementUpdateRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """
    Updates an existing platform announcement. Requires Admin permissions.
    """
    ann = db.query(PlatformAnnouncement).filter(PlatformAnnouncement.id == announcement_id).first()
    if not ann:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Announcement with ID {announcement_id} not found.",
        )

    if payload.title is not None:
        if not payload.title.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Title cannot be empty.")
        ann.title = payload.title.strip()

    if payload.message is not None:
        if not payload.message.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty.")
        ann.message = payload.message.strip()

    if payload.priority is not None:
        ann.priority = payload.priority.lower()

    if payload.target_role is not None:
        ann.target_role = payload.target_role.strip().lower()

    if payload.is_active is not None:
        ann.is_active = payload.is_active

    if payload.start_time is not None:
        ann.start_time = payload.start_time

    if payload.end_time is not None:
        ann.end_time = payload.end_time

    db.commit()
    db.refresh(ann)

    if ann.is_active:
        try:
            broadcast_announcements_to_users(db)
        except Exception as e:
            logger.warning(f"Error broadcasting updated announcement {ann.id}: {e}")

    return _map_announcement(ann)


@router.patch("/announcements/{announcement_id}/status", response_model=AnnouncementResponse)
def toggle_admin_announcement_status(
    announcement_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """
    Toggles an announcement active/inactive status. Requires Admin permissions.
    """
    ann = db.query(PlatformAnnouncement).filter(PlatformAnnouncement.id == announcement_id).first()
    if not ann:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Announcement with ID {announcement_id} not found.",
        )

    ann.is_active = not ann.is_active
    db.commit()
    db.refresh(ann)

    if ann.is_active:
        try:
            broadcast_announcements_to_users(db)
        except Exception as e:
            logger.warning(f"Error broadcasting toggled announcement {ann.id}: {e}")

    return _map_announcement(ann)


@router.delete("/announcements/{announcement_id}", response_model=dict)
def delete_admin_announcement(
    announcement_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """
    Deletes a platform announcement. Requires Admin permissions.
    """
    ann = db.query(PlatformAnnouncement).filter(PlatformAnnouncement.id == announcement_id).first()
    if not ann:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Announcement with ID {announcement_id} not found.",
        )

    db.delete(ann)
    db.commit()
    return {"status": "success", "message": f"Announcement {announcement_id} deleted successfully."}


@router.get("/performance-metrics", response_model=AdminPerformanceMetricsResponse)
def get_admin_performance_metrics(
    period_days: int = Query(7, ge=1, le=365, description="Number of days to evaluate (7, 30, 90)"),
    start_date: Optional[str] = Query(None, description="Optional custom start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Optional custom end date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """
    Consolidated Performance Metrics and System Evaluation API (Requirement 8).
    Evaluates real PostgreSQL database records and real application performance measurements:
    - 1. Alarm Performance Metrics (Dismissal Success Rate, Verification Accuracy, Snooze Reduction Rate)
    - 2. Cognitive Challenge Metrics (Completion Rate, Accuracy by Type/Difficulty/Period, Difficulty Adaptation Effectiveness)
    - 3. Habit Formation Metrics (Habit Score Improvement, Wake-Up Consistency Rate, Sleep Schedule Adherence)
    - 4. Recommendation Metrics (Relevance, User Engagement Improvement, Productivity Improvement Rate)
    - 5. System Performance Metrics (API Response Time, Dashboard Loading Speed, Challenge Latency, Concurrent User Capacity)
    """
    return calculate_performance_metrics(
        db=db,
        period_days=period_days,
        start_date_str=start_date,
        end_date_str=end_date
    )


# ============================================================================
# Admin Coach-User Assignment Cockpit Endpoints
# ============================================================================

@router.get("/coach-assignments", response_model=CoachAssignmentsOverviewResponse, summary="Get all coaches and user assignments")
def get_coach_assignments(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """
    Returns full coach-user assignment matrix for Admin management.
    Includes all coaches with their assigned patient lists and available normal users.
    Requires server-side Administrator privileges.
    """
    return get_all_coach_assignments_overview(db)


@router.post("/coach-assignments/assign", response_model=AssignmentActionResponse, summary="Assign users to a coach")
def assign_users_to_coach_endpoint(
    payload: AssignUserRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """
    Assigns one or more users to a specific coach.
    Reassigns automatically if user was actively assigned to another coach.
    Requires server-side Administrator privileges.
    """
    if not payload.user_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide at least one user ID to assign."
        )

    assigned_count = 0
    affected_ids = []

    for uid in payload.user_ids:
        assign_user_to_coach(
            db=db,
            coach_id=payload.coach_id,
            user_id=uid,
            admin_id=admin_user.id
        )
        assigned_count += 1
        affected_ids.append(uid)

    coach = db.query(User).filter(User.id == payload.coach_id).first()
    coach_name = coach.name if coach else f"Coach #{payload.coach_id}"

    return AssignmentActionResponse(
        status="success",
        message=f"Successfully assigned {assigned_count} user(s) to coach '{coach_name}'.",
        assigned_count=assigned_count,
        affected_user_ids=affected_ids
    )


@router.post("/coach-assignments/unassign", response_model=AssignmentActionResponse, summary="Unassign users from a coach")
def unassign_users_from_coach_endpoint(
    payload: UnassignUserRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """
    Removes the active assignment of one or more users from a coach.
    Requires server-side Administrator privileges.
    """
    if not payload.user_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide at least one user ID to unassign."
        )

    unassigned_count = 0
    affected_ids = []

    for uid in payload.user_ids:
        success = unassign_user_from_coach(
            db=db,
            coach_id=payload.coach_id,
            user_id=uid
        )
        if success:
            unassigned_count += 1
            affected_ids.append(uid)

    return AssignmentActionResponse(
        status="success",
        message=f"Successfully unassigned {unassigned_count} user(s) from coach #{payload.coach_id}.",
        assigned_count=unassigned_count,
        affected_user_ids=affected_ids
    )
