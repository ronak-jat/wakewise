import os
import sys
import unittest
import datetime

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from database import Base, get_db
from models import User, Alarm, ChallengeAttempt, AlarmSnoozeEvent, Notification, PlatformAnnouncement
from services.metrics_collector import PerformanceMetricsCollector, metrics_collector
from services.performance_metrics_service import calculate_performance_metrics
from security import hash_password, create_access_token
from main import app

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


class TestPerformanceMetrics(unittest.TestCase):
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

    def tearDown(self):
        self.db.close()

    def test_zero_denominator_and_insufficient_data(self):
        """Test metrics calculation with zero data returns clean insufficient_data states without crashing."""
        metrics = calculate_performance_metrics(self.db, period_days=7)

        # 1. Alarm Metrics with zero data
        am = metrics["alarm_metrics"]
        self.assertEqual(am["dismissal_status"], "insufficient_data")
        self.assertIsNone(am["dismissal_success_rate"])
        self.assertEqual(am["total_triggered_alarms"], 0)
        self.assertEqual(am["verification_status"], "insufficient_data")
        self.assertIsNone(am["verification_accuracy"])
        self.assertEqual(am["snooze_reduction_status"], "insufficient_data")
        self.assertIsNone(am["snooze_reduction_rate"])
        self.assertEqual(am["snooze_reduction_display"], "Insufficient data")

        # 2. Challenge Metrics with zero data
        cm = metrics["challenge_metrics"]
        self.assertEqual(cm["completion_status"], "insufficient_data")
        self.assertIsNone(cm["completion_rate"])
        self.assertEqual(cm["accuracy_status"], "insufficient_data")
        self.assertIsNone(cm["overall_accuracy"])
        self.assertEqual(cm["adaptation_effectiveness"]["status"], "insufficient_data")

        # 3. Habit Formation Metrics with zero data
        hm = metrics["habit_metrics"]
        self.assertEqual(hm["habit_score_improvement"]["status"], "insufficient_data")
        self.assertEqual(hm["wake_up_consistency_status"], "insufficient_data")
        self.assertEqual(hm["sleep_schedule_adherence"]["status"], "insufficient_data")
        self.assertIn("Insufficient data", hm["sleep_schedule_adherence"]["message"])
        self.assertTrue(hm["sleep_schedule_adherence"]["estimated_from_phone_inactivity"])

        # 4. Recommendation Metrics with zero data
        rm = metrics["recommendation_metrics"]
        self.assertEqual(rm["relevance"]["status"], "insufficient_data")
        self.assertEqual(rm["relevance"]["display_message"], "Not enough feedback data")
        self.assertIn("correlation", rm["engagement_improvement"]["disclaimer"].lower())
        self.assertEqual(rm["productivity_improvement_rate"]["status"], "insufficient_data")

    def test_alarm_performance_metrics_calculation(self):
        """Test real alarm dismissal rate, verification accuracy, and snooze reduction rate."""
        user = User(
            name="Test User",
            email="test_alarm@example.com",
            password=hash_password("password123"),
            role="USER"
        )
        self.db.add(user)
        self.db.commit()

        alarm = Alarm(
            user_id=user.id,
            title="Morning Alarm",
            alarm_time="07:00",
            is_active=True
        )
        self.db.add(alarm)
        self.db.commit()

        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

        # Add 2 verification sessions:
        # Session 1: 2 attempts, passed
        self.db.add(ChallengeAttempt(
            user_id=user.id,
            alarm_id=alarm.id,
            session_id="sess_1",
            challenge_type="Math Problems",
            difficulty="Medium",
            question="2+2",
            correct_answer="4",
            user_answer="5",
            is_correct=False,
            verification_status="in_progress",
            created_at=now - datetime.timedelta(days=2)
        ))
        self.db.add(ChallengeAttempt(
            user_id=user.id,
            alarm_id=alarm.id,
            session_id="sess_1",
            challenge_type="Math Problems",
            difficulty="Medium",
            question="3+3",
            correct_answer="6",
            user_answer="6",
            is_correct=True,
            verification_status="passed",
            completed_at=now - datetime.timedelta(days=2),
            created_at=now - datetime.timedelta(days=2)
        ))

        # Session 2: 1 attempt, failed
        self.db.add(ChallengeAttempt(
            user_id=user.id,
            alarm_id=alarm.id,
            session_id="sess_2",
            challenge_type="Logic Puzzles",
            difficulty="Easy",
            question="Is sky blue?",
            correct_answer="yes",
            user_answer="no",
            is_correct=False,
            verification_status="failed",
            created_at=now - datetime.timedelta(days=1)
        ))

        # Snooze events: 2 in current period, 4 in previous period
        self.db.add(AlarmSnoozeEvent(user_id=user.id, alarm_id=alarm.id, snooze_count=2, created_at=now - datetime.timedelta(days=2)))
        self.db.add(AlarmSnoozeEvent(user_id=user.id, alarm_id=alarm.id, snooze_count=4, created_at=now - datetime.timedelta(days=10)))
        self.db.commit()

        metrics = calculate_performance_metrics(self.db, period_days=7)
        am = metrics["alarm_metrics"]

        # 1 out of 2 sessions passed -> 50.0% dismissal success rate
        self.assertEqual(am["dismissal_status"], "available")
        self.assertEqual(am["dismissal_success_rate"], 50.0)
        self.assertEqual(am["total_triggered_alarms"], 2)
        self.assertEqual(am["successful_dismissals"], 1)

        # 1 correct out of 3 total answers -> 33.3% accuracy
        self.assertEqual(am["verification_accuracy"], 33.3)
        self.assertEqual(am["total_answers"], 3)
        self.assertEqual(am["correct_answers"], 1)
        self.assertEqual(am["total_verification_sessions"], 2)
        self.assertEqual(am["successful_sessions"], 1)
        self.assertEqual(am["failed_sessions"], 1)
        self.assertEqual(am["average_attempts_per_session"], 1.5)

        # Snooze reduction: (4 - 2) / 4 * 100 = 50.0%
        self.assertEqual(am["snooze_reduction_status"], "available")
        self.assertEqual(am["snooze_reduction_rate"], 50.0)
        self.assertEqual(am["current_period_snoozes"], 2)
        self.assertEqual(am["previous_period_snoozes"], 4)
        self.assertIn("+50.0%", am["snooze_reduction_display"])

    def test_difficulty_adaptation_effectiveness(self):
        """Test adaptive difficulty comparison before vs after adaptation."""
        user = User(
            name="Adaptive User",
            email="adaptive@example.com",
            password=hash_password("password123"),
            role="USER"
        )
        self.db.add(user)
        self.db.commit()

        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

        # First half (attempts 1 & 2): 1 correct out of 2 (50% accuracy)
        self.db.add(ChallengeAttempt(
            user_id=user.id,
            challenge_type="Math Problems",
            difficulty="Easy",
            question="1+1",
            correct_answer="2",
            user_answer="2",
            is_correct=True,
            verification_status="passed",
            created_at=now - datetime.timedelta(days=5)
        ))
        self.db.add(ChallengeAttempt(
            user_id=user.id,
            challenge_type="Math Problems",
            difficulty="Easy",
            question="2+2",
            correct_answer="4",
            user_answer="5",
            is_correct=False,
            verification_status="failed",
            created_at=now - datetime.timedelta(days=4)
        ))

        # Second half (attempts 3 & 4): 2 correct out of 2 (100% accuracy)
        self.db.add(ChallengeAttempt(
            user_id=user.id,
            challenge_type="Math Problems",
            difficulty="Medium",
            question="3*3",
            correct_answer="9",
            user_answer="9",
            is_correct=True,
            verification_status="passed",
            created_at=now - datetime.timedelta(days=2)
        ))
        self.db.add(ChallengeAttempt(
            user_id=user.id,
            challenge_type="Math Problems",
            difficulty="Medium",
            question="4*4",
            correct_answer="16",
            user_answer="16",
            is_correct=True,
            verification_status="passed",
            created_at=now - datetime.timedelta(days=1)
        ))
        self.db.commit()

        metrics = calculate_performance_metrics(self.db, period_days=7)
        cm = metrics["challenge_metrics"]
        adapt = cm["adaptation_effectiveness"]

        self.assertEqual(adapt["status"], "available")
        self.assertEqual(adapt["accuracy_before_adaptation"], 50.0)
        self.assertEqual(adapt["accuracy_after_adaptation"], 100.0)
        self.assertEqual(adapt["performance_change_pct"], 50.0)
        self.assertEqual(adapt["adaptation_trend"], "positive")

    def test_performance_metrics_collector(self):
        """Test the PerformanceMetricsCollector timing and statistics calculations."""
        collector = PerformanceMetricsCollector(max_records=100)

        # Initially empty
        empty_api = collector.get_api_metrics()
        self.assertEqual(empty_api["status"], "insufficient_data")
        self.assertEqual(empty_api["request_count"], 0)

        # Record 5 requests
        collector.record_request("/api/alarms", "GET", 200, 10.0)
        collector.record_request("/api/alarms", "GET", 200, 20.0)
        collector.record_request("/api/alarms", "GET", 200, 30.0)
        collector.record_request("/api/admin/dashboard", "GET", 200, 40.0)
        collector.record_request("/api/admin/dashboard", "GET", 200, 50.0)

        api_stats = collector.get_api_metrics()
        self.assertEqual(api_stats["status"], "available")
        self.assertEqual(api_stats["request_count"], 5)
        self.assertEqual(api_stats["average_response_time_ms"], 30.0)
        self.assertEqual(api_stats["median_response_time_ms"], 30.0)
        self.assertEqual(len(api_stats["slowest_requests"]), 2)

        # Challenge generation stats
        collector.record_challenge_generation("Math Problems", "Medium", "Gemini (gemini-2.5-flash)", 150.0, success=True, is_fallback=False)
        collector.record_challenge_generation("Logic Puzzles", "Hard", "Local Cognitive Engine", 5.0, success=True, is_fallback=True)

        chal_stats = collector.get_challenge_generation_metrics()
        self.assertEqual(chal_stats["status"], "available")
        self.assertEqual(chal_stats["successful_generations"], 2)
        self.assertEqual(chal_stats["fallback_generations"], 1)
        self.assertEqual(chal_stats["provider_breakdown"]["Local Cognitive Engine"], 1)

    def test_admin_performance_metrics_api_endpoint(self):
        """Test GET /api/admin/performance-metrics requires Admin authentication and returns consolidated payload."""
        admin = User(
            name="Chief Admin",
            email="admin_metrics@example.com",
            password=hash_password("adminPass123"),
            role="ADMIN"
        )
        self.db.add(admin)
        self.db.commit()

        # 1. Unauthenticated request should return 401
        resp_unauth = self.client.get("/api/admin/performance-metrics")
        self.assertEqual(resp_unauth.status_code, 401)

        # 2. Authenticated admin request
        token = create_access_token(data={"sub": admin.email, "role": "ADMIN"})
        resp = self.client.get(
            "/api/admin/performance-metrics?period_days=7",
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertIn("period", data)
        self.assertIn("alarm_metrics", data)
        self.assertIn("challenge_metrics", data)
        self.assertIn("habit_metrics", data)
        self.assertIn("recommendation_metrics", data)
        self.assertIn("system_metrics", data)
        self.assertEqual(data["period"]["days"], 7)


if __name__ == "__main__":
    unittest.main()
