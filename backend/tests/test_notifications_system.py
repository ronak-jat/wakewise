import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from database import get_db, Base
from models import (
    User, Alarm, ChallengeAttempt, AlarmSnoozeEvent,
    Notification, PlatformAnnouncement, UserNotificationPreference
)
from main import app
from security import hash_password, create_access_token
from services.notification_service import (
    evaluate_user_notifications,
    broadcast_announcements_to_users,
    get_or_create_user_preferences
)
from services.delivery_service import (
    validate_phone_number,
    is_email_configured,
    is_sms_configured,
    get_provider_status,
    send_email_notification,
    send_sms_notification
)

# In-memory SQLite for testing
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class TestNotificationsSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=test_engine)
        app.dependency_overrides.clear()

    def setUp(self):
        Base.metadata.drop_all(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)
        self.db = TestingSessionLocal()

        # Create standard user
        self.user = User(
            name="Alice Test",
            email="alice@test.com",
            phone_number="+14155552671",
            password=hash_password("Password123"),
            role="USER",
            provider="LOCAL",
            target_bedtime="23:00",
            target_wake_time="07:00",
            inactivity_threshold_minutes=30
        )
        self.db.add(self.user)

        # Create user without phone
        self.user_no_phone = User(
            name="Bob NoPhone",
            email="bob@test.com",
            phone_number=None,
            password=hash_password("Password123"),
            role="USER",
            provider="LOCAL"
        )
        self.db.add(self.user_no_phone)

        # Create admin user
        self.admin = User(
            name="Admin Chief",
            email="admin@test.com",
            password=hash_password("AdminPass123"),
            role="ADMIN",
            provider="LOCAL"
        )
        self.db.add(self.admin)
        self.db.commit()
        self.db.refresh(self.user)
        self.db.refresh(self.user_no_phone)
        self.db.refresh(self.admin)

        self.user_token = create_access_token(data={"sub": self.user.email, "role": self.user.role})
        self.user_headers = {"Authorization": f"Bearer {self.user_token}"}

        self.user_no_phone_token = create_access_token(data={"sub": self.user_no_phone.email, "role": self.user_no_phone.role})
        self.user_no_phone_headers = {"Authorization": f"Bearer {self.user_no_phone_token}"}

        self.admin_token = create_access_token(data={"sub": self.admin.email, "role": self.admin.role})
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}

    def tearDown(self):
        self.db.close()

    def test_01_user_preferences_default_creation(self):
        """Test default preferences creation and retrieval."""
        prefs = get_or_create_user_preferences(self.db, self.user.id)
        self.assertIsNotNone(prefs)
        self.assertTrue(prefs.bedtime_reminders)
        self.assertTrue(prefs.wake_up_reminders)
        self.assertTrue(prefs.habit_alerts)
        self.assertTrue(prefs.challenge_reminders)
        self.assertTrue(prefs.progress_notifications)
        self.assertTrue(prefs.platform_announcements)
        self.assertEqual(prefs.preferred_channel, "both")

        # API get test
        resp = self.client.get("/api/notifications/preferences", headers=self.user_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["bedtime_reminders"])
        self.assertEqual(data["preferred_channel"], "both")

    def test_02_update_user_preferences(self):
        """Test updating notification preferences via PUT /api/notifications/preferences."""
        update_payload = {
            "preferred_channel": "both",
            "bedtime_reminders": False,
            "bedtime_email": False,
            "bedtime_sms": False,
            "wake_up_reminders": True,
            "wakeup_email": True,
            "wakeup_sms": True,
            "habit_alerts": False,
            "habit_email": False,
            "habit_sms": False,
            "challenge_reminders": True,
            "challenge_email": True,
            "challenge_sms": True,
            "progress_notifications": True,
            "progress_email": True,
            "progress_sms": False,
            "platform_announcements": True,
            "announcement_email": True,
            "announcement_sms": False,
            "bedtime_lead_minutes": 45,
            "wakeup_lead_minutes": 15
        }
        resp = self.client.put("/api/notifications/preferences", json=update_payload, headers=self.user_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["preferred_channel"], "both")
        self.assertFalse(data["bedtime_email"])
        self.assertTrue(data["wakeup_sms"])
        self.assertEqual(data["bedtime_lead_minutes"], 45)
        self.assertEqual(data["wakeup_lead_minutes"], 15)

    def test_03_bedtime_reminder_generation_and_deduplication(self):
        """Test bedtime reminder generation when current time is within lead time window."""
        now = datetime.now(timezone.utc).replace(hour=22, minute=40, second=0, microsecond=0)
        
        # Run evaluation with mock current time
        evaluate_user_notifications(self.db, self.user, now_dt=now)
        self.db.commit()

        # Should generate 1 bedtime reminder
        bedtime_notifs = self.db.query(Notification).filter(
            Notification.user_id == self.user.id,
            Notification.type == "bedtime"
        ).all()
        self.assertGreaterEqual(len(bedtime_notifs), 1)
        self.assertIn("bedtime", bedtime_notifs[0].title.lower())

        # Second evaluation with same date should NOT duplicate due to dedup_key
        count_before = len(bedtime_notifs)
        evaluate_user_notifications(self.db, self.user, now_dt=now + timedelta(minutes=5))
        self.db.commit()
        
        count_after = self.db.query(Notification).filter(
            Notification.user_id == self.user.id,
            Notification.type == "bedtime"
        ).count()
        self.assertEqual(count_after, count_before)

    def test_04_wake_up_and_challenge_reminders(self):
        """Test wake-up and challenge reminder generation for active alarms."""
        alarm = Alarm(
            user_id=self.user.id,
            title="Morning Rise",
            alarm_time="07:00",
            alarm_type="Daily",
            challenge="Math Problems",
            difficulty_level="Medium",
            is_active=True
        )
        self.db.add(alarm)
        self.db.commit()

        now = datetime.now(timezone.utc).replace(hour=6, minute=52, second=0, microsecond=0)
        evaluate_user_notifications(self.db, self.user, now_dt=now)
        self.db.commit()

        wake_notifs = self.db.query(Notification).filter(
            Notification.user_id == self.user.id,
            Notification.type == "wake_up"
        ).all()
        self.assertEqual(len(wake_notifs), 1)
        self.assertIn("07:00", wake_notifs[0].message)

        challenge_notifs = self.db.query(Notification).filter(
            Notification.user_id == self.user.id,
            Notification.type == "challenge"
        ).all()
        self.assertEqual(len(challenge_notifs), 1)
        self.assertIn("Math Problems", challenge_notifs[0].message)

    def test_05_habit_alert_generation(self):
        """Test habit alert generated when user has high snooze count (>= 3)."""
        alarm = Alarm(
            user_id=self.user.id,
            title="Morning Rise",
            alarm_time="07:00",
            alarm_type="Daily",
            challenge="Math Problems",
            difficulty_level="Medium",
            is_active=True
        )
        self.db.add(alarm)
        self.db.commit()

        now = datetime.now(timezone.utc)
        for i in range(3):
            snooze = AlarmSnoozeEvent(
                user_id=self.user.id,
                alarm_id=alarm.id,
                snooze_count=1,
                created_at=now - timedelta(minutes=10 * i)
            )
            self.db.add(snooze)
        self.db.commit()

        evaluate_user_notifications(self.db, self.user, now_dt=now)
        self.db.commit()

        habit_notifs = self.db.query(Notification).filter(
            Notification.user_id == self.user.id,
            Notification.type == "habit_alert"
        ).all()
        self.assertGreaterEqual(len(habit_notifs), 1)
        self.assertIn("snooze", habit_notifs[0].message.lower())

    def test_06_progress_streak_milestone(self):
        """Test progress notification when user hits streak milestones."""
        alarm = Alarm(
            user_id=self.user.id,
            title="Morning Rise",
            alarm_time="07:00",
            alarm_type="Daily",
            challenge="Math Problems",
            difficulty_level="Medium",
            is_active=True
        )
        self.db.add(alarm)
        self.db.commit()

        now = datetime.now(timezone.utc)
        for i in range(3):
            attempt = ChallengeAttempt(
                user_id=self.user.id,
                alarm_id=alarm.id,
                challenge_type="Math Problems",
                difficulty="Medium",
                question="What is 7 * 8?",
                correct_answer="56",
                user_answer="56",
                is_correct=True,
                created_at=now - timedelta(days=i)
            )
            self.db.add(attempt)
        self.db.commit()

        evaluate_user_notifications(self.db, self.user, now_dt=now)
        self.db.commit()

        progress_notifs = self.db.query(Notification).filter(
            Notification.user_id == self.user.id,
            Notification.type == "progress"
        ).all()
        self.assertGreaterEqual(len(progress_notifs), 1)

    def test_07_admin_announcements_crud_and_broadcast(self):
        """Test creating, publishing, broadcasting, and updating admin announcements."""
        create_payload = {
            "title": "Scheduled Server Upgrade",
            "message": "Routine database maintenance tonight at 02:00 UTC.",
            "priority": "high",
            "is_active": True
        }
        resp = self.client.post("/api/admin/announcements", json=create_payload, headers=self.admin_headers)
        self.assertEqual(resp.status_code, 201)
        announcement_data = resp.json()
        self.assertEqual(announcement_data["title"], "Scheduled Server Upgrade")
        announcement_id = announcement_data["id"]

        # Broadcast to users
        broadcast_announcements_to_users(self.db)
        self.db.commit()

        user_notifs = self.db.query(Notification).filter(
            Notification.user_id == self.user.id,
            Notification.type == "platform_announcement"
        ).all()
        self.assertGreaterEqual(len(user_notifs), 1)
        self.assertIn("Scheduled Server Upgrade", user_notifs[0].title)
        self.assertEqual(user_notifs[0].priority, "high")

        # Toggle announcement status
        resp = self.client.patch(f"/api/admin/announcements/{announcement_id}/status?is_active=false", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["is_active"])

    def test_08_notification_unread_count_read_and_clear_apis(self):
        """Test user notification interaction endpoints."""
        n1 = Notification(
            user_id=self.user.id,
            type="bedtime",
            title="Wind down reminder",
            message="Time to sleep",
            priority="normal",
            is_read=False
        )
        n2 = Notification(
            user_id=self.user.id,
            type="wake_up",
            title="Alarm reminder",
            message="Alarm will ring soon",
            priority="normal",
            is_read=False
        )
        self.db.add_all([n1, n2])
        self.db.commit()
        self.db.refresh(n1)
        self.db.refresh(n2)

        # 1. Check unread count
        resp = self.client.get("/api/notifications/unread-count", headers=self.user_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["unread_count"], 2)

        # 2. Mark single notification as read
        resp = self.client.patch(f"/api/notifications/{n1.id}/read", headers=self.user_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["is_read"])

        # 3. Mark all read
        resp = self.client.patch("/api/notifications/read-all", headers=self.user_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "success")

        # 4. Clear all read notifications
        resp = self.client.delete("/api/notifications/clear-all", headers=self.user_headers)
        self.assertEqual(resp.status_code, 200)

        # 5. Check list is empty
        resp = self.client.get("/api/notifications/", headers=self.user_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["notifications"]), 0)

    def test_09_delivery_service_and_phone_validation(self):
        """Test phone number validation helper and delivery service edge cases."""
        # Valid phone numbers
        is_valid, cleaned = validate_phone_number("+1 (415) 555-2671")
        self.assertTrue(is_valid)
        self.assertEqual(cleaned, "+14155552671")

        is_valid, cleaned = validate_phone_number("9876543210")
        self.assertTrue(is_valid)
        self.assertEqual(cleaned, "9876543210")

        # Invalid phone numbers
        is_valid, _ = validate_phone_number("123")
        self.assertFalse(is_valid)

        is_valid, _ = validate_phone_number("abc-def-ghij")
        self.assertFalse(is_valid)

        # Phone number empty or None
        is_valid, _ = validate_phone_number(None)
        self.assertFalse(is_valid)

        # Test SMS send when user has no phone
        res = send_sms_notification(None, "Test SMS")
        self.assertEqual(res["status"], "no_phone")

        # Test provider status endpoint
        resp = self.client.get("/api/notifications/providers", headers=self.user_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("email", data)
        self.assertIn("sms", data)
        self.assertIn("configured", data["email"])
        self.assertIn("configured", data["sms"])

    def test_10_multi_channel_phone_update_and_matrix_sync(self):
        """Test updating preferences with phone number and matrix settings."""
        # 1. Update preferences with new phone number
        update_payload = {
            "preferred_channel": "sms",
            "phone_number": "+12025550199",
            "bedtime_sms": True,
            "wakeup_sms": True,
            "habit_sms": True,
            "challenge_sms": True,
            "progress_sms": True,
            "announcement_sms": True
        }
        resp = self.client.put("/api/notifications/preferences", json=update_payload, headers=self.user_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["preferred_channel"], "sms")
        self.assertTrue(data["bedtime_sms"])

        # Check that user phone number was persisted
        self.db.refresh(self.user)
        self.assertEqual(self.user.phone_number, "+12025550199")

        # 2. Reject invalid phone number
        bad_payload = {
            "phone_number": "not_a_phone"
        }
        bad_resp = self.client.put("/api/notifications/preferences", json=bad_payload, headers=self.user_headers)
        self.assertEqual(bad_resp.status_code, 400)
        self.assertIn("Invalid phone number", bad_resp.json()["detail"])

    def test_11_notification_history_retrieval_and_filtering(self):
        """Test retrieving notification history with channel and status query filters."""
        # Create test notifications with different channels and statuses
        n_email = Notification(
            user_id=self.user.id,
            type="bedtime",
            title="Bedtime Alert",
            message="Time to wind down",
            delivery_channel="email",
            delivery_status="delivered",
            email_status="delivered",
            created_at=datetime.now(timezone.utc)
        )
        n_sms = Notification(
            user_id=self.user.id,
            type="wake_up",
            title="Wakeup Alert",
            message="Your 07:00 alarm is ringing",
            delivery_channel="sms",
            delivery_status="unconfigured",
            sms_status="unconfigured",
            created_at=datetime.now(timezone.utc)
        )
        n_both = Notification(
            user_id=self.user.id,
            type="progress",
            title="Streak Reached",
            message="3-Day Streak!",
            delivery_channel="both",
            delivery_status="delivered",
            email_status="delivered",
            sms_status="delivered",
            created_at=datetime.now(timezone.utc)
        )
        self.db.add_all([n_email, n_sms, n_both])
        self.db.commit()

        # 1. Query all history
        resp = self.client.get("/api/notifications/history", headers=self.user_headers)
        self.assertEqual(resp.status_code, 200)
        history = resp.json()["history"]
        self.assertEqual(len(history), 3)

        # 2. Filter by channel=sms
        resp_sms = self.client.get("/api/notifications/history?channel=sms", headers=self.user_headers)
        self.assertEqual(resp_sms.status_code, 200)
        sms_items = resp_sms.json()["history"]
        self.assertGreaterEqual(len(sms_items), 1)
        for item in sms_items:
            self.assertIn(item["delivery_channel"], ["sms", "both"])

        # 3. Filter by status=unconfigured
        resp_unconf = self.client.get("/api/notifications/history?status=unconfigured", headers=self.user_headers)
        self.assertEqual(resp_unconf.status_code, 200)
        unconf_items = resp_unconf.json()["history"]
        self.assertEqual(len(unconf_items), 1)
        self.assertEqual(unconf_items[0]["delivery_status"], "unconfigured")

    def test_12_scheduled_report_delivery(self):
        """Test scheduling automated behavioral & cognitive report delivery."""
        # 1. Schedule report for user with phone
        payload = {
            "report_type": "summary",
            "frequency": "weekly",
            "delivery_channel": "both"
        }
        resp = self.client.post("/api/notifications/reports/schedule", json=payload, headers=self.user_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["delivery_channel"], "both")
        self.assertEqual(data["frequency"], "weekly")

        # Verify preference was saved in DB
        prefs = get_or_create_user_preferences(self.db, self.user.id)
        self.assertTrue(prefs.report_delivery_enabled)
        self.assertEqual(prefs.report_delivery_channel, "both")
        self.assertEqual(prefs.report_delivery_frequency, "weekly")

        # Verify audit notification was logged
        report_notif = self.db.query(Notification).filter(
            Notification.user_id == self.user.id,
            Notification.type == "report_delivery"
        ).order_by(Notification.id.desc()).first()
        self.assertIsNotNone(report_notif)
        self.assertIn("Report Ready", report_notif.title)

        # 2. Schedule SMS report for user WITHOUT phone -> Should return 400
        sms_payload = {
            "report_type": "detailed",
            "frequency": "monthly",
            "delivery_channel": "sms"
        }
        resp_err = self.client.post("/api/notifications/reports/schedule", json=sms_payload, headers=self.user_no_phone_headers)
        self.assertEqual(resp_err.status_code, 400)
        self.assertIn("phone number", resp_err.json()["detail"].lower())

    def test_13_user_profile_phone_update_api(self):
        """Test updating user phone number via PUT /api/auth/profile."""
        profile_update = {
            "name": "Alice Updated",
            "phone_number": "+18005550123",
            "target_bedtime": "22:30",
            "target_wake_time": "06:30"
        }
        resp = self.client.put("/api/auth/profile", json=profile_update, headers=self.user_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["phone_number"], "+18005550123")
        self.assertEqual(data["target_bedtime"], "22:30")

        # Verify in GET /api/auth/me
        me_resp = self.client.get("/api/auth/me", headers=self.user_headers)
        self.assertEqual(me_resp.status_code, 200)
        self.assertEqual(me_resp.json()["phone_number"], "+18005550123")


if __name__ == "__main__":
    unittest.main()
