import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

# Ensure backend directory in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db, run_db_migrations
from main import app
from models import (
    User,
    Alarm,
    ChallengeAttempt,
    AlarmSnoozeEvent,
    Notification,
    CoachUserAssignment,
)
from security import hash_password, create_access_token


class TestCoachUserAssignments(unittest.TestCase):
    """
    Complete unit & integration tests for Admin -> Coach -> User Assignment System.
    Validates boundary isolation, server-side authorization enforcement,
    and API tampering protection.
    """

    @classmethod
    def setUpClass(cls):
        # Use an in-memory SQLite database for test isolation
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.TestingSessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=cls.engine
        )

        Base.metadata.create_all(bind=cls.engine)

        def override_get_db():
            db = cls.TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=cls.engine)
        app.dependency_overrides.clear()

    def setUp(self):
        self.db = self.TestingSessionLocal()

        # Clear existing tables for test hygiene
        self.db.query(Notification).delete()
        self.db.query(CoachUserAssignment).delete()
        self.db.query(ChallengeAttempt).delete()
        self.db.query(AlarmSnoozeEvent).delete()
        self.db.query(Alarm).delete()
        self.db.query(User).delete()
        self.db.commit()

        # Create Admin
        self.admin = User(
            name="Platform Admin",
            email="admin@test.com",
            password=hash_password("AdminPass123"),
            role="ADMIN"
        )
        # Create Coach A
        self.coach_a = User(
            name="Coach Alice",
            email="coach_a@test.com",
            password=hash_password("CoachPass123"),
            role="COACH"
        )
        # Create Coach B
        self.coach_b = User(
            name="Coach Bob",
            email="coach_b@test.com",
            password=hash_password("CoachPass123"),
            role="COACH"
        )
        # Create Normal User 1
        self.user_1 = User(
            name="User One",
            email="user1@test.com",
            password=hash_password("UserPass123"),
            role="USER",
            target_bedtime="23:00",
            target_wake_time="07:00"
        )
        # Create Normal User 2
        self.user_2 = User(
            name="User Two",
            email="user2@test.com",
            password=hash_password("UserPass123"),
            role="USER",
            target_bedtime="22:30",
            target_wake_time="06:30"
        )
        # Create Normal User 3 (Unassigned)
        self.user_3 = User(
            name="User Three",
            email="user3@test.com",
            password=hash_password("UserPass123"),
            role="USER",
            target_bedtime="00:00",
            target_wake_time="08:00"
        )

        self.db.add_all([self.admin, self.coach_a, self.coach_b, self.user_1, self.user_2, self.user_3])
        self.db.commit()

        for u in [self.admin, self.coach_a, self.coach_b, self.user_1, self.user_2, self.user_3]:
            self.db.refresh(u)

        # Create alarms & challenge data for User 1
        self.alarm_1 = Alarm(
            user_id=self.user_1.id,
            title="Morning Routine",
            alarm_time="07:00",
            is_active=True
        )
        self.db.add(self.alarm_1)
        self.db.commit()
        self.db.refresh(self.alarm_1)

        self.attempt_1 = ChallengeAttempt(
            user_id=self.user_1.id,
            alarm_id=self.alarm_1.id,
            challenge_type="Math Problems",
            difficulty="Medium",
            question="12 + 15",
            correct_answer="27",
            user_answer="27",
            is_correct=True,
            time_taken=8,
            verification_status="passed"
        )
        self.db.add(self.attempt_1)
        self.db.commit()

        # Auth headers
        self.admin_token = create_access_token({"sub": self.admin.email, "role": self.admin.role})
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}

        self.coach_a_token = create_access_token({"sub": self.coach_a.email, "role": self.coach_a.role})
        self.coach_a_headers = {"Authorization": f"Bearer {self.coach_a_token}"}

        self.coach_b_token = create_access_token({"sub": self.coach_b.email, "role": self.coach_b.role})
        self.coach_b_headers = {"Authorization": f"Bearer {self.coach_b_token}"}

        self.user_1_token = create_access_token({"sub": self.user_1.email, "role": self.user_1.role})
        self.user_1_headers = {"Authorization": f"Bearer {self.user_1_token}"}

    def tearDown(self):
        self.db.close()

    def test_01_admin_assign_and_unassign_user(self):
        """Test Admin assigning User 1 to Coach A and unassigning."""
        # 1. Admin assigns User 1 to Coach A
        assign_resp = self.client.post(
            "/api/admin/coach-assignments/assign",
            json={"coach_id": self.coach_a.id, "user_ids": [self.user_1.id]},
            headers=self.admin_headers
        )
        self.assertEqual(assign_resp.status_code, 200)
        self.assertEqual(assign_resp.json()["assigned_count"], 1)

        # Verify DB active assignment
        assignment = (
            self.db.query(CoachUserAssignment)
            .filter(
                CoachUserAssignment.coach_id == self.coach_a.id,
                CoachUserAssignment.user_id == self.user_1.id,
                CoachUserAssignment.is_active == True
            )
            .first()
        )
        self.assertIsNotNone(assignment)
        self.assertEqual(assignment.assigned_by, self.admin.id)

        # 2. Admin unassigns User 1 from Coach A
        unassign_resp = self.client.post(
            "/api/admin/coach-assignments/unassign",
            json={"coach_id": self.coach_a.id, "user_ids": [self.user_1.id]},
            headers=self.admin_headers
        )
        self.assertEqual(unassign_resp.status_code, 200)

        # Verify DB is now inactive
        self.db.expire_all()
        active_assignment = (
            self.db.query(CoachUserAssignment)
            .filter(
                CoachUserAssignment.coach_id == self.coach_a.id,
                CoachUserAssignment.user_id == self.user_1.id,
                CoachUserAssignment.is_active == True
            )
            .first()
        )
        self.assertIsNone(active_assignment)

    def test_02_coach_sees_only_assigned_users(self):
        """Test that GET /api/coach/users returns strictly the assigned patients."""
        # Assign User 1 to Coach A and User 2 to Coach B
        self.client.post(
            "/api/admin/coach-assignments/assign",
            json={"coach_id": self.coach_a.id, "user_ids": [self.user_1.id]},
            headers=self.admin_headers
        )
        self.client.post(
            "/api/admin/coach-assignments/assign",
            json={"coach_id": self.coach_b.id, "user_ids": [self.user_2.id]},
            headers=self.admin_headers
        )

        # Coach A views their roster
        resp_a = self.client.get("/api/coach/users", headers=self.coach_a_headers)
        self.assertEqual(resp_a.status_code, 200)
        users_a = resp_a.json()
        self.assertEqual(len(users_a), 1)
        self.assertEqual(users_a[0]["id"], self.user_1.id)
        self.assertEqual(users_a[0]["email"], self.user_1.email)

        # Coach B views their roster
        resp_b = self.client.get("/api/coach/users", headers=self.coach_b_headers)
        self.assertEqual(resp_b.status_code, 200)
        users_b = resp_b.json()
        self.assertEqual(len(users_b), 1)
        self.assertEqual(users_b[0]["id"], self.user_2.id)

    def test_03_coach_cannot_access_unassigned_user_history(self):
        """Test Coach A cannot access unassigned User 2's history (HTTP 403)."""
        # Assign only User 1 to Coach A
        self.client.post(
            "/api/admin/coach-assignments/assign",
            json={"coach_id": self.coach_a.id, "user_ids": [self.user_1.id]},
            headers=self.admin_headers
        )

        # Coach A tries to access User 2 (unassigned) -> HTTP 403 Forbidden
        resp = self.client.get(f"/api/coach/users/{self.user_2.id}/history", headers=self.coach_a_headers)
        self.assertEqual(resp.status_code, 403)
        self.assertIn("not assigned", resp.json()["detail"].lower())

        # Coach A tries to access User 2 analytics -> HTTP 403 Forbidden
        resp_analytics = self.client.get(f"/api/coach/users/{self.user_2.id}/analytics", headers=self.coach_a_headers)
        self.assertEqual(resp_analytics.status_code, 403)

    def test_04_coach_cannot_access_another_coachs_user(self):
        """Test Coach B cannot access Coach A's assigned user (User 1)."""
        # User 1 assigned to Coach A, User 2 assigned to Coach B
        self.client.post(
            "/api/admin/coach-assignments/assign",
            json={"coach_id": self.coach_a.id, "user_ids": [self.user_1.id]},
            headers=self.admin_headers
        )
        self.client.post(
            "/api/admin/coach-assignments/assign",
            json={"coach_id": self.coach_b.id, "user_ids": [self.user_2.id]},
            headers=self.admin_headers
        )

        # Coach B tries to fetch User 1 -> 403
        resp = self.client.get(f"/api/coach/users/{self.user_1.id}/history", headers=self.coach_b_headers)
        self.assertEqual(resp.status_code, 403)

    def test_05_assigned_user_history_and_analytics_accessible(self):
        """Test Coach A can retrieve history and analytics for assigned User 1."""
        self.client.post(
            "/api/admin/coach-assignments/assign",
            json={"coach_id": self.coach_a.id, "user_ids": [self.user_1.id]},
            headers=self.admin_headers
        )

        resp_hist = self.client.get(f"/api/coach/users/{self.user_1.id}/history", headers=self.coach_a_headers)
        self.assertEqual(resp_hist.status_code, 200)
        data = resp_hist.json()
        self.assertEqual(data["user_id"], self.user_1.id)
        self.assertEqual(data["total_alarms"], 1)
        self.assertEqual(len(data["recent_challenge_attempts"]), 1)

        resp_ana = self.client.get(f"/api/coach/users/{self.user_1.id}/analytics?period_days=7", headers=self.coach_a_headers)
        self.assertEqual(resp_ana.status_code, 200)
        ana_data = resp_ana.json()
        self.assertEqual(ana_data["user_id"], self.user_1.id)
        self.assertIn("habit_score", ana_data)

    def test_06_coach_notification_to_assigned_vs_unassigned_user(self):
        """Test Coach can notify assigned user but is blocked (403) when trying to notify unassigned user."""
        self.client.post(
            "/api/admin/coach-assignments/assign",
            json={"coach_id": self.coach_a.id, "user_ids": [self.user_1.id]},
            headers=self.admin_headers
        )

        # 1. Coach A sends notification to assigned User 1 -> 201 Created
        notif_payload_assigned = {
            "user_id": self.user_1.id,
            "title": "Sleep Schedule Tip",
            "message": "Try to turn off screens 30 minutes before 11 PM.",
            "priority": "normal"
        }
        res_ok = self.client.post("/api/notifications/coach", json=notif_payload_assigned, headers=self.coach_a_headers)
        self.assertEqual(res_ok.status_code, 201)
        self.assertEqual(res_ok.json()["user_id"], self.user_1.id)

        # 2. Coach A tries to send notification to unassigned User 2 -> 403 Forbidden
        notif_payload_unassigned = {
            "user_id": self.user_2.id,
            "title": "Unsolicited Advice",
            "message": "You are not assigned to me.",
            "priority": "high"
        }
        res_denied = self.client.post("/api/notifications/coach", json=notif_payload_unassigned, headers=self.coach_a_headers)
        self.assertEqual(res_denied.status_code, 403)
        self.assertIn("not assigned", res_denied.json()["detail"].lower())

    def test_07_admin_cockpit_overview_and_permissions(self):
        """Test Admin overview API and verify standard users are denied (403)."""
        # Assign User 1 to Coach A
        self.client.post(
            "/api/admin/coach-assignments/assign",
            json={"coach_id": self.coach_a.id, "user_ids": [self.user_1.id]},
            headers=self.admin_headers
        )

        # 1. Admin retrieves overview -> 200 OK
        resp = self.client.get("/api/admin/coach-assignments", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_coaches"], 2)
        self.assertEqual(data["total_assigned_users"], 1)
        self.assertEqual(data["total_unassigned_users"], 2)

        # 2. Normal user tries to access admin assignments -> 403 Forbidden
        user_resp = self.client.get("/api/admin/coach-assignments", headers=self.user_1_headers)
        self.assertEqual(user_resp.status_code, 403)

        user_assign = self.client.post(
            "/api/admin/coach-assignments/assign",
            json={"coach_id": self.coach_a.id, "user_ids": [self.user_2.id]},
            headers=self.user_1_headers
        )
        self.assertEqual(user_assign.status_code, 403)

    def test_08_duplicate_assignment_prevention(self):
        """Test assigning the same user multiple times does not create duplicate active rows."""
        # First assignment
        res1 = self.client.post(
            "/api/admin/coach-assignments/assign",
            json={"coach_id": self.coach_a.id, "user_ids": [self.user_1.id]},
            headers=self.admin_headers
        )
        self.assertEqual(res1.status_code, 200)

        # Duplicate assignment attempt
        res2 = self.client.post(
            "/api/admin/coach-assignments/assign",
            json={"coach_id": self.coach_a.id, "user_ids": [self.user_1.id]},
            headers=self.admin_headers
        )
        self.assertEqual(res2.status_code, 200)

        # Count active assignments for Coach A -> User 1
        active_count = (
            self.db.query(CoachUserAssignment)
            .filter(
                CoachUserAssignment.coach_id == self.coach_a.id,
                CoachUserAssignment.user_id == self.user_1.id,
                CoachUserAssignment.is_active == True
            )
            .count()
        )
        self.assertEqual(active_count, 1)

    def test_09_user_reassignment_between_coaches(self):
        """Test reassigning a user from Coach A to Coach B deactivates Coach A's active assignment."""
        # 1. Assign User 1 to Coach A
        self.client.post(
            "/api/admin/coach-assignments/assign",
            json={"coach_id": self.coach_a.id, "user_ids": [self.user_1.id]},
            headers=self.admin_headers
        )

        # 2. Reassign User 1 to Coach B
        self.client.post(
            "/api/admin/coach-assignments/assign",
            json={"coach_id": self.coach_b.id, "user_ids": [self.user_1.id]},
            headers=self.admin_headers
        )

        self.db.expire_all()

        # Coach A's assignment should now be inactive
        assign_a = (
            self.db.query(CoachUserAssignment)
            .filter(
                CoachUserAssignment.coach_id == self.coach_a.id,
                CoachUserAssignment.user_id == self.user_1.id
            )
            .first()
        )
        self.assertFalse(assign_a.is_active)

        # Coach B's assignment should now be active
        assign_b = (
            self.db.query(CoachUserAssignment)
            .filter(
                CoachUserAssignment.coach_id == self.coach_b.id,
                CoachUserAssignment.user_id == self.user_1.id
            )
            .first()
        )
        self.assertTrue(assign_b.is_active)

        # Coach A can no longer access User 1 -> 403
        res_a = self.client.get(f"/api/coach/users/{self.user_1.id}/history", headers=self.coach_a_headers)
        self.assertEqual(res_a.status_code, 403)

        # Coach B CAN now access User 1 -> 200
        res_b = self.client.get(f"/api/coach/users/{self.user_1.id}/history", headers=self.coach_b_headers)
        self.assertEqual(res_b.status_code, 200)

    def test_10_api_parameter_tampering_protection_in_analytics(self):
        """Test that manually passing user_id in query parameters returns 403 if unassigned."""
        # Assign User 1 to Coach A
        self.client.post(
            "/api/admin/coach-assignments/assign",
            json={"coach_id": self.coach_a.id, "user_ids": [self.user_1.id]},
            headers=self.admin_headers
        )

        # Coach A tampers with user_id parameter in /api/dashboard/habit-analytics?user_id=2 (User 2 is unassigned)
        res_habit = self.client.get(
            f"/api/dashboard/habit-analytics?user_id={self.user_2.id}",
            headers=self.coach_a_headers
        )
        self.assertEqual(res_habit.status_code, 403)

        # Coach A tampers with user_id in /api/dashboard/challenge-performance?user_id=2
        res_chal = self.client.get(
            f"/api/dashboard/challenge-performance?user_id={self.user_2.id}",
            headers=self.coach_a_headers
        )
        self.assertEqual(res_chal.status_code, 403)

        # Valid assigned User 1 succeeds
        res_valid = self.client.get(
            f"/api/dashboard/habit-analytics?user_id={self.user_1.id}",
            headers=self.coach_a_headers
        )
        self.assertEqual(res_valid.status_code, 200)


if __name__ == "__main__":
    unittest.main()
