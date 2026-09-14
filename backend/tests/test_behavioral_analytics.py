import os
import sys
import unittest
from datetime import datetime, timedelta

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import User, Alarm, ChallengeAttempt, AlarmSnoozeEvent
from routes.analytics import build_behavioral_analytics


class BehavioralAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

        self.user = User(name="Test User", email="behavior@example.com", password="pw", role="USER")
        self.session.add(self.user)
        self.session.commit()
        self.session.refresh(self.user)

        self.alarm = Alarm(
            user_id=self.user.id,
            title="Morning Alarm",
            alarm_time="07:30",
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

    def test_returns_structured_behavioral_summary(self):
        finished = datetime.now() - timedelta(days=1)
        self.session.add(
            ChallengeAttempt(
                user_id=self.user.id,
                alarm_id=self.alarm.id,
                challenge_type="Math Problems",
                difficulty="Medium",
                question="What is 2 + 2?",
                correct_answer="4",
                user_answer="4",
                is_correct=True,
                attempt_number=1,
                time_taken=12,
                time_limit=20,
                verification_status="passed",
                session_id="verif_123",
                wakefulness_rating=4,
                completed_at=finished + timedelta(hours=1),
                created_at=finished,
            )
        )
        self.session.commit()

        payload = build_behavioral_analytics(self.session, self.user.id)

        self.assertIn("snooze_pattern", payload)
        self.assertIn("wake_up_behavior", payload)
        self.assertIn("productivity_correlation", payload)
        self.assertIn("habit_consistency", payload)
        self.assertIn("sleep_pattern", payload)
        self.assertIn("insights", payload)
        self.assertIsInstance(payload["habit_consistency"], dict)

    def test_uses_persisted_snooze_records_for_analytics(self):
        self.session.add(
            AlarmSnoozeEvent(
                user_id=self.user.id,
                alarm_id=self.alarm.id,
                snooze_count=3,
                scheduled_for=datetime.now() - timedelta(minutes=30),
            )
        )
        self.session.commit()

        payload = build_behavioral_analytics(self.session, self.user.id)

        self.assertEqual(payload["snooze_pattern"]["total_snoozes"], 3)
        self.assertGreaterEqual(payload["snooze_pattern"]["average_snoozes_per_alarm"], 3)

    def test_tracks_average_wakefulness_and_time_to_wake(self):
        started = datetime.now() - timedelta(hours=1)
        completed = started + timedelta(minutes=15)
        self.session.add(
            ChallengeAttempt(
                user_id=self.user.id,
                alarm_id=self.alarm.id,
                challenge_type="Math Problems",
                difficulty="Medium",
                question="What is 6 + 7?",
                correct_answer="13",
                user_answer="13",
                is_correct=True,
                attempt_number=1,
                time_taken=8,
                time_limit=20,
                verification_status="passed",
                session_id="wake_session_001",
                wakefulness_rating=4,
                created_at=started,
                completed_at=completed,
            )
        )
        self.session.commit()

        payload = build_behavioral_analytics(self.session, self.user.id)

        self.assertEqual(payload["wake_up_behavior"]["average_wakefulness_rating"], 4.0)
        self.assertEqual(payload["wake_up_behavior"]["average_time_to_wake_minutes"], 15.0)


if __name__ == "__main__":
    unittest.main()
