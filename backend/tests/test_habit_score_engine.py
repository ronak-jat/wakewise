import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import User, Alarm, ChallengeAttempt, AlarmSnoozeEvent
from services.habit_score_service import (
    calculate_habit_score_snapshot,
    calculate_sleep_adherence_snapshot,
    calculate_wake_up_consistency,
    calculate_challenge_completion,
    calculate_snooze_reduction,
    get_habit_level,
    get_habit_score_history,
    record_user_activity,
    update_user_sleep_schedule,
    _score_from_differences,
    clamp_score,
    HABIT_WEIGHTS,
)


class HabitScoreEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

        self.user = User(
            name="Test User",
            email="habit@example.com",
            password="pw",
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
            title="Morning Rise Alarm",
            alarm_time="07:00",
            alarm_type="Daily",
            repeat_days="Mon,Tue,Wed,Thu,Fri",
            is_active=True,
            challenge="Math Problems",
            difficulty_level="Medium",
            snooze_duration=5,
            max_snoozes=3,
            verification_method="multi_step",
            verification_steps=3,
            required_accuracy=67,
            consecutive_required=2,
            time_limit=20,
        )
        self.session.add(self.alarm)
        self.session.commit()
        self.session.refresh(self.alarm)

    def tearDown(self):
        self.session.close()
        Base.metadata.drop_all(self.engine)

    # 1. Exact Weighted Formula & Normalization
    def test_habit_score_uses_exact_weighted_formula(self):
        now = datetime.now()
        # Add a passed attempt close to scheduled alarm time
        self.session.add(
            ChallengeAttempt(
                user_id=self.user.id,
                alarm_id=self.alarm.id,
                challenge_type="Math Problems",
                difficulty="Medium",
                question="12 + 8",
                correct_answer="20",
                user_answer="20",
                is_correct=True,
                attempt_number=1,
                time_taken=6,
                time_limit=20,
                verification_status="passed",
                session_id="verif_weight_1",
                completed_at=now.replace(hour=7, minute=5, second=0),
                created_at=now.replace(hour=7, minute=4, second=0),
            )
        )
        # Set estimated sleep and wake times
        self.user.estimated_sleep_start = now.replace(hour=23, minute=10, second=0)
        self.user.estimated_sleep_end = now.replace(hour=7, minute=5, second=0)
        self.session.commit()

        payload = calculate_habit_score_snapshot(self.session, self.user.id, period_days=7)
        self.assertIn("habit_score", payload)
        self.assertIn("level", payload)
        self.assertGreaterEqual(payload["habit_score"], 0.0)
        self.assertLessEqual(payload["habit_score"], 100.0)

        weights = payload["weights"]
        self.assertEqual(weights["wake_up_consistency"], 0.35)
        self.assertEqual(weights["challenge_completion"], 0.25)
        self.assertEqual(weights["snooze_reduction"], 0.20)
        self.assertEqual(weights["sleep_schedule_adherence"], 0.20)

        # Verify exact math
        bd = payload["breakdown"]
        expected = clamp_score(
            bd["wake_up_consistency"] * 0.35
            + bd["challenge_completion"] * 0.25
            + bd["snooze_reduction"] * 0.20
            + bd["sleep_schedule_adherence"] * 0.20
        )
        self.assertAlmostEqual(payload["habit_score"], round(expected, 1), places=1)

    # 2. Habit Levels Exact Mapping
    def test_habit_levels_exact_thresholds(self):
        self.assertEqual(get_habit_level(100), "Excellent")
        self.assertEqual(get_habit_level(90), "Excellent")
        self.assertEqual(get_habit_level(89.9), "Good")
        self.assertEqual(get_habit_level(75), "Good")
        self.assertEqual(get_habit_level(74.9), "Fair")
        self.assertEqual(get_habit_level(60), "Fair")
        self.assertEqual(get_habit_level(59.9), "Needs Improvement")
        self.assertEqual(get_habit_level(40), "Needs Improvement")
        self.assertEqual(get_habit_level(39.9), "Poor")
        self.assertEqual(get_habit_level(0), "Poor")

    # 3. Wake-Up Consistency Scoring & Difference Tiers
    def test_wake_up_consistency_difference_scoring(self):
        self.assertEqual(_score_from_differences(5), 100.0)   # 0–15 mins
        self.assertEqual(_score_from_differences(15), 100.0)
        self.assertEqual(_score_from_differences(20), 90.0)   # 16–30 mins
        self.assertEqual(_score_from_differences(30), 90.0)
        self.assertEqual(_score_from_differences(45), 75.0)   # 31–60 mins
        self.assertEqual(_score_from_differences(90), 50.0)   # 61–120 mins
        self.assertEqual(_score_from_differences(150), 25.0)  # >120 mins

    def test_wake_up_consistency_penalizes_failed_verification(self):
        now = datetime.now()
        self.session.add(
            ChallengeAttempt(
                user_id=self.user.id,
                alarm_id=self.alarm.id,
                challenge_type="Math Problems",
                difficulty="Medium",
                question="9 * 9",
                correct_answer="81",
                user_answer="80",
                is_correct=False,
                attempt_number=1,
                time_taken=20,
                time_limit=20,
                verification_status="failed",
                session_id="verif_fail_1",
                completed_at=now,
                created_at=now,
            )
        )
        self.session.commit()

        res = calculate_wake_up_consistency(self.session, self.user.id, period_days=7)
        self.assertEqual(res["score"], 0.0)
        self.assertEqual(res["details"][0]["status"], "failed")

    # 4. Challenge Completion Success (25%)
    def test_challenge_completion_calculation(self):
        now = datetime.now()
        # 3 passed, 1 failed = 75% accuracy
        for i in range(3):
            self.session.add(
                ChallengeAttempt(
                    user_id=self.user.id,
                    alarm_id=self.alarm.id,
                    challenge_type="Math Problems",
                    difficulty="Medium",
                    question=f"Q{i}",
                    correct_answer="A",
                    user_answer="A",
                    is_correct=True,
                    attempt_number=1,
                    time_taken=5,
                    time_limit=20,
                    verification_status="passed",
                    created_at=now - timedelta(days=i),
                )
            )
        self.session.add(
            ChallengeAttempt(
                user_id=self.user.id,
                alarm_id=self.alarm.id,
                challenge_type="Math Problems",
                difficulty="Medium",
                question="Q_fail",
                correct_answer="A",
                user_answer="B",
                is_correct=False,
                attempt_number=1,
                time_taken=15,
                time_limit=20,
                verification_status="failed",
                created_at=now - timedelta(days=4),
            )
        )
        self.session.commit()

        res = calculate_challenge_completion(self.session, self.user.id, period_days=7)
        self.assertEqual(res["total"], 4)
        self.assertEqual(res["passed"], 3)
        self.assertEqual(res["score"], 75.0)

    # 5. Snooze Reduction Scoring (20%)
    def test_snooze_reduction_rewards_zero_snoozes(self):
        res = calculate_snooze_reduction(self.session, self.user.id, period_days=7)
        self.assertEqual(res["score"], 100.0)
        self.assertEqual(res["recent_total"], 0)

    def test_snooze_reduction_penalizes_frequent_snoozing(self):
        now = datetime.now()
        self.session.add(
            AlarmSnoozeEvent(
                user_id=self.user.id,
                alarm_id=self.alarm.id,
                snooze_count=3,
                scheduled_for=now,
                created_at=now,
            )
        )
        self.session.commit()

        res = calculate_snooze_reduction(self.session, self.user.id, period_days=7)
        self.assertLess(res["score"], 100.0)
        self.assertEqual(res["recent_total"], 3)

    # 6. Phone Inactivity Detection & Sleep Session Estimation
    def test_phone_inactivity_triggers_sleep_estimation_after_threshold(self):
        # Initial activity at 11:17 PM
        start_time = datetime(2026, 9, 9, 23, 17, 0)
        record_user_activity(self.session, self.user.id, activity_time=start_time)

        self.session.refresh(self.user)
        self.assertEqual(self.user.last_meaningful_activity_at, start_time)
        self.assertIsNone(self.user.estimated_sleep_start)

        # Inactivity continues for 35 minutes (>= 30m threshold)
        resume_time = start_time + timedelta(minutes=35)
        res = record_user_activity(self.session, self.user.id, activity_time=resume_time)

        self.session.refresh(self.user)
        self.assertTrue(res["sleep_session_created"])
        self.assertEqual(self.user.estimated_sleep_start, start_time)

    def test_phone_inactivity_resumed_before_threshold_does_not_confirm_sleep(self):
        start_time = datetime(2026, 9, 9, 23, 17, 0)
        record_user_activity(self.session, self.user.id, activity_time=start_time)

        # User becomes active again at 15 minutes (< 30m threshold)
        resume_time = start_time + timedelta(minutes=15)
        res = record_user_activity(self.session, self.user.id, activity_time=resume_time)

        self.session.refresh(self.user)
        self.assertFalse(res["sleep_session_created"])
        self.assertIsNone(self.user.estimated_sleep_start)
        self.assertEqual(self.user.last_meaningful_activity_at, resume_time)

    # 7. Sleep Schedule Adherence: Full, Partial, Insufficient Data
    def test_sleep_adherence_full_data(self):
        # Target: Bedtime 11:00 PM (23:00), Wake 7:00 AM (07:00)
        # Actual: Sleep estimated 11:17 PM (23:17) [diff=17m -> score 90]
        #         Wake actual 7:08 AM (07:08) [diff=8m -> score 100]
        # Total daily adherence = (90 + 100) / 2 = 95
        base_day = datetime(2026, 9, 9, 0, 0, 0)
        self.user.estimated_sleep_start = base_day.replace(hour=23, minute=17)
        self.user.estimated_sleep_end = (base_day + timedelta(days=1)).replace(hour=7, minute=8)
        self.session.commit()

        snapshot = calculate_sleep_adherence_snapshot(self.session, self.user.id)
        self.assertEqual(snapshot["status"], "available")
        self.assertEqual(snapshot["adherence_score"], 95.0)
        self.assertEqual(snapshot["bedtime_adherence"], 90.0)
        self.assertEqual(snapshot["wake_time_adherence"], 100.0)
        self.assertTrue(snapshot["estimated_from_phone_inactivity"])
        self.assertIn("Estimated from phone inactivity", snapshot["summary"])
        self.assertIn("17 minutes later", snapshot["insight"])

    def test_sleep_adherence_partial_wake_only(self):
        # Only wake time data available, no bedtime estimated
        self.user.estimated_sleep_start = None
        self.user.estimated_sleep_end = datetime(2026, 9, 9, 7, 10, 0)
        self.session.commit()

        snapshot = calculate_sleep_adherence_snapshot(self.session, self.user.id)
        self.assertEqual(snapshot["status"], "partial")
        self.assertIn("Wake-time adherence available", snapshot["message"])
        self.assertEqual(snapshot["wake_time_adherence"], 100.0)
        self.assertFalse(snapshot["estimated_from_phone_inactivity"])

    def test_sleep_adherence_insufficient_data(self):
        self.user.estimated_sleep_start = None
        self.user.estimated_sleep_end = None
        self.session.commit()

        snapshot = calculate_sleep_adherence_snapshot(self.session, self.user.id)
        self.assertEqual(snapshot["status"], "insufficient_data")
        self.assertIn("Insufficient Data", snapshot["message"])
        self.assertEqual(snapshot["adherence_score"], 0.0)

    # 8. Score History & Component Deltas
    def test_score_history_and_deltas(self):
        now = datetime.now()
        self.session.add(
            ChallengeAttempt(
                user_id=self.user.id,
                alarm_id=self.alarm.id,
                challenge_type="Math Problems",
                difficulty="Medium",
                question="3 + 3",
                correct_answer="6",
                user_answer="6",
                is_correct=True,
                attempt_number=1,
                time_taken=5,
                time_limit=20,
                verification_status="passed",
                completed_at=now,
                created_at=now,
            )
        )
        self.session.commit()

        history = get_habit_score_history(self.session, self.user.id, days=14)
        self.assertIn("daily_scores", history)
        self.assertIn("weekly_scores", history)
        self.assertIn("score_changes", history)
        self.assertIn("This Week", history["weekly_scores"])
        self.assertIn("Last Week", history["weekly_scores"])
        self.assertIn("Change", history["weekly_scores"])

    # 9. Update Sleep Schedule Helper
    def test_update_user_sleep_schedule_helper(self):
        res = update_user_sleep_schedule(
            self.session,
            self.user.id,
            target_bedtime="22:30",
            target_wake_time="06:30",
            inactivity_threshold_minutes=45,
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["target_bedtime"], "22:30")
        self.assertEqual(res["target_wake_time"], "06:30")
        self.assertEqual(res["inactivity_threshold_minutes"], 45)


if __name__ == "__main__":
    unittest.main()
