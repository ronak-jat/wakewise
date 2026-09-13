import uuid
import logging
import threading
from typing import Dict, Optional, Any, List
from sqlalchemy.orm import Session

from models import ChallengeAttempt, User, Alarm
from services.gemini_service import generate_cognitive_challenge, map_challenge_type
from services.personalization_service import (
    get_adaptive_recommendation,
    step_difficulty,
    normalize_difficulty,
    get_time_limit_for_difficulty
)
from services.challenge_store import add_session, get_session, remove_session

logger = logging.getLogger(__name__)

def normalize_answer(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip().lower().replace(" ", "")


VERIFICATION_METHODS = [
    {
        "id": "puzzle_completion",
        "name": "Puzzle Completion",
        "description": "Alarm cannot be dismissed until the assigned cognitive challenge is successfully solved."
    },
    {
        "id": "multi_step",
        "name": "Multi-Step Challenge",
        "description": "Requires 2–3 sequential cognitive questions in the same wake-up session."
    },
    {
        "id": "consecutive_correct",
        "name": "Consecutive Correct Answers",
        "description": "Requires 2 or 3 consecutive correct answers. Any incorrect answer resets the streak counter."
    },
    {
        "id": "time_based",
        "name": "Time-Based Verification",
        "description": "Configurable strict time limit per challenge. Timeouts are recorded and force a retry."
    },
    {
        "id": "accuracy_check",
        "name": "Cognitive Accuracy Check",
        "description": "Requires a minimum accuracy percentage across questions before silencing the alarm."
    }
]

_session_lock = threading.RLock()
ACTIVE_VERIFICATION_SESSIONS: Dict[str, dict] = {}


def _generate_distinct_challenge(challenge_type: str, difficulty: str, previous_questions: set) -> dict:
    """Generate a challenge that has not already appeared in this session when possible."""
    challenge = None
    for _ in range(5):
        candidate = generate_cognitive_challenge(challenge_type, difficulty)
        if candidate.get("question") not in previous_questions:
            return candidate
        challenge = candidate
    return challenge


def get_verification_session_by_alarm(alarm_id: int, user_id: int) -> Optional[dict]:
    with _session_lock:
        for session in ACTIVE_VERIFICATION_SESSIONS.values():
            if session.get("alarm_id") == alarm_id and session.get("user_id") == user_id:
                return session
    return None



def init_verification_session(
    alarm: Optional[Alarm] = None,
    user_id: int = 1,
    challenge_type: str = "Math Problems",
    difficulty: str = "Medium",
    verification_method: str = "puzzle_completion",
    verification_steps: int = 1,
    required_accuracy: int = 100,
    consecutive_required: int = 1,
    time_limit: int = 20,
    first_challenge: Optional[dict] = None,
    alarm_id: Optional[int] = None
) -> dict:
    """
    Initializes a new wake-up verification session with rules, steps, and initial challenge.
    """
    if alarm:
        existing = get_verification_session_by_alarm(alarm.id, alarm.user_id)
        if existing:
            logger.info(
                "Verification session reused: session_id=%s alarm_id=%s user_id=%s status=%s",
                existing["session_id"], alarm.id, alarm.user_id, existing["status"]
            )
            return existing

    session_id = f"verif_{uuid.uuid4().hex[:12]}"
    
    # Extract config from alarm if provided
    if alarm:
        alarm_id = alarm.id
        user_id = alarm.user_id
        verification_method = alarm.verification_method or verification_method
        verification_steps = alarm.verification_steps or verification_steps
        required_accuracy = alarm.required_accuracy or required_accuracy
        consecutive_required = alarm.consecutive_required or consecutive_required
        time_limit = alarm.time_limit or time_limit
        challenge_type = alarm.challenge if alarm.challenge and alarm.challenge != "None" else challenge_type
        difficulty = alarm.difficulty_level or difficulty
    else:
        alarm_id = alarm_id

    # Sanitize and adjust defaults based on verification method
    method = (verification_method or "puzzle_completion").lower()
    if method == "multi_step":
        total_steps = max(2, min(5, verification_steps or 3))
        req_acc = required_accuracy if required_accuracy < 100 else 100
        consec_req = 1
    elif method == "consecutive_correct":
        consec_req = max(2, min(5, consecutive_required or 2))
        total_steps = consec_req
        req_acc = 100
    elif method == "accuracy_check":
        total_steps = max(2, min(5, verification_steps or 3))
        req_acc = required_accuracy if required_accuracy > 0 else 67
        consec_req = 1
    elif method == "time_based":
        total_steps = max(1, verification_steps or 1)
        req_acc = required_accuracy or 100
        consec_req = 1
        time_limit = min(30, max(5, time_limit or 15))
    else: # puzzle_completion
        method = "puzzle_completion"
        total_steps = 1
        req_acc = 100
        consec_req = 1

    # Generate first challenge if not supplied
    if not first_challenge:
        norm_type = map_challenge_type(challenge_type)
        norm_diff = normalize_difficulty(difficulty)
        first_challenge = generate_cognitive_challenge(norm_type, norm_diff)
        chal_id = f"chal_{uuid.uuid4().hex[:12]}"
        first_challenge["id"] = chal_id
        first_challenge["recommended_difficulty"] = norm_diff
        first_challenge["recommended_challenge_type"] = norm_type
        first_challenge["alarm_id"] = alarm_id
        first_challenge["time_limit"] = time_limit
        first_challenge["source"] = "verification_step"
        first_challenge["scheduler_generated"] = False
        add_session(chal_id, first_challenge)

    session_data = {
        "session_id": session_id,
        "alarm_id": alarm_id,
        "user_id": user_id,
        "challenge_type": challenge_type,
        "difficulty": difficulty,
        "verification_method": method,
        "status": "in_progress", # pending, in_progress, passed, failed, timeout
        "current_step": 1,
        "total_steps": total_steps,
        "correct_count": 0,
        "attempts": 0,
        "accuracy": 0,
        "required_accuracy": req_acc,
        "consecutive_correct": 0,
        "consecutive_required": consec_req,
        "time_limit": time_limit,
        "current_challenge": first_challenge,
        "history": []
    }

    with _session_lock:
        if alarm_id is not None:
            existing = get_verification_session_by_alarm(alarm_id, user_id)
            if existing:
                return existing
        ACTIVE_VERIFICATION_SESSIONS[session_id] = session_data

    logger.info(
        "Verification session started: session_id=%s alarm_id=%s user_id=%s step=1/%s challenge_id=%s source=%s",
        session_id, alarm_id, user_id, total_steps,
        first_challenge.get("id"), first_challenge.get("source", "unknown")
    )

    return session_data


def get_verification_session(session_id: str) -> Optional[dict]:
    with _session_lock:
        return ACTIVE_VERIFICATION_SESSIONS.get(session_id)


def remove_verification_session(session_id: str) -> None:
    with _session_lock:
        if session_id in ACTIVE_VERIFICATION_SESSIONS:
            del ACTIVE_VERIFICATION_SESSIONS[session_id]


def process_verification_step(
    session_id: str,
    user_answer: str,
    time_taken: float,
    is_timeout: bool,
    db: Session,
    user_id: int = 1,
    alarm_id: Optional[int] = None,
    step_number: Optional[int] = None,
    challenge_id: Optional[str] = None
) -> dict:
    with _session_lock:
        session = ACTIVE_VERIFICATION_SESSIONS.get(session_id)
        if not session:
            return _process_verification_step(
                session_id, user_answer, time_taken, is_timeout, db,
                user_id, alarm_id
            )

        requested_step = step_number or session.get("current_step", 1)
        idempotency_enabled = step_number is not None or challenge_id is not None
        processed_steps = session.setdefault("processed_steps", {})
        cached_response = processed_steps.get(str(requested_step))
        if idempotency_enabled and cached_response:
            logger.info(
                "Verification step replay: session_id=%s step=%s challenge_id=%s",
                session_id, requested_step, cached_response.get("current_challenge_id")
            )
            return cached_response["response"]

        current_challenge = session.get("current_challenge", {})
        expected_challenge_id = current_challenge.get("id")
        if idempotency_enabled and requested_step != session.get("current_step", 1):
            return _build_idempotent_state_response(session)
        if idempotency_enabled and challenge_id and expected_challenge_id and challenge_id != expected_challenge_id:
            return _build_idempotent_state_response(session)

        response = _process_verification_step(
            session_id, user_answer, time_taken, is_timeout, db,
            user_id, alarm_id
        )
        if idempotency_enabled:
            processed_steps[str(requested_step)] = {
                "current_challenge_id": expected_challenge_id,
                "response": response
            }
        return response


def _build_idempotent_state_response(session: dict) -> dict:
    challenge = session.get("current_challenge")
    return {
        "session_id": session["session_id"],
        "verification_status": session.get("status", "in_progress"),
        "is_step_correct": False,
        "message": "This verification step has already been processed.",
        "explanation": "The current challenge remains active.",
        "current_step": session.get("current_step", 1),
        "total_steps": session.get("total_steps", 1),
        "correct_count": session.get("correct_count", 0),
        "attempts": session.get("attempts", 0),
        "accuracy": session.get("accuracy", 0),
        "required_accuracy": session.get("required_accuracy", 100),
        "consecutive_correct": session.get("consecutive_correct", 0),
        "consecutive_required": session.get("consecutive_required", 1),
        "time_limit": session.get("time_limit", 20),
        "next_challenge": challenge
    }


def _process_verification_step(
    session_id: str,
    user_answer: str,
    time_taken: float,
    is_timeout: bool,
    db: Session,
    user_id: int = 1,
    alarm_id: Optional[int] = None
) -> dict:
    """
    Validates a challenge attempt within an active verification session.
    Applies the specific rules for the 5 verification methods:
    1. Puzzle Completion
    2. Multi-Step Challenge
    3. Consecutive Correct Answers
    4. Time-Based Verification
    5. Cognitive Accuracy Check
    """
    with _session_lock:
        session = ACTIVE_VERIFICATION_SESSIONS.get(session_id)

    if not session:
        # Fallback session if expired or not found
        session = init_verification_session(
            user_id=user_id,
            alarm_id=alarm_id,
            verification_method="puzzle_completion"
        )
        session_id = session["session_id"]

    current_chal = session.get("current_challenge", {})
    method = session.get("verification_method", "puzzle_completion")
    correct_ans = normalize_answer(current_chal.get("answer", ""))
    user_ans = normalize_answer(user_answer)
    explanation = current_chal.get("explanation", "")
    ch_type = current_chal.get("type", "Math Problems")
    diff = normalize_difficulty(current_chal.get("difficulty", "Medium"))
    question_text = current_chal.get("question", "Challenge question")
    attempt_num = len(session.get("history", [])) + 1
    time_limit_val = session.get("time_limit", 20)

    logger.info(
        "Verification step: session_id=%s alarm_id=%s step=%s challenge_id=%s source=%s",
        session_id, session.get("alarm_id"), session.get("current_step"),
        current_chal.get("id"), current_chal.get("source", "unknown")
    )

    # 1. Determine Correctness
    is_step_correct = False
    if is_timeout:
        is_step_correct = False
        step_message = "⏱️ Time expired! Attempt recorded as timed out."
        explanation = explanation or "Time limit reached before answer submission."
    elif user_ans and user_ans == correct_ans:
        is_step_correct = True
        step_message = "✓ Correct answer!"
    else:
        try:
            if user_ans and float(user_ans) == float(correct_ans):
                is_step_correct = True
                step_message = "✓ Correct answer!"
            else:
                step_message = "✗ Incorrect answer."
        except (ValueError, TypeError):
            step_message = "✗ Incorrect answer."

    # 2. Log Attempt in Database
    try:
        status_tag = "timeout" if is_timeout else ("passed" if is_step_correct else "failed")
        attempt_record = ChallengeAttempt(
            user_id=user_id,
            alarm_id=alarm_id or session.get("alarm_id"),
            challenge_type=ch_type,
            difficulty=diff,
            question=question_text[:500],
            correct_answer=correct_ans,
            user_answer=user_answer or "",
            is_correct=is_step_correct,
            attempt_number=attempt_num,
            time_taken=int(time_taken or (time_limit_val if is_timeout else 0)),
            time_limit=time_limit_val,
            verification_status=status_tag,
            session_id=session_id
        )
        db.add(attempt_record)
        db.commit()
        db.refresh(attempt_record)
    except Exception as err:
        logger.error(f"Error logging challenge attempt to DB in verification service: {err}")
        db.rollback()

    # 3. Update Verification Counters & State
    current_step = session.get("current_step", 1)
    total_steps = session.get("total_steps", 1)
    correct_count = session.get("correct_count", 0)
    consecutive_correct = session.get("consecutive_correct", 0)
    consecutive_required = session.get("consecutive_required", 1)
    required_accuracy = session.get("required_accuracy", 100)

    if is_step_correct:
        correct_count += 1
        consecutive_correct += 1
    else:
        # Rule 3 & Rule 4: Incorrect answer or timeout resets the consecutive streak!
        consecutive_correct = 0

    session["correct_count"] = correct_count
    session["attempts"] = session.get("attempts", 0) + 1
    session["accuracy"] = round((correct_count / session["attempts"]) * 100)
    session["consecutive_correct"] = consecutive_correct
    session["history"].append({
        "step": current_step,
        "question": question_text,
        "is_correct": is_step_correct,
        "is_timeout": is_timeout,
        "time_taken": time_taken
    })

    # 4. Apply Verification Rules
    verification_status = "in_progress"
    next_challenge_obj = None

    if method == "puzzle_completion":
        # Rule 1: Single Puzzle Completion
        if is_step_correct:
            verification_status = "passed"
            step_message = "✓ Verification Passed! Wake-up drill complete."
        else:
            verification_status = "timeout" if is_timeout else "failed"
            step_message = f"{'⏱️ Time expired!' if is_timeout else '✗ Incorrect!'} Try this new question:"

    elif method == "consecutive_correct":
        # Rule 3: Consecutive Correct Answers
        if consecutive_correct >= consecutive_required:
            verification_status = "passed"
            step_message = f"✓ Verification Passed! Completed {consecutive_required} consecutive correct answers."
        else:
            verification_status = "timeout" if is_timeout else ("in_progress" if is_step_correct else "failed")
            if is_step_correct:
                step_message = f"✓ Streak: {consecutive_correct}/{consecutive_required} correct! Solve the next question:"
            else:
                step_message = f"{'⏱️ Time expired!' if is_timeout else '✗ Incorrect!'} Streak reset to 0/{consecutive_required}. Solve next:"

    elif method == "multi_step":
        # Rule 2: Multi-Step Challenge (sequential questions)
        if current_step < total_steps:
            current_step += 1
            session["current_step"] = current_step
            verification_status = "in_progress"
            step_message = f"Step {current_step - 1}/{total_steps} complete. Moving to Step {current_step}/{total_steps}:"
        else:
            # All steps completed, check required accuracy
            calc_accuracy = round((correct_count / total_steps) * 100)
            if calc_accuracy >= required_accuracy:
                verification_status = "passed"
                step_message = f"✓ Multi-step verification passed! Accuracy: {correct_count}/{total_steps} ({calc_accuracy}%)."
            else:
                verification_status = "failed"
                step_message = f"✗ Accuracy {correct_count}/{total_steps} ({calc_accuracy}%) was below required {required_accuracy}%. Additional challenge required:"
                # Provide a bonus retry step to allow user to reach required accuracy
                total_steps += 1
                current_step += 1
                session["total_steps"] = total_steps
                session["current_step"] = current_step

    elif method == "accuracy_check":
        # Rule 5: Cognitive Accuracy Check
        if current_step < total_steps:
            current_step += 1
            session["current_step"] = current_step
            verification_status = "in_progress"
            step_message = f"{'✓ Correct!' if is_step_correct else '✗ Incorrect.'} Question {current_step - 1}/{total_steps} recorded. Question {current_step}/{total_steps}:"
        else:
            calc_accuracy = round((correct_count / total_steps) * 100)
            if calc_accuracy >= required_accuracy:
                verification_status = "passed"
                step_message = f"✓ Accuracy verified: {correct_count}/{total_steps} ({calc_accuracy}% >= {required_accuracy}%). Wake-up confirmed!"
            else:
                verification_status = "failed"
                step_message = f"✗ Accuracy {correct_count}/{total_steps} ({calc_accuracy}%) did not meet {required_accuracy}%. Another challenge required:"
                total_steps += 1
                current_step += 1
                session["total_steps"] = total_steps
                session["current_step"] = current_step

    elif method == "time_based":
        # Rule 4: Time-Based Verification
        if is_timeout:
            verification_status = "timeout"
            step_message = "⏱️ Time limit exceeded! Attempt failed. Solve this new challenge within time limit:"
        elif is_step_correct:
            if current_step >= total_steps:
                verification_status = "passed"
                step_message = f"✓ Time-critical verification passed in {int(time_taken)}s!"
            else:
                current_step += 1
                session["current_step"] = current_step
                verification_status = "in_progress"
                step_message = f"✓ Solved in {int(time_taken)}s! Moving to Step {current_step}/{total_steps}:"
        else:
            verification_status = "failed"
            step_message = "✗ Incorrect answer! Try this new challenge:"

    session["status"] = verification_status

    # 5. Generate the next challenge only after this answer was processed.
    if verification_status != "passed":
        # Step down difficulty if user got question wrong / timeout
        next_diff = step_difficulty(diff, -1) if not is_step_correct else diff
        norm_type = map_challenge_type(ch_type)
        try:
            previous_questions = {
                item.get("question")
                for item in session.get("history", [])
                if item.get("question")
            }
            previous_questions.add(question_text)
            next_data = _generate_distinct_challenge(norm_type, next_diff, previous_questions)
            next_chal_id = f"chal_{uuid.uuid4().hex[:12]}"
            next_data["id"] = next_chal_id
            next_data["user_id"] = user_id
            next_data["recommended_difficulty"] = next_diff
            next_data["recommended_challenge_type"] = ch_type
            next_data["alarm_id"] = alarm_id or session.get("alarm_id")
            next_data["time_limit"] = time_limit_val
            next_data["source"] = "verification_step"
            next_data["scheduler_generated"] = False
            add_session(next_chal_id, next_data)
            session["current_challenge"] = next_data
            next_challenge_obj = next_data
            logger.info(
                "Verification challenge generated: session_id=%s alarm_id=%s step=%s challenge_id=%s source=verification_step",
                session_id, session.get("alarm_id"), session.get("current_step"), next_chal_id
            )
        except Exception as e:
            logger.error(f"Error generating next challenge in verification service: {e}")
    else:
        # Keep the verification session so duplicate final requests are replayed.
        if current_chal.get("id"):
            remove_session(current_chal["id"]) 

    return {
        "session_id": session_id,
        "verification_status": verification_status,
        "is_step_correct": is_step_correct,
        "message": step_message,
        "explanation": explanation,
        "current_step": current_step,
        "total_steps": total_steps,
        "correct_count": correct_count,
        "attempts": session.get("attempts", 0),
        "accuracy": session.get("accuracy", 0),
        "required_accuracy": required_accuracy,
        "consecutive_correct": consecutive_correct,
        "consecutive_required": consecutive_required,
        "time_limit": time_limit_val,
        "next_challenge": next_challenge_obj
    }
