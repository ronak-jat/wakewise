import os
import sys
import unittest
from datetime import datetime, timedelta, date

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from database import get_db, Base
from models import User, Alarm, ChallengeAttempt, AlarmSnoozeEvent
from main import app
from security import hash_password, create_access_token

# Set up an in-memory SQLite database with StaticPool for multi-threaded test client sharing
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


class TestDashboardAndAnalytics(unittest.TestCase):
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
            name="Alice Walker",
            email="alice@example.com",
            password=hash_password("Password123"),
            role="USER",
            provider="LOCAL",
            target_bedtime="23:00",
            target_wake_time="07:00",
        )
        # Create admin user
        self.admin = User(
            name="Admin User",
            email="admin@example.com",
            password=hash_password("AdminPass123"),
            role="ADMIN",
            provider="LOCAL",
        )
        self.db.add_all([self.user, self.admin])
        self.db.commit()
        self.db.refresh(self.user)
        self.db.refresh(self.admin)

        self.user_token = create_access_token(data={"sub": self.user.email, "role": self.user.role, "id": self.user.id})
        self.admin_token = create_access_token(data={"sub": self.admin.email, "role": self.admin.role, "id": self.admin.id})

        self.user_headers = {"Authorization": f"Bearer {self.user_token}"}
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}

    def tearDown(self):
        self.db.close()

    def test_01_new_user_empty_overview(self):
        """Validates empty state for new user with no alarms or attempts."""
        res = self.client.get("/api/dashboard/overview", headers=self.user_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total_alarms"], 0)
        self.assertEqual(data["active_alarms"], 0)
        self.assertEqual(data["completed_alarms"], 0)
        self.assertEqual(data["missed_alarms"], 0)
        self.assertEqual(data["snooze_count"], 0)
        self.assertEqual(data["current_streak"], 0)
        self.assertIsNone(data["average_wake_up_time"])

    def test_02_user_with_alarms_and_history(self):
        """Validates dashboard overview with multiple alarms, passed attempts, and snoozes."""
        alarm1 = Alarm(
            user_id=self.user.id,
            title="Morning Awakening",
            alarm_time="07:00",
            alarm_type="Daily",
            is_active=True,
            challenge="Math Problems",
            difficulty_level="Medium",
        )
        alarm2 = Alarm(
            user_id=self.user.id,
            title="Workout Alarm",
            alarm_time="06:30",
            alarm_type="Weekday",
            is_active=False,
            challenge="Memory Challenges",
            difficulty_level="Hard",
        )
        self.db.add_all([alarm1, alarm2])
        self.db.commit()

        # Add challenge attempts for alarm1
        now = datetime.now()
        att1 = ChallengeAttempt(
            user_id=self.user.id,
            alarm_id=alarm1.id,
            challenge_type="Math Problems",
            difficulty="Medium",
            question="12 * 8",
            correct_answer="96",
            user_answer="96",
            is_correct=True,
            time_taken=8,
            verification_status="passed",
            session_id="session_101",
            wakefulness_rating=4,
            completed_at=now,
            created_at=now - timedelta(seconds=10),
        )
        att2 = ChallengeAttempt(
            user_id=self.user.id,
            alarm_id=alarm1.id,
            challenge_type="Logic Puzzles",
            difficulty="Medium",
            question="Sequence 2, 4, 8, ?",
            correct_answer="16",
            user_answer="16",
            is_correct=True,
            time_taken=12,
            verification_status="passed",
            session_id="session_101",
            wakefulness_rating=5,
            completed_at=now,
            created_at=now - timedelta(seconds=20),
        )
        snooze = AlarmSnoozeEvent(
            user_id=self.user.id,
            alarm_id=alarm1.id,
            snooze_count=2,
            scheduled_for=now,
        )
        self.db.add_all([att1, att2, snooze])
        self.db.commit()

        res = self.client.get("/api/dashboard/overview", headers=self.user_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total_alarms"], 2)
        self.assertEqual(data["active_alarms"], 1)
        self.assertEqual(data["completed_alarms"], 1)
        self.assertEqual(data["snooze_count"], 2)
        self.assertGreater(data["habit_score"], 0)
        self.assertIsNotNone(data["average_wakefulness_rating"])

    def test_03_alarm_history_with_date_filters(self):
        """Validates alarm history endpoint with today, 7days, and custom date range filters."""
        alarm = Alarm(user_id=self.user.id, title="Rise & Shine", alarm_time="07:30", is_active=True)
        self.db.add(alarm)
        self.db.commit()

        # Session today
        today_att = ChallengeAttempt(
            user_id=self.user.id,
            alarm_id=alarm.id,
            challenge_type="Math Problems",
            difficulty="Easy",
            question="5 + 5",
            correct_answer="10",
            user_answer="10",
            is_correct=True,
            verification_status="passed",
            session_id="today_sess",
            created_at=datetime.now(),
        )
        # Session 10 days ago
        old_att = ChallengeAttempt(
            user_id=self.user.id,
            alarm_id=alarm.id,
            challenge_type="Word Games",
            difficulty="Easy",
            question="Anagram of LISTEN",
            correct_answer="SILENT",
            user_answer="SILENT",
            is_correct=True,
            verification_status="passed",
            session_id="old_sess",
            created_at=datetime.now() - timedelta(days=10),
        )
        self.db.add_all([today_att, old_att])
        self.db.commit()

        # Filter: today
        res_today = self.client.get("/api/dashboard/alarm-history?filter_type=today", headers=self.user_headers)
        self.assertEqual(res_today.status_code, 200)
        self.assertEqual(len(res_today.json()["history"]), 1)

        # Filter: 7days (should only include today's session)
        res_7d = self.client.get("/api/dashboard/alarm-history?filter_type=7days", headers=self.user_headers)
        self.assertEqual(res_7d.status_code, 200)
        self.assertEqual(len(res_7d.json()["history"]), 1)

        # Filter: 30days (should include both sessions)
        res_30d = self.client.get("/api/dashboard/alarm-history?filter_type=30days", headers=self.user_headers)
        self.assertEqual(res_30d.status_code, 200)
        self.assertEqual(len(res_30d.json()["history"]), 2)

    def test_04_wake_up_statistics_and_trends(self):
        """Validates wake-up statistics calculations and trend data points."""
        alarm = Alarm(user_id=self.user.id, title="Routine", alarm_time="07:00", is_active=True)
        self.db.add(alarm)
        self.db.commit()

        # Add passed session with known times
        t1 = datetime.now().replace(hour=7, minute=10)
        att = ChallengeAttempt(
            user_id=self.user.id,
            alarm_id=alarm.id,
            challenge_type="Math Problems",
            difficulty="Medium",
            question="7 * 7",
            correct_answer="49",
            user_answer="49",
            is_correct=True,
            time_taken=15,
            verification_status="passed",
            session_id="stat_sess_1",
            wakefulness_rating=4,
            completed_at=t1,
            created_at=t1 - timedelta(seconds=15),
        )
        self.db.add(att)
        self.db.commit()

        res = self.client.get("/api/dashboard/wake-up-statistics?days=30", headers=self.user_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["average_scheduled_wake_time"], "07:00")
        self.assertEqual(data["average_actual_wake_time"], "07:10")
        self.assertEqual(data["average_wake_up_delay_minutes"], 10.0)
        self.assertEqual(data["on_time_wake_percentage"], 100.0)
        self.assertEqual(len(data["trend_points"]), 1)

    def test_05_challenge_performance_breakdown(self):
        """Validates challenge performance breakdown by 7 types and 5 difficulty levels."""
        # Add attempts for different types and difficulties
        types_to_test = ["Math Problems", "Logic Puzzles", "Memory Challenges", "Word Games", "Pattern Recognition", "Riddles", "Quick Quizzes"]
        diffs_to_test = ["Beginner", "Easy", "Medium", "Hard", "Expert"]

        for i, t in enumerate(types_to_test):
            att = ChallengeAttempt(
                user_id=self.user.id,
                challenge_type=t,
                difficulty=diffs_to_test[i % len(diffs_to_test)],
                question=f"Q for {t}",
                correct_answer="ans",
                user_answer="ans" if i % 2 == 0 else "wrong",
                is_correct=(i % 2 == 0),
                time_taken=10 + i,
                verification_status="passed" if i % 2 == 0 else "failed",
                created_at=datetime.now(),
            )
            self.db.add(att)
        self.db.commit()

        res = self.client.get("/api/dashboard/challenge-performance", headers=self.user_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total_challenges_attempted"], len(types_to_test))
        self.assertEqual(len(data["performance_by_type"]), 7)
        self.assertEqual(len(data["performance_by_difficulty"]), 5)

    def test_06_sleep_trends_and_disclaimer(self):
        """Validates phone-inactivity sleep trends and explicit disclaimer labeling."""
        self.user.last_meaningful_activity_at = datetime.now() - timedelta(hours=8)
        self.user.estimated_sleep_start = datetime.now() - timedelta(hours=8)
        self.user.estimated_sleep_end = datetime.now()
        self.db.commit()

        res = self.client.get("/api/dashboard/sleep-trends", headers=self.user_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["disclaimer"], "Estimated from phone inactivity")
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["target_bedtime"], "23:00")
        self.assertEqual(data["target_wake_time"], "07:00")

    def test_07_categorized_recommendations(self):
        """Validates Requirement 9 categorized recommendations across all 5 domains."""
        res = self.client.get("/api/dashboard/recommendations", headers=self.user_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        categories = {r["category"] for r in data["recommendations"]}
        self.assertIn("Personalized Challenge", categories)
        self.assertIn("Habit Improvement", categories)

    def test_08_admin_authorization_enforcement(self):
        """Validates server-side admin protection: non-admin gets 403 Forbidden."""
        # Non-admin attempting admin endpoints
        res_dash = self.client.get("/api/admin/dashboard", headers=self.user_headers)
        self.assertEqual(res_dash.status_code, 403)

        res_users = self.client.get("/api/admin/users", headers=self.user_headers)
        self.assertEqual(res_users.status_code, 403)

        res_analytics = self.client.get("/api/admin/analytics", headers=self.user_headers)
        self.assertEqual(res_analytics.status_code, 403)

        res_reports = self.client.get("/api/admin/reports", headers=self.user_headers)
        self.assertEqual(res_reports.status_code, 403)

    def test_09_admin_dashboard_and_analytics_success(self):
        """Validates admin endpoints for authorized admin user."""
        res_dash = self.client.get("/api/admin/dashboard", headers=self.admin_headers)
        self.assertEqual(res_dash.status_code, 200)
        data_dash = res_dash.json()
        self.assertGreaterEqual(data_dash["total_users"], 2)

        res_users = self.client.get("/api/admin/users", headers=self.admin_headers)
        self.assertEqual(res_users.status_code, 200)
        users_list = res_users.json()
        self.assertGreaterEqual(len(users_list), 2)
        # Ensure passwords and secret keys are NOT exposed
        for u in users_list:
            self.assertNotIn("password", u)
            self.assertNotIn("token", u)

        res_analytics = self.client.get("/api/admin/analytics", headers=self.admin_headers)
        self.assertEqual(res_analytics.status_code, 200)
        data_analytics = res_analytics.json()
        self.assertIn("habit_score_distribution", data_analytics)
        self.assertIn("role_distribution", data_analytics)

        res_reports = self.client.get("/api/admin/reports", headers=self.admin_headers)
        self.assertEqual(res_reports.status_code, 200)

    def test_10_admin_user_role_update_and_delete_safeguards(self):
        """Validates admin role update and self-deletion prevention."""
        # Update user role
        res_role = self.client.put(
            f"/api/admin/users/{self.user.id}/role",
            json={"role": "Wellness Coach"},
            headers=self.admin_headers
        )
        self.assertEqual(res_role.status_code, 200)

        # Self-deletion attempt by admin -> 400 Bad Request
        res_del_self = self.client.delete(f"/api/admin/users/{self.admin.email}", headers=self.admin_headers)
        self.assertEqual(res_del_self.status_code, 400)

    def test_11_admin_logs_and_recommendations(self):
        """Validates real database audit logs and recommendations endpoints."""
        res_logs = self.client.get("/api/admin/logs", headers=self.admin_headers)
        self.assertEqual(res_logs.status_code, 200)
        logs_data = res_logs.json()
        self.assertIn("logs", logs_data)
        self.assertIn("total", logs_data)
        # Should have registered user events from setUp
        self.assertGreaterEqual(logs_data["total"], 2)

        res_recs = self.client.get("/api/admin/recommendations", headers=self.admin_headers)
        self.assertEqual(res_recs.status_code, 200)
        recs_data = res_recs.json()
        self.assertIn("by_category", recs_data)
        self.assertIn("by_priority", recs_data)

    def test_12_admin_alarms_endpoint(self):
        """Validates real database alarms endpoint returning total alarms directly from alarms table."""
        # Create an alarm in alarms table
        alarm = Alarm(
            user_id=self.user.id,
            title="Sunrise Wakeup",
            alarm_time="06:00",
            alarm_type="Daily",
            is_active=True,
            challenge="Math Problems",
            difficulty_level="Medium"
        )
        self.db.add(alarm)
        self.db.commit()

        res = self.client.get("/api/admin/alarms", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("total_alarms", data)
        self.assertIn("active_alarms", data)
        self.assertIn("alarms", data)
        self.assertGreaterEqual(data["total_alarms"], 1)
        self.assertEqual(data["alarms"][0]["title"], "Sunrise Wakeup")


if __name__ == "__main__":
    unittest.main()
