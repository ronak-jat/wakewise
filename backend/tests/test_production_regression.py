import os
import sys
import unittest
from unittest.mock import patch
import socket
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from database import get_db, Base
from models import (
    User, Alarm, ChallengeAttempt, AlarmSnoozeEvent,
    Notification, PlatformAnnouncement, UserNotificationPreference, CoachUserAssignment
)
from main import app
from security import hash_password, verify_password, create_access_token
from services.notification_service import (
    evaluate_user_notifications,
    broadcast_announcements_to_users,
    get_or_create_user_preferences
)
from services.delivery_service import send_email_notification, send_sms_notification

# In-memory SQLite for isolated regression testing
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


class TestProductionRegression(unittest.TestCase):
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

        # 1. Registered standard user with existing bcrypt password
        self.raw_password = "SecurePassword123!"
        self.hashed_pwd = hash_password(self.raw_password)
        self.user = User(
            name="Alice Normal",
            email="alice@test.com",
            password=self.hashed_pwd,
            phone_number="+14155550199",
            role="USER",
            provider="LOCAL",
            target_bedtime="23:00",
            target_wake_time="07:00"
        )
        self.db.add(self.user)

        # 2. Registered Admin user
        self.admin = User(
            name="Admin User",
            email="admin@test.com",
            password=hash_password("AdminSecret123!"),
            role="ADMIN",
            provider="LOCAL"
        )
        self.db.add(self.admin)

        # 3. Registered Coach user
        self.coach = User(
            name="Coach Taylor",
            email="coach@test.com",
            password=hash_password("CoachSecret123!"),
            role="COACH",
            provider="LOCAL"
        )
        self.db.add(self.coach)

        self.db.commit()
        self.db.refresh(self.user)
        self.db.refresh(self.admin)
        self.db.refresh(self.coach)

        self.user_token = create_access_token(data={"sub": self.user.email, "role": self.user.role, "id": self.user.id})
        self.user_headers = {
            "Authorization": f"Bearer {self.user_token}",
            "Origin": "https://wakewise-nine.vercel.app"
        }

        self.admin_token = create_access_token(data={"sub": self.admin.email, "role": self.admin.role, "id": self.admin.id})
        self.admin_headers = {
            "Authorization": f"Bearer {self.admin_token}",
            "Origin": "https://wakewise-nine.vercel.app"
        }

    def tearDown(self):
        self.db.close()

    def test_01_valid_login_succeeds_and_verifies_bcrypt_hash(self):
        """Valid credentials authenticate against existing bcrypt hash and return JWT."""
        self.assertTrue(verify_password(self.raw_password, self.user.password))
        
        resp = self.client.post("/api/auth/login", json={
            "email": "alice@test.com",
            "password": self.raw_password
        }, headers={"Origin": "https://wakewise-nine.vercel.app"})
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["token_type"], "bearer")
        self.assertEqual(data["user"]["email"], "alice@test.com")
        self.assertEqual(data["user"]["role"], "USER")

    def test_02_invalid_login_fails_safely(self):
        """Invalid password returns 401 Unauthorized safely without leaking secrets."""
        resp = self.client.post("/api/auth/login", json={
            "email": "alice@test.com",
            "password": "WrongPassword999!"
        }, headers={"Origin": "https://wakewise-nine.vercel.app"})
        
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["detail"], "Incorrect email or password")

    def test_03_jwt_authenticates_current_user(self):
        """Valid JWT token authenticates /api/auth/me."""
        resp = self.client.get("/api/auth/me", headers=self.user_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["email"], "alice@test.com")
        self.assertEqual(resp.json()["id"], self.user.id)

    def test_04_authenticated_dashboard_and_api_requests(self):
        """User and Admin dashboard requests work with valid authentication."""
        user_dash_resp = self.client.get("/api/dashboard/overview", headers=self.user_headers)
        self.assertEqual(user_dash_resp.status_code, 200)
        self.assertEqual(user_dash_resp.json()["user_id"], self.user.id)
        
        admin_dash_resp = self.client.get("/api/admin/dashboard", headers=self.admin_headers)
        self.assertEqual(admin_dash_resp.status_code, 200)
        self.assertEqual(admin_dash_resp.json()["system_health"], "operational")

    def test_05_smtp_network_unreachable_does_not_break_in_app_notifications(self):
        """
        When SMTP throws [Errno 101] Network is unreachable or socket error:
        1. send_email_notification returns failed status safely without raising unhandled exception.
        2. In-app notification IS CREATED and persisted in database.
        3. Delivery status is recorded accurately.
        4. GET /api/notifications/ succeeds with HTTP 200.
        """
        from config import settings
        original_host = settings.SMTP_HOST
        original_user = settings.SMTP_USER
        original_pass = settings.SMTP_PASSWORD

        try:
            settings.SMTP_HOST = "smtp.example.com"
            settings.SMTP_USER = "test@example.com"
            settings.SMTP_PASSWORD = "secretpassword"

            with patch("smtplib.SMTP") as mock_smtp:
                mock_smtp.side_effect = OSError(101, "Network is unreachable")
                
                # Direct send_email_notification test
                res = send_email_notification("alice@test.com", "Test Subject", "Test Message")
                self.assertEqual(res["status"], "failed")
                self.assertIn("Network Error", res["detail"])

                # Evaluate user notifications with unreachable SMTP
                now = datetime.now(timezone.utc).replace(hour=22, minute=45)
                prefs = get_or_create_user_preferences(self.db, self.user.id)
                prefs.bedtime_email = True
                prefs.preferred_channel = "email"
                self.db.commit()

                evaluate_user_notifications(self.db, self.user, now_dt=now)

                # In-app notification MUST exist
                notifs = self.db.query(Notification).filter(
                    Notification.user_id == self.user.id,
                    Notification.type == "bedtime"
                ).all()
                self.assertGreaterEqual(len(notifs), 1)
                self.assertEqual(notifs[0].email_status, "failed")
                self.assertFalse(notifs[0].is_read)

                # API endpoint fetch succeeds
                api_resp = self.client.get("/api/notifications/", headers=self.user_headers)
                self.assertEqual(api_resp.status_code, 200)
                self.assertGreaterEqual(len(api_resp.json()["notifications"]), 1)
        finally:
            settings.SMTP_HOST = original_host
            settings.SMTP_USER = original_user
            settings.SMTP_PASSWORD = original_pass

    def test_06_platform_announcement_broadcast_and_orm_stale_instance_isolation(self):
        """
        Tests that creating an announcement and broadcasting across multiple users:
        1. Does not crash with ObjectDeletedError ('Instance has been deleted or row not present').
        2. Creates in-app notifications for targeted users.
        3. Returns valid response from POST /api/admin/announcements.
        """
        ann_payload = {
            "title": "Platform Reliability Update",
            "message": "All notification delivery channels are operating with full resilience.",
            "priority": "high",
            "target_role": "all",
            "is_active": True
        }

        # Create announcement as Admin (which automatically broadcasts)
        resp = self.client.post("/api/admin/announcements", json=ann_payload, headers=self.admin_headers)
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["title"], "Platform Reliability Update")
        self.assertEqual(data["priority"], "high")
        ann_id = data["id"]

        # Target user receives the announcement in notification stream
        user_notifs_resp = self.client.get("/api/notifications/?type=announcement", headers=self.user_headers)
        self.assertEqual(user_notifs_resp.status_code, 200)
        ann_items = user_notifs_resp.json()["notifications"]
        self.assertTrue(any(n["reference_id"] == str(ann_id) for n in ann_items))

    def test_07_repeated_announcement_processing_idempotency(self):
        """
        Broadcasting announcements repeatedly across multiple cycles must NOT duplicate notifications.
        """
        ann = PlatformAnnouncement(
            title="Idempotency Test Announcement",
            message="This should only appear once per user.",
            priority="normal",
            target_role="all",
            is_active=True,
            created_by=self.admin.id
        )
        self.db.add(ann)
        self.db.commit()
        self.db.refresh(ann)

        # Broadcast cycle 1
        broadcast_announcements_to_users(self.db)
        count_1 = self.db.query(Notification).filter(
            Notification.user_id == self.user.id,
            Notification.reference_type == "announcement",
            Notification.reference_id == str(ann.id)
        ).count()
        self.assertEqual(count_1, 1)

        # Broadcast cycle 2 (simulating repeated scheduler runs)
        broadcast_announcements_to_users(self.db)
        count_2 = self.db.query(Notification).filter(
            Notification.user_id == self.user.id,
            Notification.reference_type == "announcement",
            Notification.reference_id == str(ann.id)
        ).count()
        self.assertEqual(count_2, 1)

    def test_08_cors_headers_on_authenticated_and_options_requests(self):
        """Verifies CORS headers for Vercel production frontend origin on all key endpoints."""
        # 1. OPTIONS preflight
        opt_resp = self.client.options(
            "/api/admin/announcements",
            headers={
                "Origin": "https://wakewise-nine.vercel.app",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type"
            }
        )
        self.assertEqual(opt_resp.status_code, 200)
        self.assertEqual(opt_resp.headers.get("access-control-allow-origin"), "https://wakewise-nine.vercel.app")
        self.assertEqual(opt_resp.headers.get("access-control-allow-credentials"), "true")

        # 2. Authenticated GET /api/notifications/
        notif_resp = self.client.get("/api/notifications/", headers=self.user_headers)
        self.assertEqual(notif_resp.status_code, 200)
        self.assertEqual(notif_resp.headers.get("access-control-allow-origin"), "https://wakewise-nine.vercel.app")

        # 3. Authenticated POST /api/admin/announcements
        post_resp = self.client.post(
            "/api/admin/announcements",
            json={"title": "CORS Check", "message": "Test message", "priority": "normal", "is_active": True},
            headers=self.admin_headers
        )
        self.assertEqual(post_resp.status_code, 201)
        self.assertEqual(post_resp.headers.get("access-control-allow-origin"), "https://wakewise-nine.vercel.app")


if __name__ == "__main__":
    unittest.main()
