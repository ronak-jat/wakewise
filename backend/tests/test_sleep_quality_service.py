import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from database import Base, get_db
from models import User, Alarm, ChallengeAttempt, AlarmSnoozeEvent
from services.sleep_quality_service import (
    calculate_sleep_quality,
    get_sleep_quality_level,
    _compute_duration_score,
    _compute_consistency_score,
    SLEEP_QUALITY_WEIGHTS,
)
from services.habit_score_service import calculate_habit_score_snapshot
from main import app
from routes.auth import get_current_user


class SleepQualityServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

        # Create base test user
        self.user = User(
            name="Sleep Quality User",
            email="sleepq@example.com",
            password="hashed_pw",
            role="USER",
            target_bedtime="23:00",
            target_wake_time="07:00",
            inactivity_threshold_minutes=30,
        )
        self.session.add(self.user)
        self.session.commit()
        self.session.refresh(self.user)

        self.alarm = Alarm(
            user_id=self.user.id,
            title="7 AM Wake Alarm",
            alarm_time="07:00",
            alarm_type="Daily",
            repeat_days="Mon,Tue,Wed,Thu,Fri",
            is_active=True,
            challenge="Math Problems",
            difficulty_level="Medium",
            snooze_duration=5,
            max_snoozes=3,
        )
        self.session.add(self.alarm)
        self.session.commit()
        self.session.refresh(self.alarm)

    def tearDown(self):
        self.session.close()
        Base.metadata.drop_all(self.engine)

    # 1. Level Interpretation
    def test_sleep_quality_level_mapping(self):
        self.assertEqual(get_sleep_quality_level(95), "Excellent")
        self.assertEqual(get_sleep_quality_level(82), "Good")
        self.assertEqual(get_sleep_quality_level(68), "Fair")
        self.assertEqual(get_sleep_quality_level(45), "Needs Improvement")
        self.assertEqual(get_sleep_quality_level(25), "Poor")
        self.assertIsNone(get_sleep_quality_level(None))

    # 2. Duration Scoring Formula
    def test_duration_scoring(self):
        # Target 8.0 hours
        self.assertEqual(_compute_duration_score(8.0, 8.0), 100.0)  # exact
        self.assertEqual(_compute_duration_score(7.8, 8.0), 100.0)  # <= 0.5h diff
        self.assertEqual(_compute_duration_score(7.2, 8.0), 90.0)   # <= 1.0h diff
        self.assertEqual(_compute_duration_score(6.6, 8.0), 80.0)   # <= 1.5h diff
        self.assertEqual(_compute_duration_score(6.0, 8.0), 65.0)   # <= 2.0h diff
        self.assertEqual(_compute_duration_score(5.0, 8.0), 45.0)   # <= 3.0h diff
        self.assertEqual(_compute_duration_score(4.0, 8.0), 25.0)   # > 3.0h diff

    # 3. Consistency Scoring Formula
    def test_consistency_scoring(self):
        self.assertEqual(_compute_consistency_score(10.0), 100.0)  # <= 15m std dev
        self.assertEqual(_compute_consistency_score(25.0), 90.0)   # <= 30m
        self.assertEqual(_compute_consistency_score(40.0), 80.0)   # <= 45m
        self.assertEqual(_compute_consistency_score(55.0), 70.0)   # <= 60m
        self.assertEqual(_compute_consistency_score(75.0), 55.0)   # <= 90m
        self.assertEqual(_compute_consistency_score(105.0), 40.0)  # <= 120m
        self.assertEqual(_compute_consistency_score(150.0), 25.0)  # > 120m

    # 4. User with Insufficient History
    def test_user_with_insufficient_history(self):
        # Brand new user with no inactivity or attempts
        res = calculate_sleep_quality(self.session, self.user.id, days=7)
        self.assertEqual(res["status"], "insufficient_data")
        self.assertIsNone(res["score"])
        self.assertIsNone(res["level"])
        self.assertTrue(res["estimated"])
        self.assertIn("More sleep history is needed", res["message"])

    # 5. User with Sufficient Real Sleep Data
    def test_user_with_sufficient_sleep_history(self):
        now = datetime.now()
        base_time = now - timedelta(days=5)

        # Set user's latest estimated sleep start & end
        self.user.estimated_sleep_start = (now - timedelta(days=1)).replace(hour=23, minute=5, second=0)
        self.user.estimated_sleep_end = now.replace(hour=7, minute=5, second=0)
        self.session.commit()

        # Add challenge attempts across 5 days representing wake events around 07:05 AM
        for i in range(5):
            day_dt = base_time + timedelta(days=i)
            attempt = ChallengeAttempt(
                user_id=self.user.id,
                alarm_id=self.alarm.id,
                challenge_type="Math Problems",
                difficulty="Medium",
                question="5 + 5",
                correct_answer="10",
                user_answer="10",
                is_correct=True,
                time_taken=12,
                verification_status="passed",
                created_at=day_dt.replace(hour=7, minute=5, second=0),
                completed_at=day_dt.replace(hour=7, minute=7, second=0),
            )
            self.session.add(attempt)
        self.session.commit()

        res = calculate_sleep_quality(self.session, self.user.id, days=7)
        self.assertEqual(res["status"], "available")
        self.assertIsNotNone(res["score"])
        self.assertTrue(70.0 <= res["score"] <= 100.0)
        self.assertIn(res["level"], ["Good", "Excellent"])
        self.assertTrue(res["estimated"])
        self.assertGreaterEqual(res["data_days"], 1)

        components = res["components"]
        self.assertIn("schedule_adherence", components)
        self.assertIn("sleep_duration", components)
        self.assertIn("consistency", components)
        self.assertGreater(components["schedule_adherence"], 80.0)
        self.assertGreater(components["sleep_duration"], 80.0)

        # Ensure history entries are created
        self.assertTrue(len(res["history"]) >= 1)
        for h in res["history"]:
            self.assertIn("date", h)
            self.assertIn("day", h)
            self.assertIn("score", h)
            self.assertIn("duration_hours", h)

    # 6. Consistent vs Inconsistent Sleep Schedules
    def test_consistent_vs_inconsistent_schedule(self):
        # User 1: Consistent wake time (07:00 every day)
        now = datetime.now()
        for i in range(4):
            day_dt = now - timedelta(days=i + 1)
            self.session.add(ChallengeAttempt(
                user_id=self.user.id,
                alarm_id=self.alarm.id,
                challenge_type="Math Problems",
                difficulty="Medium",
                question="2+2",
                correct_answer="4",
                user_answer="4",
                is_correct=True,
                time_taken=10,
                verification_status="passed",
                created_at=day_dt.replace(hour=7, minute=2, second=0),
                completed_at=day_dt.replace(hour=7, minute=4, second=0),
            ))
        self.user.estimated_sleep_start = (now - timedelta(days=1)).replace(hour=23, minute=5)
        self.user.estimated_sleep_end = now.replace(hour=7, minute=5)
        self.session.commit()

        res_consistent = calculate_sleep_quality(self.session, self.user.id, days=7)
        consist_score = res_consistent["components"]["consistency"]
        self.assertGreaterEqual(consist_score, 80.0)

        # User 2: Inconsistent user
        user2 = User(
            name="Inconsistent User",
            email="incon@example.com",
            password="pw",
            role="USER",
            target_bedtime="23:00",
            target_wake_time="07:00",
        )
        self.session.add(user2)
        self.session.commit()

        # Wildly fluctuating wake times (05:00, 11:30, 06:15, 10:45)
        wake_hours = [5, 11, 6, 10]
        wake_mins = [0, 30, 15, 45]
        for i in range(4):
            day_dt = now - timedelta(days=i + 1)
            self.session.add(ChallengeAttempt(
                user_id=user2.id,
                alarm_id=self.alarm.id,
                challenge_type="Math Problems",
                difficulty="Medium",
                question="2+2",
                correct_answer="4",
                user_answer="4",
                is_correct=True,
                time_taken=10,
                verification_status="passed",
                created_at=day_dt.replace(hour=wake_hours[i], minute=wake_mins[i], second=0),
                completed_at=day_dt.replace(hour=wake_hours[i], minute=wake_mins[i] + 2, second=0),
            ))
        user2.estimated_sleep_start = (now - timedelta(days=1)).replace(hour=2, minute=30)
        user2.estimated_sleep_end = now.replace(hour=10, minute=45)
        self.session.commit()

        res_inconsistent = calculate_sleep_quality(self.session, user2.id, days=7)
        self.assertLess(res_inconsistent["components"]["consistency"], consist_score)
        self.assertLess(res_inconsistent["score"], res_consistent["score"])

    # 7. Short Sleep Duration Penalization
    def test_short_sleep_duration_penalty(self):
        now = datetime.now()
        # User sleeps 3.5 hours (03:30 AM to 07:00 AM)
        self.user.estimated_sleep_start = (now - timedelta(days=1)).replace(hour=3, minute=30, second=0)
        self.user.estimated_sleep_end = now.replace(hour=7, minute=0, second=0)
        self.session.add(ChallengeAttempt(
            user_id=self.user.id,
            alarm_id=self.alarm.id,
            challenge_type="Math Problems",
            difficulty="Medium",
            question="1+1",
            correct_answer="2",
            user_answer="2",
            is_correct=True,
            time_taken=10,
            verification_status="passed",
            created_at=now.replace(hour=7, minute=0, second=0),
            completed_at=now.replace(hour=7, minute=2, second=0),
        ))
        self.session.commit()

        res = calculate_sleep_quality(self.session, self.user.id, days=7)
        self.assertLessEqual(res["components"]["sleep_duration"], 50.0)

    # 8. Habit Score remains intact and independent
    def test_habit_score_independent(self):
        now = datetime.now()
        self.user.estimated_sleep_start = (now - timedelta(days=1)).replace(hour=23, minute=10)
        self.user.estimated_sleep_end = now.replace(hour=7, minute=5)
        self.session.commit()

        habit_snap = calculate_habit_score_snapshot(self.session, self.user.id, period_days=7)
        sleep_snap = calculate_sleep_quality(self.session, self.user.id, days=7)

        self.assertIn("habit_score", habit_snap)
        self.assertIn("breakdown", habit_snap)
        self.assertIn("sleep_schedule_adherence", habit_snap["breakdown"])
        self.assertIn("score", sleep_snap)
        self.assertIn("components", sleep_snap)


class SleepQualityApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

        self.user = User(
            name="API Sleep User",
            email="apisleep@example.com",
            password="pw",
            role="USER",
            target_bedtime="23:00",
            target_wake_time="07:00",
            inactivity_threshold_minutes=30,
        )
        self.session.add(self.user)
        self.session.commit()
        self.session.refresh(self.user)

        now = datetime.now()
        self.user.estimated_sleep_start = (now - timedelta(days=1)).replace(hour=23, minute=15)
        self.user.estimated_sleep_end = now.replace(hour=7, minute=5)
        self.session.commit()

        def override_get_db():
            try:
                yield self.session
            finally:
                pass

        def override_get_current_user():
            return self.user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.session.close()
        Base.metadata.drop_all(self.engine)

    def test_dashboard_sleep_quality_endpoint(self):
        response = self.client.get("/api/dashboard/sleep-quality?days=7")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "available")
        self.assertTrue(data["estimated"])
        self.assertIsNotNone(data["score"])
        self.assertIn(data["level"], ["Good", "Excellent", "Fair"])
        self.assertIn("components", data)
        self.assertIn("*Estimated from phone inactivity", data["disclaimer"])

    def test_analytics_sleep_quality_endpoint(self):
        response = self.client.get("/api/analytics/sleep-quality?days=7")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "available")
        self.assertIn("components", data)

    def test_dashboard_overview_includes_sleep_quality(self):
        response = self.client.get("/api/dashboard/overview")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("sleep_quality_score", data)
        self.assertIn("sleep_quality_level", data)
        self.assertIsNotNone(data["sleep_quality_score"])

    def test_categorized_recommendations_integration(self):
        response = self.client.get("/api/dashboard/recommendations")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("recommendations", data)
        # Sleep improvement recommendations exist
        sleep_recs = [r for r in data["recommendations"] if r["category"] == "Sleep Improvement"]
        self.assertTrue(len(sleep_recs) >= 1)


if __name__ == "__main__":
    unittest.main()
