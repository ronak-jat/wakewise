import json
import urllib.request
import unittest

BASE_URL = "http://127.0.0.1:8000"

def post_json(endpoint: str, data: dict):
    req = urllib.request.Request(
        f"{BASE_URL}{endpoint}",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    res = urllib.request.urlopen(req)
    return json.loads(res.read().decode("utf-8"))

def get_json(endpoint: str):
    res = urllib.request.urlopen(f"{BASE_URL}{endpoint}")
    return json.loads(res.read().decode("utf-8"))

def server_is_running():
    try:
        urllib.request.urlopen(f"{BASE_URL}/health", timeout=1.0)
        return True
    except Exception:
        return False

@unittest.skipUnless(server_is_running(), "Requires running backend server at http://127.0.0.1:8000")
class TestLiveVerificationFlows(unittest.TestCase):

    def test_01_health_and_types(self):
        types_data = get_json("/api/challenges/types")
        methods = [m["id"] for m in types_data["verification_methods"]]
        self.assertIn("puzzle_completion", methods)
        self.assertIn("multi_step", methods)
        self.assertIn("consecutive_correct", methods)
        self.assertIn("time_based", methods)
        self.assertIn("accuracy_check", methods)

    def test_02_method1_puzzle_completion(self):
        start = post_json("/api/challenges/verification/start", {
            "verification_method": "puzzle_completion",
            "challenge_type": "Math Problems",
            "difficulty": "Easy"
        })
        session_id = start["session_id"]
        self.assertEqual(start["status"], "in_progress")
        self.assertEqual(start["total_steps"], 1)

        correct_ans = start["current_challenge"]["answer"]
        step = post_json("/api/challenges/verification/step", {
            "session_id": session_id,
            "user_answer": correct_ans,
            "time_taken": 3
        })
        self.assertEqual(step["verification_status"], "passed")
        self.assertTrue(step["is_step_correct"])

    def test_03_method2_multi_step(self):
        start = post_json("/api/challenges/verification/start", {
            "verification_method": "multi_step",
            "verification_steps": 3,
            "challenge_type": "Math Problems",
            "difficulty": "Easy"
        })
        session_id = start["session_id"]
        self.assertEqual(start["total_steps"], 3)
        self.assertEqual(start["current_step"], 1)

        # Step 1
        ans1 = start["current_challenge"]["answer"]
        step1 = post_json("/api/challenges/verification/step", {
            "session_id": session_id,
            "user_answer": ans1,
            "time_taken": 4
        })
        self.assertEqual(step1["verification_status"], "in_progress")
        self.assertEqual(step1["current_step"], 2)
        self.assertEqual(step1["correct_count"], 1)

        # Step 2
        ans2 = step1["next_challenge"]["answer"]
        step2 = post_json("/api/challenges/verification/step", {
            "session_id": session_id,
            "user_answer": ans2,
            "time_taken": 5
        })
        self.assertEqual(step2["verification_status"], "in_progress")
        self.assertEqual(step2["current_step"], 3)
        self.assertEqual(step2["correct_count"], 2)

        # Step 3
        ans3 = step2["next_challenge"]["answer"]
        step3 = post_json("/api/challenges/verification/step", {
            "session_id": session_id,
            "user_answer": ans3,
            "time_taken": 4
        })
        self.assertEqual(step3["verification_status"], "passed")
        self.assertEqual(step3["correct_count"], 3)

    def test_04_method3_consecutive_correct(self):
        start = post_json("/api/challenges/verification/start", {
            "verification_method": "consecutive_correct",
            "consecutive_required": 2,
            "challenge_type": "Math Problems",
            "difficulty": "Easy"
        })
        session_id = start["session_id"]
        self.assertEqual(start["consecutive_required"], 2)

        # 1st correct answer -> streak 1
        ans1 = start["current_challenge"]["answer"]
        s1 = post_json("/api/challenges/verification/step", {
            "session_id": session_id,
            "user_answer": ans1,
            "time_taken": 3
        })
        self.assertEqual(s1["verification_status"], "in_progress")
        self.assertEqual(s1["consecutive_correct"], 1)

        # 2nd wrong answer -> streak resets to 0!
        s2 = post_json("/api/challenges/verification/step", {
            "session_id": session_id,
            "user_answer": "wrong_ans_xyz",
            "time_taken": 4
        })
        self.assertEqual(s2["verification_status"], "failed")
        self.assertEqual(s2["consecutive_correct"], 0)

        # 3rd correct answer -> streak 1
        ans3 = s2["next_challenge"]["answer"]
        s3 = post_json("/api/challenges/verification/step", {
            "session_id": session_id,
            "user_answer": ans3,
            "time_taken": 3
        })
        self.assertEqual(s3["verification_status"], "in_progress")
        self.assertEqual(s3["consecutive_correct"], 1)

        # 4th correct answer -> streak 2 -> PASSED!
        ans4 = s3["next_challenge"]["answer"]
        s4 = post_json("/api/challenges/verification/step", {
            "session_id": session_id,
            "user_answer": ans4,
            "time_taken": 3
        })
        self.assertEqual(s4["verification_status"], "passed")
        self.assertEqual(s4["consecutive_correct"], 2)

    def test_05_method4_time_based(self):
        start = post_json("/api/challenges/verification/start", {
            "verification_method": "time_based",
            "time_limit": 10,
            "challenge_type": "Math Problems",
            "difficulty": "Easy"
        })
        session_id = start["session_id"]
        self.assertEqual(start["time_limit"], 10)

        # Exceed time limit / timeout
        t_out = post_json("/api/challenges/verification/step", {
            "session_id": session_id,
            "user_answer": "",
            "time_taken": 11,
            "is_timeout": True
        })
        self.assertEqual(t_out["verification_status"], "timeout")
        self.assertFalse(t_out["is_step_correct"])

        # Retry and solve
        next_ans = t_out["next_challenge"]["answer"]
        s_pass = post_json("/api/challenges/verification/step", {
            "session_id": session_id,
            "user_answer": next_ans,
            "time_taken": 4,
            "is_timeout": False
        })
        self.assertEqual(s_pass["verification_status"], "passed")

    def test_06_method5_accuracy_check(self):
        start = post_json("/api/challenges/verification/start", {
            "verification_method": "accuracy_check",
            "verification_steps": 3,
            "required_accuracy": 67.0,
            "challenge_type": "Math Problems",
            "difficulty": "Easy"
        })
        session_id = start["session_id"]

        # Step 1: Correct
        ans1 = start["current_challenge"]["answer"]
        s1 = post_json("/api/challenges/verification/step", {
            "session_id": session_id,
            "user_answer": ans1,
            "time_taken": 3
        })
        self.assertEqual(s1["verification_status"], "in_progress")
        self.assertEqual(s1["correct_count"], 1)

        # Step 2: Wrong
        s2 = post_json("/api/challenges/verification/step", {
            "session_id": session_id,
            "user_answer": "wrong_123",
            "time_taken": 4
        })
        self.assertEqual(s2["verification_status"], "in_progress")
        self.assertEqual(s2["correct_count"], 1)

        # Step 3: Correct (2 of 3 = 66.7% >= 67% rounded) -> Passed!
        ans3 = s2["next_challenge"]["answer"]
        s3 = post_json("/api/challenges/verification/step", {
            "session_id": session_id,
            "user_answer": ans3,
            "time_taken": 3
        })
        self.assertEqual(s3["verification_status"], "passed")
        self.assertEqual(s3["correct_count"], 2)

if __name__ == "__main__":
    unittest.main()
