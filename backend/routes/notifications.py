import logging
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database import get_db
from models import Notification, User, UserNotificationPreference
from routes.auth import get_current_user
from schemas import (
    NotificationResponse,
    NotificationListResponse,
    NotificationUnreadCountResponse,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdateRequest,
    NotificationHistoryResponse,
    NotificationHistoryItemResponse,
    DeliveryProviderStatusResponse,
    ScheduleReportRequest,
    ScheduleReportResponse,
)
from services.notification_service import (
    evaluate_user_notifications,
    get_or_create_user_preferences,
    format_time_ago,
    dispatch_scheduled_report_notification,
)
from services.delivery_service import (
    get_provider_status,
    validate_phone_number,
)

logger = logging.getLogger("routes.notifications")

router = APIRouter(prefix="/api/notifications", tags=["Notification & Reminder System"])


def _map_notification(n: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=n.id,
        user_id=n.user_id,
        type=n.type,
        title=n.title,
        message=n.message,
        priority=n.priority or "normal",
        is_read=n.is_read,
        created_at=n.created_at.strftime("%Y-%m-%d %H:%M:%S") if n.created_at else None,
        scheduled_for=n.scheduled_for.strftime("%Y-%m-%d %H:%M:%S") if n.scheduled_for else None,
        sent_at=n.sent_at.strftime("%Y-%m-%d %H:%M:%S") if n.sent_at else None,
        expires_at=n.expires_at.strftime("%Y-%m-%d %H:%M:%S") if n.expires_at else None,
        reference_type=n.reference_type,
        reference_id=n.reference_id,
        action_url=n.action_url,
        time_ago=format_time_ago(n.created_at),
        delivery_channel=getattr(n, "delivery_channel", "in_app") or "in_app",
        delivery_status=getattr(n, "delivery_status", "delivered") or "delivered",
        email_status=getattr(n, "email_status", None),
        sms_status=getattr(n, "sms_status", None),
    )


def _map_preferences(pref: UserNotificationPreference, user: User) -> NotificationPreferenceResponse:
    return NotificationPreferenceResponse(
        user_id=pref.user_id,
        user_email=user.email,
        user_phone_number=user.phone_number,
        phone_number_configured=bool(user.phone_number and user.phone_number.strip()),
        preferred_channel=getattr(pref, "preferred_channel", "both") or "both",
        bedtime_reminders=bool(pref.bedtime_reminders),
        wake_up_reminders=bool(pref.wake_up_reminders),
        habit_alerts=bool(pref.habit_alerts),
        challenge_reminders=bool(pref.challenge_reminders),
        progress_notifications=bool(pref.progress_notifications),
        platform_announcements=bool(pref.platform_announcements),
        browser_notifications_enabled=bool(pref.browser_notifications_enabled),
        bedtime_email=bool(getattr(pref, "bedtime_email", True)),
        bedtime_sms=bool(getattr(pref, "bedtime_sms", False)),
        wakeup_email=bool(getattr(pref, "wakeup_email", True)),
        wakeup_sms=bool(getattr(pref, "wakeup_sms", True)),
        habit_email=bool(getattr(pref, "habit_email", True)),
        habit_sms=bool(getattr(pref, "habit_sms", False)),
        challenge_email=bool(getattr(pref, "challenge_email", True)),
        challenge_sms=bool(getattr(pref, "challenge_sms", False)),
        progress_email=bool(getattr(pref, "progress_email", True)),
        progress_sms=bool(getattr(pref, "progress_sms", False)),
        announcement_email=bool(getattr(pref, "announcement_email", True)),
        announcement_sms=bool(getattr(pref, "announcement_sms", False)),
        bedtime_lead_minutes=getattr(pref, "bedtime_lead_minutes", 30) or 30,
        wakeup_lead_minutes=getattr(pref, "wakeup_lead_minutes", 10) or 10,
        report_delivery_enabled=bool(getattr(pref, "report_delivery_enabled", False)),
        report_delivery_channel=getattr(pref, "report_delivery_channel", "email") or "email",
        report_delivery_frequency=getattr(pref, "report_delivery_frequency", "weekly") or "weekly",
        report_delivery_type=getattr(pref, "report_delivery_type", "habit") or "habit",
    )


@router.get("/", response_model=NotificationListResponse)
def get_user_notifications(
    type: Optional[str] = Query(None, description="Filter by notification type"),
    unread_only: bool = Query(False, description="Filter only unread notifications"),
    limit: int = Query(50, ge=1, le=100, description="Max notifications to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns user notifications with real-time evaluation of pending reminders, habit alerts, and announcements.
    """
    try:
        evaluate_user_notifications(db, current_user)
    except Exception as e:
        logger.warning(f"Error during notification evaluation: {e}")

    query = db.query(Notification).filter(Notification.user_id == current_user.id)

    if type and type != "all":
        query = query.filter(Notification.type == type)

    if unread_only:
        query = query.filter(Notification.is_read == False)

    total_count = query.count()
    unread_count = db.query(Notification).filter(Notification.user_id == current_user.id, Notification.is_read == False).count()

    notifications = query.order_by(desc(Notification.created_at)).limit(limit).all()

    return NotificationListResponse(
        total=total_count,
        unread_count=unread_count,
        notifications=[_map_notification(n) for n in notifications],
    )


@router.get("/unread-count", response_model=NotificationUnreadCountResponse)
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fast query returning unread notification count for the navbar badge.
    """
    count = db.query(Notification).filter(Notification.user_id == current_user.id, Notification.is_read == False).count()
    return NotificationUnreadCountResponse(unread_count=count)


@router.get("/history", response_model=NotificationHistoryResponse)
def get_notification_history(
    channel: Optional[str] = Query(None, description="Filter by delivery channel (email, sms, both, in_app)"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by delivery status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns complete notification delivery audit history for the authenticated user.
    """
    query = db.query(Notification).filter(Notification.user_id == current_user.id)

    if channel and channel != "all":
        if channel == "email":
            query = query.filter(Notification.delivery_channel.in_(["email", "both"]))
        elif channel == "sms":
            query = query.filter(Notification.delivery_channel.in_(["sms", "both"]))
        else:
            query = query.filter(Notification.delivery_channel == channel)

    if status_filter and status_filter != "all":
        query = query.filter(Notification.delivery_status == status_filter)

    total = query.count()
    items = query.order_by(desc(Notification.created_at)).offset(offset).limit(limit).all()

    history_items = [
        NotificationHistoryItemResponse(
            id=n.id,
            type=n.type,
            title=n.title,
            message=n.message,
            delivery_channel=getattr(n, "delivery_channel", "in_app") or "in_app",
            delivery_status=getattr(n, "delivery_status", "delivered") or "delivered",
            email_status=getattr(n, "email_status", None),
            sms_status=getattr(n, "sms_status", None),
            priority=n.priority or "normal",
            created_at=n.created_at.strftime("%Y-%m-%d %H:%M:%S") if n.created_at else None,
            time_ago=format_time_ago(n.created_at),
        )
        for n in items
    ]

    return NotificationHistoryResponse(total=total, history=history_items)


@router.get("/providers", response_model=DeliveryProviderStatusResponse)
def get_delivery_providers_status(
    current_user: User = Depends(get_current_user),
):
    """
    Returns configured availability of SMTP and Twilio delivery services without exposing keys.
    """
    return get_provider_status()


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Marks a specific notification as read.
    """
    notif = db.query(Notification).filter(Notification.id == notification_id, Notification.user_id == current_user.id).first()
    if not notif:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )

    notif.is_read = True
    db.commit()
    db.refresh(notif)
    return _map_notification(notif)


@router.patch("/read-all", response_model=dict)
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Marks all notifications for current user as read.
    """
    updated_count = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_read == False)
        .update({"is_read": True})
    )
    db.commit()
    return {"status": "success", "message": f"Marked {updated_count} notifications as read.", "updated_count": updated_count}


@router.delete("/clear-all", response_model=dict)
def clear_all_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Clears all read notifications for current user.
    """
    deleted_count = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_read == True)
        .delete()
    )
    db.commit()
    return {"status": "success", "message": f"Cleared {deleted_count} notifications.", "deleted_count": deleted_count}


@router.delete("/{notification_id}", response_model=dict)
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Deletes a specific notification.
    """
    notif = db.query(Notification).filter(Notification.id == notification_id, Notification.user_id == current_user.id).first()
    if not notif:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )

    db.delete(notif)
    db.commit()
    return {"status": "success", "message": "Notification dismissed."}


@router.get("/preferences", response_model=NotificationPreferenceResponse)
def get_notification_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns complete multi-channel notification preferences and user contact details.
    """
    pref = get_or_create_user_preferences(db, current_user.id)
    return _map_preferences(pref, current_user)


@router.put("/preferences", response_model=NotificationPreferenceResponse)
def update_notification_preferences(
    payload: NotificationPreferenceUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Updates multi-channel notification preferences, phone number, and report scheduling.
    """
    pref = get_or_create_user_preferences(db, current_user.id)

    # 1. Update phone number if provided
    if payload.phone_number is not None:
        raw_phone = payload.phone_number.strip()
        if raw_phone:
            is_valid, clean_phone = validate_phone_number(raw_phone)
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=clean_phone
                )
            current_user.phone_number = clean_phone
        else:
            current_user.phone_number = None
        db.add(current_user)

    # 2. Update Global Preferred Channel
    if payload.preferred_channel is not None:
        valid_channels = {"email", "sms", "both", "disabled"}
        chan = payload.preferred_channel.lower()
        if chan not in valid_channels:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid preferred_channel '{chan}'. Must be one of: {valid_channels}"
            )
        pref.preferred_channel = chan

        # If user switches global channel and didn't specify individual overrides, adjust defaults
        if chan == "email":
            pref.bedtime_email = True
            pref.bedtime_sms = False
            pref.wakeup_email = True
            pref.wakeup_sms = False
            pref.habit_email = True
            pref.habit_sms = False
            pref.challenge_email = True
            pref.challenge_sms = False
            pref.progress_email = True
            pref.progress_sms = False
            pref.announcement_email = True
            pref.announcement_sms = False
        elif chan == "sms":
            pref.bedtime_email = False
            pref.bedtime_sms = True
            pref.wakeup_email = False
            pref.wakeup_sms = True
            pref.habit_email = False
            pref.habit_sms = True
            pref.challenge_email = False
            pref.challenge_sms = True
            pref.progress_email = False
            pref.progress_sms = True
            pref.announcement_email = False
            pref.announcement_sms = True
        elif chan == "both":
            pref.bedtime_email = True
            pref.bedtime_sms = True
            pref.wakeup_email = True
            pref.wakeup_sms = True
            pref.habit_email = True
            pref.habit_sms = True
            pref.challenge_email = True
            pref.challenge_sms = True
            pref.progress_email = True
            pref.progress_sms = True
            pref.announcement_email = True
            pref.announcement_sms = True
        elif chan == "disabled":
            pref.bedtime_email = False
            pref.bedtime_sms = False
            pref.wakeup_email = False
            pref.wakeup_sms = False
            pref.habit_email = False
            pref.habit_sms = False
            pref.challenge_email = False
            pref.challenge_sms = False
            pref.progress_email = False
            pref.progress_sms = False
            pref.announcement_email = False
            pref.announcement_sms = False

    # 3. Individual Matrix Overrides (takes precedence over global bulk default)
    if payload.bedtime_reminders is not None:
        pref.bedtime_reminders = payload.bedtime_reminders
    if payload.wake_up_reminders is not None:
        pref.wake_up_reminders = payload.wake_up_reminders
    if payload.habit_alerts is not None:
        pref.habit_alerts = payload.habit_alerts
    if payload.challenge_reminders is not None:
        pref.challenge_reminders = payload.challenge_reminders
    if payload.progress_notifications is not None:
        pref.progress_notifications = payload.progress_notifications
    if payload.platform_announcements is not None:
        pref.platform_announcements = payload.platform_announcements
    if payload.browser_notifications_enabled is not None:
        pref.browser_notifications_enabled = payload.browser_notifications_enabled

    if payload.bedtime_email is not None:
        pref.bedtime_email = payload.bedtime_email
    if payload.bedtime_sms is not None:
        pref.bedtime_sms = payload.bedtime_sms
    if payload.wakeup_email is not None:
        pref.wakeup_email = payload.wakeup_email
    if payload.wakeup_sms is not None:
        pref.wakeup_sms = payload.wakeup_sms
    if payload.habit_email is not None:
        pref.habit_email = payload.habit_email
    if payload.habit_sms is not None:
        pref.habit_sms = payload.habit_sms
    if payload.challenge_email is not None:
        pref.challenge_email = payload.challenge_email
    if payload.challenge_sms is not None:
        pref.challenge_sms = payload.challenge_sms
    if payload.progress_email is not None:
        pref.progress_email = payload.progress_email
    if payload.progress_sms is not None:
        pref.progress_sms = payload.progress_sms
    if payload.announcement_email is not None:
        pref.announcement_email = payload.announcement_email
    if payload.announcement_sms is not None:
        pref.announcement_sms = payload.announcement_sms

    # 4. Lead Times
    if payload.bedtime_lead_minutes is not None:
        pref.bedtime_lead_minutes = payload.bedtime_lead_minutes
    if payload.wakeup_lead_minutes is not None:
        pref.wakeup_lead_minutes = payload.wakeup_lead_minutes

    # 5. Report Delivery Settings
    if payload.report_delivery_enabled is not None:
        pref.report_delivery_enabled = payload.report_delivery_enabled
    if payload.report_delivery_channel is not None:
        pref.report_delivery_channel = payload.report_delivery_channel
    if payload.report_delivery_frequency is not None:
        pref.report_delivery_frequency = payload.report_delivery_frequency
    if payload.report_delivery_type is not None:
        pref.report_delivery_type = payload.report_delivery_type

    db.commit()
    db.refresh(pref)
    db.refresh(current_user)
    return _map_preferences(pref, current_user)


@router.post("/reports/schedule", response_model=ScheduleReportResponse)
def schedule_report_delivery(
    payload: ScheduleReportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Schedules recurring report delivery (Email, SMS notification link, or Both).
    """
    pref = get_or_create_user_preferences(db, current_user.id)

    if payload.delivery_channel in ["sms", "both"] and not current_user.phone_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A configured mobile phone number is required to schedule SMS report delivery."
        )

    pref.report_delivery_enabled = payload.enabled
    pref.report_delivery_channel = payload.delivery_channel
    pref.report_delivery_frequency = payload.frequency
    pref.report_delivery_type = payload.report_type

    db.commit()
    db.refresh(pref)

    # Trigger a confirmation notification record
    dispatch_scheduled_report_notification(
        db=db,
        user=current_user,
        report_type=payload.report_type,
        download_url=f"/user/analytics.html?report={payload.report_type}"
    )

    msg = f"Scheduled {payload.frequency} {payload.report_type.title()} Report delivery via {payload.delivery_channel.upper()}."
    return ScheduleReportResponse(
        status="success",
        message=msg,
        delivery_channel=pref.report_delivery_channel,
        frequency=pref.report_delivery_frequency,
        report_type=pref.report_delivery_type,
        enabled=pref.report_delivery_enabled,
    )
