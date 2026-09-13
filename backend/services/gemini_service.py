import os
import json
import logging
import requests
from typing import Optional, Dict, Any, List
from config import settings
from services.fallback_challenges import get_fallback_challenge
from services.personalization_service import normalize_difficulty, get_time_limit_for_difficulty

logger = logging.getLogger(__name__)

ALLOWED_TYPES = [
    "Math Problems",
    "Logic Puzzles",
    "Memory Challenges",
    "Word Games",
    "Pattern Recognition",
    "Riddles",
    "Quick Quizzes"
]

ALLOWED_DIFFICULTIES = ["Beginner", "Easy", "Medium", "Hard", "Expert"]

def map_challenge_type(input_type: str) -> str:
    """Normalize input challenge types or shortcuts to standard types."""
    if not input_type:
        return "Math Problems"
    
    mapping = {
        "math": "Math Problems",
        "logic": "Logic Puzzles",
        "memory": "Memory Challenges",
        "word": "Word Games",
        "pattern": "Pattern Recognition",
        "riddle": "Riddles",
        "quiz": "Quick Quizzes",
        "tap": "Logic Puzzles",
        "none": "Math Problems"
    }
    
    val = input_type.strip()
    if val in ALLOWED_TYPES:
        return val
    
    lower_val = val.lower()
    if lower_val in mapping:
        return mapping[lower_val]
    
    for allowed in ALLOWED_TYPES:
        if allowed.lower() in lower_val or lower_val in allowed.lower():
            return allowed
            
    return "Math Problems"

def build_gemini_prompt(challenge_type: str, difficulty: str) -> str:
    """
    Constructs a strong prompt for Gemini to generate a wake-up cognitive challenge.
    """
    normalized_diff = normalize_difficulty(difficulty)
    difficulty_instructions = {
        "Beginner": "Very gentle, basic calculations, simple direct questions, or 2-item memory tasks for gentle morning wakeups.",
        "Easy": "Simple calculations, basic patterns, direct riddles, or simple memory tasks that kickstart alertness.",
        "Medium": "Multi-step reasoning, moderate arithmetic, complex word/pattern matching, or multi-item memory tasks.",
        "Hard": "Challenging multi-step logic, complex math equations, deep pattern recognition, or multi-element recall.",
        "Expert": "Rapid, high-intensity cognitive arousal drills, advanced algebra/logic, multi-layered memory recall."
    }

    diff_desc = difficulty_instructions.get(normalized_diff, difficulty_instructions["Medium"])

    prompt = f"""
You are an AI Cognitive Engine for WakeWise AI, an intelligent alarm platform.
Your task is to generate ONE single WAKE-UP cognitive challenge to help a user wake up and overcome sleep inertia.

Requirements:
- Challenge Type: {challenge_type}
- Difficulty Level: {normalized_diff} ({diff_desc})
- The question must be unambiguous, clear, appropriate for waking up, and have exactly ONE correct answer.
- Do NOT generate offensive, impossible, or trick questions.
- Provide 4 multiple-choice options in the "options" array whenever suitable (e.g. for Math, Logic, Quizzes, Patterns, Word Games, Memory). Make sure the exact correct answer is included in the options list!
- For open-ended riddles where options aren't necessary, "options" can be an empty array [].
- For Memory Challenges: Include the items to be memorized clearly inside the question (e.g., "Memorize this list: APPLE, RIVER, CLOCK, MOUNTAIN, GUITAR. What was the 3rd item?").

You MUST return strictly a JSON object with NO markdown wrapping, matching this exact schema:
{{
    "type": "{challenge_type}",
    "difficulty": "{normalized_diff}",
    "question": "<string>",
    "options": ["<option1>", "<option2>", "<option3>", "<option4>"],
    "answer": "<string exact match of the correct answer or choice>",
    "explanation": "<short clear explanation of the solution>"
}}
"""
    return prompt.strip()

def generate_cognitive_challenge(
    challenge_type: str,
    difficulty: str,
    preferred_provider: Optional[str] = None
) -> dict:
    """
    Multi-Provider AI Cognitive Challenge Generator.
    Orchestrates Groq API (ultra-fast sub-second latency) + Gemini API + Local Fallback.
    Instruments latency and outcome to PerformanceMetricsCollector.
    """
    import time
    from services.metrics_collector import metrics_collector
    from services.groq_service import generate_groq_challenge

    t_start = time.perf_counter()
    normalized_type = map_challenge_type(challenge_type)
    normalized_diff = normalize_difficulty(difficulty)

    provider_setting = (preferred_provider or settings.AI_PROVIDER or os.getenv("AI_PROVIDER", "auto")).lower()
    groq_api_key = settings.GROQ_API_KEY or os.getenv("GROQ_API_KEY", "")
    gemini_api_key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")

    # 1. Try Gemini API first
    if provider_setting in ("auto", "gemini") and gemini_api_key and gemini_api_key.strip():
        gemini_challenge = _generate_gemini_challenge(normalized_type, normalized_diff, gemini_api_key.strip())
        if gemini_challenge:
            duration_ms = (time.perf_counter() - t_start) * 1000
            metrics_collector.record_challenge_generation(
                challenge_type=normalized_type,
                difficulty=normalized_diff,
                provider=gemini_challenge.get("ai_provider", "Gemini"),
                duration_ms=duration_ms,
                success=True,
                is_fallback=False
            )
            return gemini_challenge
        logger.warning("Gemini API generation failed or unavailable. Falling back to Groq API...")

    # 2. Try Groq API if Gemini fails or if Groq is preferred
    if provider_setting in ("auto", "groq", "gemini") and groq_api_key and groq_api_key.strip():
        try:
            groq_challenge = generate_groq_challenge(normalized_type, normalized_diff, groq_api_key.strip())
            if groq_challenge:
                duration_ms = (time.perf_counter() - t_start) * 1000
                metrics_collector.record_challenge_generation(
                    challenge_type=normalized_type,
                    difficulty=normalized_diff,
                    provider="Groq",
                    duration_ms=duration_ms,
                    success=True,
                    is_fallback=(provider_setting == "gemini")
                )
                logger.info(f"Groq API successfully generated challenge for '{normalized_type}' ({normalized_diff}) as primary/fallback!")
                return groq_challenge
            logger.warning("Groq API fallback did not return a challenge. Using local fallback.")
        except Exception as e:
            logger.warning(f"Groq API challenge generation error: {e}")

    # 3. Fallback to high-quality curated local challenges
    duration_ms = (time.perf_counter() - t_start) * 1000
    logger.info(f"Serving instant local cognitive challenge for '{normalized_type}' ({normalized_diff}).")
    local_challenge = get_fallback_challenge(normalized_type, normalized_diff)
    local_challenge["ai_provider"] = "Local Cognitive Engine"
    metrics_collector.record_challenge_generation(
        challenge_type=normalized_type,
        difficulty=normalized_diff,
        provider="Local Cognitive Engine",
        duration_ms=duration_ms,
        success=True,
        is_fallback=True
    )
    return local_challenge


def _generate_gemini_challenge(normalized_type: str, normalized_diff: str, api_key: str) -> Optional[dict]:
    """Internal helper to call Google Gemini API with fallback models."""
    prompt = build_gemini_prompt(normalized_type, normalized_diff)
    models_to_try = ["gemini-2.5-flash", "gemini-flash-latest"]

    for model_name in models_to_try:
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.7
            }
        }

        try:
            res = requests.post(endpoint, json=payload, timeout=8.0)
            if res.status_code == 200:
                res_data = res.json()
                candidates = res_data.get("candidates", [])
                if not candidates:
                    continue

                content_parts = candidates[0].get("content", {}).get("parts", [])
                if not content_parts:
                    continue

                raw_text = content_parts[0].get("text", "").strip()

                # Clean markdown fences
                if raw_text.startswith("```json"):
                    raw_text = raw_text[7:]
                if raw_text.startswith("```"):
                    raw_text = raw_text[3:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]
                raw_text = raw_text.strip()

                challenge_obj = json.loads(raw_text)

                required_keys = ["type", "difficulty", "question", "options", "answer", "explanation"]
                if not all(k in challenge_obj for k in required_keys):
                    continue

                challenge_obj["type"] = normalized_type
                challenge_obj["difficulty"] = normalized_diff
                if not isinstance(challenge_obj.get("options"), list):
                    challenge_obj["options"] = []

                challenge_obj["answer"] = str(challenge_obj["answer"]).strip()
                challenge_obj["explanation"] = str(challenge_obj["explanation"]).strip()
                challenge_obj["time_limit"] = get_time_limit_for_difficulty(normalized_diff)
                challenge_obj["ai_provider"] = f"Gemini ({model_name})"

                logger.info(f"Gemini API model '{model_name}' successfully generated dynamic AI challenge!")
                return challenge_obj

            else:
                logger.warning(f"Gemini API model '{model_name}' returned status {res.status_code}: {res.text[:200]}")

        except Exception as e:
            logger.warning(f"Gemini API model '{model_name}' connection issue: {e}")
            continue

    return None
