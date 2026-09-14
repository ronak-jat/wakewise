import os
import sys
import unittest
from types import SimpleNamespace

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


from scheduler import deactivate_one_time_alarm_if_needed


class OneTimeAlarmBehaviorTests(unittest.TestCase):
    def test_one_time_alarm_is_deactivated_after_trigger(self):
        alarm = SimpleNamespace(alarm_type="One-Time", is_active=True)
        db = SimpleNamespace(commit=lambda: None, add=lambda obj: None)

        changed = deactivate_one_time_alarm_if_needed(db, alarm)

        self.assertTrue(changed)
        self.assertFalse(alarm.is_active)

    def test_recurring_alarm_stays_active_after_trigger(self):
        alarm = SimpleNamespace(alarm_type="Daily", is_active=True)
        db = SimpleNamespace(commit=lambda: None, add=lambda obj: None)

        changed = deactivate_one_time_alarm_if_needed(db, alarm)

        self.assertFalse(changed)
        self.assertTrue(alarm.is_active)


if __name__ == "__main__":
    unittest.main()
