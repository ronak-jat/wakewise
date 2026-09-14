import os
import sys
import unittest
from datetime import datetime, timedelta

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.personalization_service import (
    DIFFICULTY_LEVELS,
    ALLOWED_TYPES,
    normalize_difficulty,
    step_difficulty,
    AdaptiveDifficultyEngine,
    get_adaptive_recommendation,
    calculate_personalized_difficulty
)
from schemas import (
    AlarmCreate,
    AlarmUpdate,
    ChallengeResponse,
    ChallengeValidateResponse,
    AdaptiveRecommendationResponse
)


class MockAttempt:
    def __init__(self, challenge_type="Math Problems", difficulty="Medium", is_correct=True, time_taken=8, time_limit=30, created_at=None):
        self.challenge_type = challenge_type
        self.difficulty = difficulty
        self.is_correct = is_correct
        self.time_taken = time_taken
        self.time_limit = time_limit
        self.created_at = created_at or datetime.now()


class MockQuery:
    def __init__(self, data):
        self._data = data

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._data)


class MockDB:
    def __init__(self, attempts=None):
        self._attempts = attempts or []

    def query(self, model):
        return MockQuery(self._attempts)


class AdaptiveDifficultyEngineTests(unittest.TestCase):
    """
    Test suite for the Adaptive Difficulty Engine.
    """

    def test_canonical_difficulty_levels_and_aliases(self):
        """Validates the 5 canonical levels and legacy alias normalization."""
        self.assertEqual(DIFFICULTY_LEVELS, ["Beginner", "Easy", "Medium", "Hard", "Expert"])
        
        # Test normalizations
        self.assertEqual(normalize_difficulty("beginner"), "Beginner")
        self.assertEqual(normalize_difficulty("easy"), "Easy")
        self.assertEqual(normalize_difficulty("medium"), "Medium")
        self.assertEqual(normalize_difficulty("hard"), "Hard")
        self.assertEqual(normalize_difficulty("expert"), "Expert")
        
        # Legacy aliases
        self.assertEqual(normalize_difficulty("Difficult"), "Hard")
        self.assertEqual(normalize_difficulty("Advanced"), "Expert")
        self.assertEqual(normalize_difficulty("unknown"), "Medium")

    def test_step_difficulty_boundaries_and_clamping(self):
        """Validates stepping difficulty up/down and boundary clamping."""
        self.assertEqual(step_difficulty("Beginner", +1), "Easy")
        self.assertEqual(step_difficulty("Easy", +1), "Medium")
        self.assertEqual(step_difficulty("Medium", +1), "Hard")
        self.assertEqual(step_difficulty("Hard", +1), "Expert")
        
        # Clamping at top
        self.assertEqual(step_difficulty("Expert", +1), "Expert")

        # Stepping down
        self.assertEqual(step_difficulty("Expert", -1), "Hard")
        self.assertEqual(step_difficulty("Hard", -1), "Medium")
        self.assertEqual(step_difficulty("Medium", -1), "Easy")
        self.assertEqual(step_difficulty("Easy", -1), "Beginner")
        
        # Clamping at bottom
        self.assertEqual(step_difficulty("Beginner", -1), "Beginner")

    def test_excellent_performance_upgrades_difficulty(self):
        """Rule: 90%+ accuracy and fast completion increases difficulty (+1)."""
        attempts = [
            MockAttempt(challenge_type="Math Problems", difficulty="Medium", is_correct=True, time_taken=6, time_limit=30)
            for _ in range(5)
        ]
        
        analysis = AdaptiveDifficultyEngine.analyze_user_performance(attempts)
        self.assertEqual(analysis["recent_accuracy"], 100.0)
        self.assertLessEqual(analysis["avg_speed_ratio"], 0.65)
        
        rec = AdaptiveDifficultyEngine.determine_recommendation(analysis, base_difficulty="Medium")
        self.assertEqual(rec["recommended_difficulty"], "Hard")
        self.assertIn("Increased difficulty", rec["reason"])

    def test_average_performance_maintains_difficulty(self):
        """Rule: 70-89% accuracy maintains difficulty level."""
        attempts = [
            MockAttempt(challenge_type="Logic Puzzles", difficulty="Medium", is_correct=True, time_taken=12),
            MockAttempt(challenge_type="Logic Puzzles", difficulty="Medium", is_correct=True, time_taken=10),
            MockAttempt(challenge_type="Logic Puzzles", difficulty="Medium", is_correct=False, time_taken=20),
            MockAttempt(challenge_type="Logic Puzzles", difficulty="Medium", is_correct=True, time_taken=14),
            MockAttempt(challenge_type="Logic Puzzles", difficulty="Medium", is_correct=True, time_taken=11),
        ]
        
        analysis = AdaptiveDifficultyEngine.analyze_user_performance(attempts)
        self.assertEqual(analysis["recent_accuracy"], 80.0)
        
        rec = AdaptiveDifficultyEngine.determine_recommendation(analysis, base_difficulty="Medium")
        self.assertEqual(rec["recommended_difficulty"], "Medium")
        self.assertIn("Maintained Medium difficulty", rec["reason"])

    def test_poor_performance_or_repeated_failures_decreases_difficulty(self):
        """Rule: <70% accuracy or repeated failures decreases difficulty (-1)."""
        attempts = [
            MockAttempt(challenge_type="Pattern Recognition", difficulty="Hard", is_correct=False, time_taken=25),
            MockAttempt(challenge_type="Pattern Recognition", difficulty="Hard", is_correct=False, time_taken=28),
            MockAttempt(challenge_type="Pattern Recognition", difficulty="Hard", is_correct=True, time_taken=15),
        ]
        
        analysis = AdaptiveDifficultyEngine.analyze_user_performance(attempts)
        self.assertEqual(analysis["consecutive_failures"], 2)
        
        rec = AdaptiveDifficultyEngine.determine_recommendation(analysis, base_difficulty="Hard")
        self.assertEqual(rec["recommended_difficulty"], "Medium")
        self.assertIn("Reduced difficulty", rec["reason"])

    def test_strong_and_weak_challenge_type_identification(self):
        """Validates identification of strong (>=85%) and weak (<70%) challenge types."""
        attempts = [
            # Math: 3/3 = 100% (Strong)
            MockAttempt(challenge_type="Math Problems", difficulty="Medium", is_correct=True, time_taken=5),
            MockAttempt(challenge_type="Math Problems", difficulty="Medium", is_correct=True, time_taken=6),
            MockAttempt(challenge_type="Math Problems", difficulty="Medium", is_correct=True, time_taken=7),
            # Memory: 1/3 = 33.3% (Weak)
            MockAttempt(challenge_type="Memory Challenges", difficulty="Medium", is_correct=False, time_taken=22),
            MockAttempt(challenge_type="Memory Challenges", difficulty="Medium", is_correct=False, time_taken=24),
            MockAttempt(challenge_type="Memory Challenges", difficulty="Medium", is_correct=True, time_taken=18),
        ]
        
        analysis = AdaptiveDifficultyEngine.analyze_user_performance(attempts)
        self.assertIn("Math Problems", analysis["strong_types"])
        self.assertIn("Memory Challenges", analysis["weak_types"])
        
        # Test domain specific boost for Math
        rec_math = AdaptiveDifficultyEngine.determine_recommendation(
            analysis, base_difficulty="Medium", requested_type="Math Problems"
        )
        self.assertEqual(rec_math["recommended_difficulty"], "Hard")
        self.assertIn("Math Problems", rec_math["reason"])

        # Test domain specific relaxation for Memory
        rec_memory = AdaptiveDifficultyEngine.determine_recommendation(
            analysis, base_difficulty="Medium", requested_type="Memory Challenges"
        )
        self.assertEqual(rec_memory["recommended_difficulty"], "Easy")

    def test_engagement_optimization_anti_repetition(self):
        """Engagement rule: Avoid repeating the same challenge type after 2+ consecutive sessions."""
        attempts = [
            MockAttempt(challenge_type="Math Problems", difficulty="Medium", is_correct=True, time_taken=8),
            MockAttempt(challenge_type="Math Problems", difficulty="Medium", is_correct=True, time_taken=9),
            MockAttempt(challenge_type="Logic Puzzles", difficulty="Medium", is_correct=True, time_taken=10),
        ]
        
        analysis = AdaptiveDifficultyEngine.analyze_user_performance(attempts)
        rec = AdaptiveDifficultyEngine.determine_recommendation(analysis, base_difficulty="Medium", requested_type=None)
        self.assertNotEqual(rec["recommended_challenge_type"], "Math Problems")
        self.assertIn("avoid repeating 'Math Problems'", rec["reason"])

    def test_cognitive_score_and_trend_calculation(self):
        """Validates score generation (0-100) and trend detection."""
        improving_attempts = [
            MockAttempt(challenge_type="Word Games", difficulty="Medium", is_correct=True, time_taken=7)
            for _ in range(5)
        ] + [
            MockAttempt(challenge_type="Word Games", difficulty="Medium", is_correct=False, time_taken=20)
            for _ in range(5)
        ]
        
        analysis = AdaptiveDifficultyEngine.analyze_user_performance(improving_attempts)
        self.assertGreater(analysis["score"], 70.0)
        self.assertEqual(analysis["trend"], "improving")

    def test_database_integration_helper(self):
        """Validates get_adaptive_recommendation and calculate_personalized_difficulty with DB session."""
        mock_attempts = [
            MockAttempt(challenge_type="Quick Quizzes", difficulty="Easy", is_correct=True, time_taken=5)
            for _ in range(4)
        ]
        db = MockDB(mock_attempts)
        
        rec = get_adaptive_recommendation(db, user_id=1, base_difficulty="Easy")
        self.assertIn(rec["recommended_difficulty"], ["Easy", "Medium"])
        self.assertIsInstance(rec["reason"], str)
        self.assertIn("score", rec["analysis"])

        diff_str = calculate_personalized_difficulty(db, user_id=1, base_difficulty="Easy")
        self.assertIn(diff_str, DIFFICULTY_LEVELS)

    def test_pydantic_schema_validation(self):
        """Validates Pydantic schema validation for difficulty levels and snooze_duration."""
        alarm = AlarmCreate(
            title="Morning Alarm",
            alarm_time="07:00",
            alarm_type="Daily",
            difficulty_level="Hard",
            snooze_duration=5
        )
        self.assertEqual(alarm.difficulty_level, "Hard")
        self.assertEqual(alarm.snooze_duration, 5)

        alarm_expert = AlarmCreate(
            title="Expert Alarm",
            alarm_time="08:00",
            alarm_type="Daily",
            difficulty_level="Expert"
        )
        self.assertEqual(alarm_expert.difficulty_level, "Expert")

        alarm_legacy = AlarmCreate(
            title="Legacy Alarm",
            alarm_time="06:30",
            alarm_type="Daily",
            difficulty_level="Difficult"
        )
        self.assertEqual(alarm_legacy.difficulty_level, "Hard")

    def test_gemini_fallback_supports_hard_and_expert(self):
        """Validates that fallback challenge service cleanly delivers challenges for Hard and Expert."""
        from services.fallback_challenges import get_fallback_challenge
        
        chal_hard = get_fallback_challenge("Math Problems", "Hard")
        self.assertEqual(chal_hard["difficulty"], "Hard")
        self.assertTrue(len(chal_hard["options"]) > 0)
        self.assertTrue(len(chal_hard["question"]) > 0)

        chal_expert = get_fallback_challenge("Logic Puzzles", "Expert")
        self.assertEqual(chal_expert["difficulty"], "Expert")
        self.assertTrue(len(chal_expert["question"]) > 0)

    def test_timeouts_and_failed_counts_computation(self):
        """Validates timeouts and failed count computation in analysis."""
        attempts = [
            MockAttempt(challenge_type="Riddles", difficulty="Medium", is_correct=False, time_taken=30, time_limit=30),
            MockAttempt(challenge_type="Riddles", difficulty="Medium", is_correct=False, time_taken=15, time_limit=30),
            MockAttempt(challenge_type="Riddles", difficulty="Medium", is_correct=True, time_taken=10, time_limit=30),
        ]
        
        analysis = AdaptiveDifficultyEngine.analyze_user_performance(attempts)
        self.assertEqual(analysis["timeouts"], 1)
        self.assertEqual(analysis["failed_attempts"], 2)
        self.assertEqual(analysis["passed_attempts"], 1)
        self.assertLess(analysis["score"], 60.0)

    def test_empty_attempts_baseline(self):
        """Validates default behavior when a new user has zero attempts."""
        analysis = AdaptiveDifficultyEngine.analyze_user_performance([])
        self.assertEqual(analysis["total_attempts"], 0)
        self.assertEqual(analysis["overall_accuracy"], 0.0)

        rec = AdaptiveDifficultyEngine.determine_recommendation(analysis, base_difficulty="Medium")
        self.assertEqual(rec["recommended_difficulty"], "Medium")
        self.assertIn("Initial baseline difficulty set to Medium", rec["reason"])


if __name__ == "__main__":
    unittest.main()
