import uuid
import logging
from typing import Dict, Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database import get_db
from models import ChallengeAttempt, User, Alarm
from routes.auth import get_current_user
from services.gemini_service import (
    ALLOWED_TYPES,
    ALLOWED_DIFFICULTIES as DIFFICULTY_LEVELS,
    map_challenge_type,
    generate_cognitive_challenge
)
from services.personalization_service import (
    normalize_difficulty,
    get_time_limit_for_difficulty,
    get_adaptive_recommendation,
    calculate_user_cognitive_metrics,
    get_next_attempt_difficulty
)
from services.verification_service import (
    VERIFICATION_METHODS,
    init_verification_session,
    process_verification_step,
    get_verification_session,
    remove_verification_session,
    normalize_answer
)
from services.challenge_store import find_session_by_alarm
from schemas import (
    ChallengeTypesResponse,
    ChallengeResponse,
    ChallengeValidateRequest,
    ChallengeValidateResponse,
    ChallengeAttemptResponse,
    UserPerformanceResponse,
    VerificationStartRequest,
    VerificationSessionState,
    VerificationStepRequest,
    VerificationStepResponse
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/challenges", tags=["Cognitive Challenges"])

oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)

def get_optional_user(token: Optional[str] = Depends(oauth2_scheme_optional), db: Session = Depends(get_db)) -> Optional[User]:
    if not token:
        return None
    try:
        return get_current_user(token=token, db=db)
    except Exception:
        return None

@router.get("/types", response_model=ChallengeTypesResponse)
def get_challenge_types():
    """
    Returns supported cognitive challenge types, difficulty levels, and wake-up verification methods.
    """
    return ChallengeTypesResponse(
        challenge_types=ALLOWED_TYPES,
        difficulty_levels=DIFFICULTY_LEVELS,
        verification_methods=VERIFICATION_METHODS
    )

@router.get("/providers")
def get_ai_providers():
    """
    Returns configured AI challenge generation providers (Groq, Gemini, Local).
    """
    groq_configured = bool(settings.GROQ_API_KEY and settings.GROQ_API_KEY.strip())
    gemini_configured = bool(settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip())
    return {
        "active_mode": settings.AI_PROVIDER,
        "providers": [
            {
                "id": "groq",
                "name": "Groq LPU (Ultra-Fast)",
                "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
                "is_configured": groq_configured,
                "latency": "< 500ms"
            },
            {
                "id": "gemini",
                "name": "Google Gemini",
                "models": ["gemini-2.5-flash", "gemini-flash-latest"],
                "is_configured": gemini_configured,
                "latency": "1-2s"
            },
            {
                "id": "local",
                "name": "Local Cognitive Engine",
                "models": ["Curated WakeWise Drills"],
                "is_configured": True,
                "latency": "Instant (0ms)"
            }
        ]
    }

@router.post("/verification/start", response_model=VerificationSessionState)
def start_verification_session(
    payload: VerificationStartRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user)
):
    """
    Initializes a new Wake-Up Verification Session according to alarm rules or custom parameters.
    """
    user_id = current_user.id if current_user else 1
    alarm_obj = None
    if payload.alarm_id:
        alarm_obj = db.query(Alarm).filter(Alarm.id == payload.alarm_id).first()

    scheduler_challenge = payload.first_challenge.model_dump() if payload.first_challenge else None
    if not scheduler_challenge and payload.alarm_id:
        scheduler_challenge = find_session_by_alarm(payload.alarm_id, alarm_obj.user_id if alarm_obj else user_id)

    session_data = init_verification_session(
        alarm=alarm_obj,
        user_id=user_id,
        challenge_type=payload.challenge_type or "Math Problems",
        difficulty=payload.difficulty or "Medium",
        verification_method=payload.verification_method or "puzzle_completion",
        verification_steps=payload.verification_steps or 1,
        required_accuracy=payload.required_accuracy or 100,
        consecutive_required=payload.consecutive_required or 1,
        time_limit=payload.time_limit or 20,
        first_challenge=scheduler_challenge,
        alarm_id=payload.alarm_id
    )

    chal = session_data.get("current_challenge")
    chal_obj = ChallengeResponse(**chal) if chal else None

    return VerificationSessionState(
        session_id=session_data["session_id"],
        alarm_id=session_data.get("alarm_id"),
        verification_method=session_data["verification_method"],
        status=session_data["status"],
        current_step=session_data["current_step"],
        total_steps=session_data["total_steps"],
        correct_count=session_data["correct_count"],
        attempts=session_data.get("attempts", 0),
        accuracy=session_data.get("accuracy", 0),
        required_accuracy=session_data["required_accuracy"],
        consecutive_correct=session_data["consecutive_correct"],
        consecutive_required=session_data["consecutive_required"],
        time_limit=session_data["time_limit"],
        current_challenge=chal_obj
    )

@router.post("/verification/step", response_model=VerificationStepResponse)
def handle_verification_step(
    payload: VerificationStepRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user)
):
    """
    Processes a step in an active verification session, logs attempt, applies rules, and advances sequence.
    """
    user_id = current_user.id if current_user else 1
    result = process_verification_step(
        session_id=payload.session_id,
        user_answer=payload.user_answer,
        time_taken=payload.time_taken,
        is_timeout=payload.is_timeout,
        db=db,
        user_id=user_id,
        alarm_id=payload.alarm_id,
        step_number=payload.step_number,
        challenge_id=payload.challenge_id
    )

    next_chal = result.get("next_challenge")
    next_chal_obj = ChallengeResponse(**next_chal) if next_chal else None

    return VerificationStepResponse(
        session_id=result["session_id"],
        verification_status=result["verification_status"],
        is_step_correct=result["is_step_correct"],
        message=result["message"],
        explanation=result["explanation"],
        current_step=result["current_step"],
        total_steps=result["total_steps"],
        correct_count=result["correct_count"],
        attempts=result.get("attempts", 0),
        accuracy=result.get("accuracy", 0),
        required_accuracy=result["required_accuracy"],
        consecutive_correct=result["consecutive_correct"],
        consecutive_required=result["consecutive_required"],
        time_limit=result["time_limit"],
        next_challenge=next_chal_obj
    )

@router.get("/generate", response_model=ChallengeResponse)
def generate_challenge(
    challenge_type: str = Query(..., description="Challenge type (e.g. Math Problems, Logic Puzzles, etc.)"),
    difficulty: Optional[str] = Query(None, description="Difficulty level (Beginner, Easy, Medium, Hard, Expert)"),
    alarm_id: Optional[int] = Query(None, description="Associated Alarm ID"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user)
):
    """
    Generates a dynamic cognitive challenge via Gemini API (or local fallback).
    Applies user personalization if authenticated, assigns time limit based on difficulty, and returns challenge structure.
    """
    valid_raw_types = {t.lower() for t in ALLOWED_TYPES} | {"math", "logic", "memory", "word", "pattern", "riddle", "quiz", "tap", "none"}
    
    if not challenge_type or challenge_type.strip().lower() not in valid_raw_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid challenge_type '{challenge_type}'. Must be one of: {', '.join(ALLOWED_TYPES)}"
        )

    base_diff = normalize_difficulty(difficulty) if difficulty else "Medium"
    adaptive_reason = None
    pref_type = challenge_type

    # 1. Personalization: If caller explicitly provided difficulty, honor it.
    #    Otherwise, compute personalized recommendation from Adaptive Engine.
    if current_user:
        rec = get_adaptive_recommendation(
            db=db,
            user_id=current_user.id,
            base_difficulty=base_diff,
            preferred_type=challenge_type
        )
        recommended_diff = rec["recommended_difficulty"] if not difficulty else base_diff
        pref_type = rec["recommended_challenge_type"] if challenge_type.lower() in ("none", "") else challenge_type
        adaptive_reason = rec["reason"]
    else:
        recommended_diff = base_diff
        adaptive_reason = f"Standard baseline difficulty: {recommended_diff}."

    normalized_type = map_challenge_type(pref_type)

    # 2. If this request is for an alarm and an active session already exists, return it.
    if alarm_id:
        if current_user:
            existing = find_session_by_alarm(alarm_id, current_user.id)
            if existing:
                return ChallengeResponse(**existing)
        else:
            try:
                alarm_obj = db.query(Alarm).filter(Alarm.id == alarm_id).first()
                if alarm_obj:
                    existing = find_session_by_alarm(alarm_id, alarm_obj.user_id)
                    if existing:
                        return ChallengeResponse(**existing)
            except Exception:
                logger.debug("Could not resolve alarm owner for alarm_id lookup")

    # 3. Call Gemini Service (or local fallback)
    challenge_data = generate_cognitive_challenge(normalized_type, recommended_diff)

    # 4. Generate session ID and store server-side
    session_id = f"chal_{uuid.uuid4().hex[:12]}"
    challenge_data["id"] = session_id
    challenge_data["recommended_difficulty"] = recommended_diff
    challenge_data["recommended_challenge_type"] = pref_type
    challenge_data["adaptive_reason"] = adaptive_reason
    challenge_data["alarm_id"] = alarm_id
    challenge_data["time_limit"] = get_time_limit_for_difficulty(recommended_diff)

    # Persist session in central store
    add_session(session_id, challenge_data)

    return ChallengeResponse(**challenge_data)
    

@router.post("/validate", response_model=ChallengeValidateResponse)
def validate_challenge(
    payload: ChallengeValidateRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user)
):
    """
    Validates user's challenge answer or handles timeout, records attempt in DB, and applies verification rules.
    """
    user_ans = normalize_answer(payload.user_answer)
    correct_ans = ""
    explanation = ""
    ch_type = payload.challenge_type or "Math Problems"
    diff = normalize_difficulty(payload.difficulty or "Medium")
    question_text = payload.question or "Challenge question"

    # 1. Lookup session details if session ID is provided (user-scoped)
    session_data = None
    if payload.challenge_id:
        session_data = get_challenge_session(payload.challenge_id)
        if session_data:
            sess_user = session_data.get("user_id")
            if current_user:
                if sess_user != current_user.id:
                    session_data = None
            else:
                if sess_user != 1:
                    session_data = None

    if session_data:
        correct_ans = normalize_answer(session_data.get("answer", ""))
        explanation = session_data.get("explanation", "")
        ch_type = session_data.get("type", ch_type)
        diff = normalize_difficulty(session_data.get("difficulty", diff))
        question_text = session_data.get("question", question_text)
    elif payload.correct_answer:
        correct_ans = normalize_answer(payload.correct_answer)
        explanation = "The correct answer matched."

    # 2. Check correctness / timeout
    is_correct = False
    if payload.is_timeout:
        is_correct = False
        msg = "⏱️ Time expired! Attempt recorded as timed out."
        explanation = explanation or "Time limit reached before answer submission."
    elif user_ans and user_ans == correct_ans:
        is_correct = True
        msg = "✓ Correct! Challenge completed."
    else:
        try:
            if user_ans and float(user_ans) == float(correct_ans):
                is_correct = True
                msg = "✓ Correct! Challenge completed."
            else:
                msg = "✗ Incorrect answer. Try again!"
        except (ValueError, TypeError):
            msg = "✗ Incorrect answer. Try again!"

    # 3. Verification State Computation
    method = (payload.verification_method or "puzzle_completion").lower()
    current_step = payload.current_step or 1
    total_steps = payload.total_steps or 1
    correct_count = (payload.correct_count or 0) + (1 if is_correct else 0)
    consecutive_required = payload.consecutive_required or 1
    required_accuracy = payload.required_accuracy or 100
    
    if is_correct:
        consecutive_correct = (payload.consecutive_correct or 0) + 1
    else:
        consecutive_correct = 0 # Streak resets to 0 on failure/timeout

    verification_status = "in_progress"
    if method == "puzzle_completion":
        verification_status = "passed" if is_correct else ("timeout" if payload.is_timeout else "failed")
    elif method == "consecutive_correct":
        if consecutive_correct >= consecutive_required:
            verification_status = "passed"
            msg = f"✓ Verification Passed! Reached {consecutive_required} consecutive correct answers."
        else:
            verification_status = "timeout" if payload.is_timeout else ("in_progress" if is_correct else "failed")
            msg = f"{'✓ Correct!' if is_correct else '✗ Incorrect!'} Consecutive streak: {consecutive_correct}/{consecutive_required}."
    elif method in ("multi_step", "accuracy_check"):
        if current_step < total_steps:
            current_step += 1
            verification_status = "in_progress"
            msg = f"{'✓ Correct!' if is_correct else '✗ Incorrect!'} Step {current_step - 1}/{total_steps} complete. Moving to Step {current_step}/{total_steps}."
        else:
            calc_acc = round((correct_count / total_steps) * 100)
            if calc_acc >= required_accuracy:
                verification_status = "passed"
                msg = f"✓ Wake-up verified! Accuracy: {correct_count}/{total_steps} ({calc_acc}% >= {required_accuracy}%)."
            else:
                verification_status = "failed"
                msg = f"✗ Accuracy {correct_count}/{total_steps} ({calc_acc}%) below required {required_accuracy}%. Additional question required:"
                total_steps += 1
                current_step += 1
    elif method == "time_based":
        if payload.is_timeout:
            verification_status = "timeout"
            msg = "⏱️ Time expired! Attempt recorded as timed out. Try again within time limit:"
        elif is_correct:
            if current_step >= total_steps:
                verification_status = "passed"
                msg = "✓ Verification Passed within time limit!"
            else:
                current_step += 1
                verification_status = "in_progress"
        else:
            verification_status = "failed"
            msg = "✗ Incorrect answer! Try again within time limit:"

    # 4. Record attempt in Database
    user_id = current_user.id if current_user else 1
    attempt_num = payload.attempt_number or 1
    time_limit_val = payload.time_limit or get_time_limit_for_difficulty(diff)
    time_taken_val = int(payload.time_taken or 0)

    try:
        attempt_record = ChallengeAttempt(
            user_id=user_id,
            alarm_id=payload.alarm_id,
            challenge_type=ch_type,
            difficulty=diff,
            question=question_text[:500],
            correct_answer=correct_ans or payload.correct_answer or "",
            user_answer=payload.user_answer or "",
            is_correct=is_correct,
            attempt_number=attempt_num,
            time_taken=time_taken_val,
            time_limit=time_limit_val,
            verification_status=verification_status,
            session_id=payload.challenge_id
        )
        db.add(attempt_record)
        db.commit()
        db.refresh(attempt_record)
    except Exception as err:
        logger.error(f"Error logging challenge attempt to database: {err}")
        db.rollback()

    # 5. Determine adaptive recommendation and next challenge if not passed
    rec = get_adaptive_recommendation(db=db, user_id=user_id, base_difficulty=diff, preferred_type=ch_type)
    next_challenge_obj = None

    if verification_status != "passed":
        # Step down difficulty on incorrect/timeout if appropriate
        new_diff = step_difficulty(diff, -1) if not is_correct else diff
        normalized_type = map_challenge_type(ch_type)

        try:
            new_data = generate_cognitive_challenge(normalized_type, new_diff)
            session_id = f"chal_{uuid.uuid4().hex[:12]}"
            new_data["id"] = session_id
            new_data["user_id"] = user_id
            new_data["recommended_difficulty"] = new_diff
            new_data["recommended_challenge_type"] = ch_type
            new_data["adaptive_reason"] = rec["reason"]
            new_data["alarm_id"] = payload.alarm_id
            new_data["time_limit"] = time_limit_val
            add_session(session_id, new_data)
            next_challenge_obj = ChallengeResponse(**new_data)
        except Exception as e:
            logger.error(f"Error generating challenge: {e}")

        next_diff = new_diff
    else:
        next_diff = rec["recommended_difficulty"]

    # 6. If completed successfully, clean up session
    if verification_status == "passed" and payload.challenge_id:
        try:
            remove_challenge_session(payload.challenge_id)
            try:
                import scheduler
                scheduler.triggered_alarms = [t for t in scheduler.triggered_alarms if not (t.get("challenge", {}).get("id") == payload.challenge_id or t.get("id") == payload.alarm_id)]
            except Exception:
                logger.debug("Could not prune scheduler.triggered_alarms or scheduler not loaded")
        except Exception as e:
            logger.error(f"Error removing challenge session {payload.challenge_id}: {e}")

    return ChallengeValidateResponse(
        correct=is_correct,
        message=msg,
        explanation=explanation or "Double check your response and try again.",
        attempt_number=attempt_num,
        verification_status=verification_status,
        current_step=current_step,
        total_steps=total_steps,
        correct_count=correct_count,
        required_accuracy=required_accuracy,
        consecutive_correct=consecutive_correct,
        consecutive_required=consecutive_required,
        next_recommended_difficulty=next_diff,
        next_recommended_type=rec["recommended_challenge_type"],
        adaptive_reason=rec["reason"],
        next_challenge=next_challenge_obj
    )

@router.get("/performance", response_model=UserPerformanceResponse)
def get_user_performance(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieves user's historical cognitive challenge performance and recent attempts.
    """
    attempts = (
        db.query(ChallengeAttempt)
        .filter(ChallengeAttempt.user_id == current_user.id)
        .order_by(desc(ChallengeAttempt.created_at))
        .all()
    )

    rec = get_adaptive_recommendation(db, current_user.id, "Medium")
    analysis = rec["analysis"]

    total_attempts = analysis["total_attempts"]
    total_passed = analysis["passed_attempts"]
    accuracy_percentage = analysis["overall_accuracy"]
    avg_time = analysis["avg_time_taken"]

    return UserPerformanceResponse(
        user_id=current_user.id,
        total_attempts=total_attempts,
        total_passed=total_passed,
        accuracy_percentage=accuracy_percentage,
        average_time_taken=avg_time,
        recommended_difficulty=rec["recommended_difficulty"],
        preferred_challenge_type=rec["recommended_challenge_type"],
        reason=rec["reason"],
        score=analysis.get("score", 50.0),
        trend=analysis.get("trend", "stable"),
        strong_types=analysis.get("strong_types", []),
        weak_types=analysis.get("weak_types", []),
        type_breakdown=analysis.get("type_breakdown", {}),
        recent_attempts=[ChallengeAttemptResponse.model_validate(a) for a in attempts[:10]]
    )

