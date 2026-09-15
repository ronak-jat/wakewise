from datetime import datetime
from typing import Optional, List, Dict, Any
import re
from pydantic import BaseModel, EmailStr, Field, field_validator


class UserRegister(BaseModel):
    name: str = Field(..., example="John", description="User Name")
    email: EmailStr = Field(..., example="john@gmail.com", description="Unique Email Address")
    password: str = Field(..., min_length=6, example="Password@123", description="User Password")
    role: str = Field(default="USER", example="USER", description="User Role (USER, Wellness Coach, Administrator)")
    provider: Optional[str] = Field(default="LOCAL", example="LOCAL", description="Authentication provider (LOCAL or GOOGLE)")

class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str
    provider: str
    target_bedtime: Optional[str] = None
    target_wake_time: Optional[str] = None
    phone_number: Optional[str] = None
    inactivity_threshold_minutes: Optional[int] = 30
    last_meaningful_activity_at: Optional[datetime] = None
    estimated_sleep_start: Optional[datetime] = None
    estimated_sleep_end: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    habit_score: Optional[float] = None
    sleep_quality_score: Optional[float] = None
    habit_breakdown: Optional[Dict[str, float]] = None

    class Config:
        from_attributes = True

class UserProfileUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    target_bedtime: Optional[str] = None
    target_wake_time: Optional[str] = None
    inactivity_threshold_minutes: Optional[int] = None

class RegisterSuccessResponse(BaseModel):
    status: str = "success"
    message: str = "User registered successfully"
    data: UserResponse

class UserLogin(BaseModel):
    email: EmailStr = Field(..., example="john@gmail.com")
    password: str = Field(..., example="Password@123")

class GoogleOAuthRequest(BaseModel):
    token: Optional[str] = Field(None, description="Google OAuth ID Token or Credential String")
    email: Optional[EmailStr] = Field(None, description="Google Account Email")
    name: Optional[str] = Field(None, description="Google Account Full Name")
    role: Optional[str] = Field(default="USER", description="User Role")

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class TokenData(BaseModel):
    email: Optional[str] = None

class AlarmBase(BaseModel):
    title: str = Field(..., max_length=100)
    alarm_time: str = Field(..., description="Trigger time in 24H format (HH:MM)")
    alarm_type: str = Field(default="One-Time", description="Alarm schedule type")
    repeat_days: str = Field(default="", description="Comma-separated repeat days (e.g. 'Mon,Tue')")
    is_active: bool = Field(default=True)
    challenge: str = Field(default="None")
    difficulty_level: str = Field(default="Medium")
    sound: str = Field(default="Radar")
    vibration: str = Field(default="Standard")
    snooze_duration: int = Field(default=5, ge=1, le=120, description="Snooze duration in minutes")
    max_snoozes: int = Field(default=3, ge=0, le=20, description="Maximum snoozes per alarm occurrence")
    # Wake-Up Verification Settings
    verification_method: str = Field(default="multi_step", description="Verification rule: multi_step, puzzle_completion, consecutive_correct, time_based, accuracy_check")
    verification_steps: int = Field(default=3, ge=1, le=10, description="Total questions required in multi-step verification")
    required_accuracy: int = Field(default=67, ge=1, le=100, description="Minimum percentage accuracy required to pass")
    consecutive_required: int = Field(default=2, ge=1, le=10, description="Consecutive correct answers required")
    time_limit: int = Field(default=20, ge=5, le=120, description="Time limit per challenge in seconds")

    @field_validator("alarm_time")
    @classmethod
    def validate_time_format(cls, v):
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v):
            raise ValueError("alarm_time must be in 24-hour HH:MM format")
        return v

    @field_validator("alarm_type")
    @classmethod
    def validate_type(cls, v):
        valid_types = {"Daily", "Weekday", "Weekdays", "Weekend", "Weekends", "One-Time", "Custom", "Smart Adaptive"}
        if v not in valid_types:
            raise ValueError(f"alarm_type must be one of {valid_types}")
        return v

    @field_validator("difficulty_level")
    @classmethod
    def validate_difficulty(cls, v):
        if v is None:
            return v
        normalized = v.title().strip()
        alias_map = {
            "Beginner": "Beginner",
            "Easy": "Easy",
            "Medium": "Medium",
            "Hard": "Hard",
            "Difficult": "Hard",
            "Expert": "Expert",
            "Advanced": "Expert"
        }
        if normalized not in alias_map:
            raise ValueError(f"difficulty_level must be one of {list(alias_map.keys())}")
        return alias_map[normalized]

    @field_validator("verification_method")
    @classmethod
    def validate_verification_method(cls, v):
        valid_methods = {"puzzle_completion", "multi_step", "consecutive_correct", "time_based", "accuracy_check"}
        if v and v.lower() not in valid_methods:
            return "puzzle_completion"
        return v.lower() if v else "puzzle_completion"

class AlarmCreate(AlarmBase):
    pass

class AlarmUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=100)
    alarm_time: Optional[str] = None
    alarm_type: Optional[str] = None
    repeat_days: Optional[str] = None
    is_active: Optional[bool] = None
    challenge: Optional[str] = None
    difficulty_level: Optional[str] = None
    sound: Optional[str] = None
    vibration: Optional[str] = None
    snooze_duration: Optional[int] = None
    max_snoozes: Optional[int] = None
    verification_method: Optional[str] = None
    verification_steps: Optional[int] = None
    required_accuracy: Optional[int] = None
    consecutive_required: Optional[int] = None
    time_limit: Optional[int] = None

    @field_validator("alarm_time")
    @classmethod
    def validate_time_format(cls, v):
        if v is not None and not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v):
            raise ValueError("alarm_time must be in 24-hour HH:MM format")
        return v

    @field_validator("alarm_type")
    @classmethod
    def validate_type(cls, v):
        if v is not None:
            valid_types = {"Daily", "Weekday", "Weekdays", "Weekend", "Weekends", "One-Time", "Custom", "Smart Adaptive"}
            if v not in valid_types:
                raise ValueError(f"alarm_type must be one of {valid_types}")
        return v

    @field_validator("difficulty_level")
    @classmethod
    def validate_difficulty(cls, v):
        if v is not None:
            normalized = v.title().strip()
            alias_map = {
                "Beginner": "Beginner",
                "Easy": "Easy",
                "Medium": "Medium",
                "Hard": "Hard",
                "Difficult": "Hard",
                "Expert": "Expert",
                "Advanced": "Expert"
            }
            if normalized not in alias_map:
                raise ValueError(f"difficulty_level must be one of {list(alias_map.keys())}")
            return alias_map[normalized]
        return v

    @field_validator("verification_method")
    @classmethod
    def validate_verification_method(cls, v):
        if v is not None:
            valid_methods = {"puzzle_completion", "multi_step", "consecutive_correct", "time_based", "accuracy_check"}
            if v.lower() not in valid_methods:
                return "puzzle_completion"
            return v.lower()
        return v

class AlarmResponse(AlarmBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class CheckNextRequest(BaseModel):
    base_time: Optional[datetime] = None

class CheckNextResponse(BaseModel):
    next_alarm: Optional[AlarmResponse] = None
    next_trigger: Optional[datetime] = None
    time_remaining_seconds: Optional[float] = None


# Cognitive Challenge Schemas
class ChallengeTypesResponse(BaseModel):
    challenge_types: List[str]
    difficulty_levels: List[str]
    verification_methods: List[Dict[str, str]] = []

class ChallengeResponse(BaseModel):
    id: Optional[str] = None
    type: str
    difficulty: str
    question: str
    options: List[str] = []
    answer: Optional[str] = None
    explanation: str
    time_limit: int = 20
    recommended_difficulty: Optional[str] = None
    recommended_challenge_type: Optional[str] = None
    adaptive_reason: Optional[str] = None
    alarm_id: Optional[int] = None
    ai_provider: Optional[str] = None
    source: Optional[str] = None
    scheduler_generated: Optional[bool] = None

class ChallengeValidateRequest(BaseModel):
    challenge_id: Optional[str] = None
    user_answer: str = ""
    correct_answer: Optional[str] = None
    challenge_type: Optional[str] = None
    difficulty: Optional[str] = None
    question: Optional[str] = None
    alarm_id: Optional[int] = None
    attempt_number: Optional[int] = 1
    time_taken: Optional[float] = 0.0
    time_limit: Optional[int] = 20
    is_timeout: Optional[bool] = False
    verification_method: Optional[str] = "puzzle_completion"
    current_step: Optional[int] = 1
    total_steps: Optional[int] = 1
    correct_count: Optional[int] = 0
    required_accuracy: Optional[int] = 100
    consecutive_correct: Optional[int] = 0
    consecutive_required: Optional[int] = 1

class ChallengeValidateResponse(BaseModel):
    correct: bool
    message: str
    explanation: str
    attempt_number: int = 1
    verification_status: str = "passed" # pending, in_progress, passed, failed, timeout
    current_step: int = 1
    total_steps: int = 1
    correct_count: int = 1
    required_accuracy: int = 100
    consecutive_correct: int = 1
    consecutive_required: int = 1
    time_remaining: Optional[int] = None
    next_recommended_difficulty: Optional[str] = None
    next_recommended_type: Optional[str] = None
    adaptive_reason: Optional[str] = None
    next_challenge: Optional[ChallengeResponse] = None

class ChallengeAttemptResponse(BaseModel):
    id: int
    user_id: int
    alarm_id: Optional[int] = None
    challenge_type: str
    difficulty: str
    question: str
    correct_answer: str
    user_answer: str
    is_correct: bool
    attempt_number: int
    time_taken: float
    time_limit: int
    verification_status: Optional[str] = "in_progress"
    session_id: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Verification Session Schemas
class VerificationStartRequest(BaseModel):
    alarm_id: Optional[int] = None
    challenge_type: Optional[str] = "Math Problems"
    difficulty: Optional[str] = "Medium"
    verification_method: Optional[str] = "puzzle_completion"
    verification_steps: Optional[int] = 1
    required_accuracy: Optional[int] = 100
    consecutive_required: Optional[int] = 1
    time_limit: Optional[int] = 20
    first_challenge: Optional[ChallengeResponse] = None

class VerificationSessionState(BaseModel):
    session_id: str
    alarm_id: Optional[int] = None
    verification_method: str = "puzzle_completion"
    status: str = "in_progress" # pending, in_progress, passed, failed, timeout
    current_step: int = 1
    total_steps: int = 1
    correct_count: int = 0
    attempts: int = 0
    accuracy: int = 0
    required_accuracy: int = 100
    consecutive_correct: int = 0
    consecutive_required: int = 1
    time_limit: int = 20
    time_remaining: Optional[int] = None
    current_challenge: Optional[ChallengeResponse] = None

class VerificationStepRequest(BaseModel):
    session_id: str
    step_number: Optional[int] = None
    challenge_id: Optional[str] = None
    user_answer: str = ""
    time_taken: float = 0.0
    is_timeout: bool = False
    alarm_id: Optional[int] = None

class VerificationStepResponse(BaseModel):
    session_id: str
    verification_status: str # pending, in_progress, passed, failed, timeout
    is_step_correct: bool
    message: str
    explanation: str
    current_step: int
    total_steps: int
    correct_count: int
    attempts: int = 0
    accuracy: int = 0
    required_accuracy: int
    consecutive_correct: int
    consecutive_required: int
    time_limit: int
    next_challenge: Optional[ChallengeResponse] = None

class UserPerformanceResponse(BaseModel):
    user_id: int
    total_attempts: int
    total_passed: int
    accuracy_percentage: float
    average_time_taken: float
    recommended_difficulty: str
    preferred_challenge_type: Optional[str] = None
    reason: Optional[str] = None
    score: Optional[float] = None
    trend: Optional[str] = None
    strong_types: List[str] = []
    weak_types: List[str] = []
    type_breakdown: Optional[Dict[str, Any]] = None
    recent_attempts: List[ChallengeAttemptResponse] = []

class AdaptiveRecommendationResponse(BaseModel):
    user_id: int
    recommended_difficulty: str
    recommended_challenge_type: str
    reason: str
    strong_types: List[str] = []
    weak_types: List[str] = []
    score: float
    trend: str
    analysis: Dict[str, Any]


# ==========================================
# REQUIREMENT 10: DASHBOARD & ANALYTICS SCHEMAS
# ==========================================

class DashboardOverviewResponse(BaseModel):
    user_id: int
    total_alarms: int
    active_alarms: int
    completed_alarms: int
    missed_alarms: int
    snooze_count: int
    habit_score: float
    habit_level: str
    current_streak: int
    average_wake_up_time: Optional[str] = None
    average_wake_up_delay_minutes: Optional[float] = None
    average_wakefulness_rating: Optional[float] = None
    verification_success_rate: Optional[float] = None
    sleep_quality_score: Optional[float] = None
    sleep_quality_level: Optional[str] = None


class AlarmHistoryItem(BaseModel):
    id: str
    alarm_id: Optional[int] = None
    alarm_label: str
    scheduled_time: Optional[str] = None
    trigger_time: Optional[str] = None
    actual_wake_time: Optional[str] = None
    status: str
    snooze_count: int = 0
    verification_result: str
    wakefulness_rating: Optional[int] = None
    challenge_result: Optional[str] = None
    date: str
    created_at: Optional[str] = None


class AlarmHistoryResponse(BaseModel):
    filter_type: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    total_records: int
    history: List[AlarmHistoryItem]


class WakeTimeTrendPoint(BaseModel):
    date: str
    scheduled_hhmm: Optional[str] = None
    actual_hhmm: Optional[str] = None
    scheduled_minutes: Optional[int] = None
    actual_minutes: Optional[int] = None
    delay_minutes: Optional[float] = None


class WakeUpStatisticsResponse(BaseModel):
    average_scheduled_wake_time: Optional[str] = None
    average_actual_wake_time: Optional[str] = None
    average_wake_up_delay_minutes: Optional[float] = None
    on_time_wake_percentage: Optional[float] = None
    successful_verification_percentage: Optional[float] = None
    failed_verification_percentage: Optional[float] = None
    average_snoozes_per_alarm: float = 0.0
    average_wakefulness_rating: Optional[float] = None
    average_verification_completion_time_seconds: Optional[float] = None
    trend_points: List[WakeTimeTrendPoint] = []


class ChallengeTypeStat(BaseModel):
    challenge_type: str
    total_attempts: int
    passed: int
    failed: int
    accuracy_percentage: float
    avg_time_taken: float


class DifficultyStat(BaseModel):
    difficulty: str
    total_attempts: int
    passed: int
    failed: int
    accuracy_percentage: float
    avg_time_taken: float


class ChallengePerformanceResponse(BaseModel):
    total_challenges_attempted: int
    completed_challenges: int
    correct_answers: int
    incorrect_answers: int
    overall_accuracy: float
    average_completion_time: float
    performance_by_type: List[ChallengeTypeStat]
    performance_by_difficulty: List[DifficultyStat]
    daily_trend: List[Dict[str, Any]] = []


class ProductivityInsightsResponse(BaseModel):
    wake_up_consistency_vs_performance: Dict[str, Any]
    snooze_frequency_vs_challenge_accuracy: Dict[str, Any]
    wakefulness_rating_vs_challenge_performance: Dict[str, Any]
    insights: List[str]
    status: str


class WellnessDashboardResponse(BaseModel):
    user_id: int
    habit_score: float
    habit_level: str
    wake_up_consistency_percentage: float
    challenge_completion_percentage: float
    snooze_reduction_percentage: float
    sleep_adherence_percentage: float
    current_streak: int
    best_streak: int
    successful_days: int
    unsuccessful_days: int
    behavior_insights: List[str]
    snooze_pattern_status: str


class SleepTrendsResponse(BaseModel):
    disclaimer: str = "Estimated from phone inactivity"
    status: str
    target_bedtime: Optional[str] = None
    target_wake_time: Optional[str] = None
    estimated_bedtime: Optional[str] = None
    estimated_wake_time: Optional[str] = None
    estimated_sleep_duration_hours: Optional[float] = None
    sleep_schedule_adherence_score: float
    daily_sleep_trends: List[Dict[str, Any]] = []


class SleepQualityComponents(BaseModel):
    schedule_adherence: Optional[float] = None
    sleep_duration: Optional[float] = None
    consistency: Optional[float] = None


class SleepQualityDayTrend(BaseModel):
    date: str
    day: str
    score: Optional[float] = None
    duration_hours: Optional[float] = None
    adherence: Optional[float] = None
    level: Optional[str] = None


class SleepQualityResponse(BaseModel):
    score: Optional[float] = None
    level: Optional[str] = None
    status: str  # "available", "insufficient_data"
    estimated: bool = True
    data_days: int = 0
    components: SleepQualityComponents
    history: List[Dict[str, Any]] = []
    message: str = "Estimated from phone inactivity and sleep schedule data"
    disclaimer: str = "*Estimated from phone inactivity and sleep schedule data"


class ProgressMonitoringResponse(BaseModel):
    period_days: int
    habit_score_trend: List[Dict[str, Any]]
    wake_up_consistency_trend: List[Dict[str, Any]]
    challenge_accuracy_trend: List[Dict[str, Any]]
    snooze_behavior_trend: List[Dict[str, Any]]
    sleep_adherence_trend: List[Dict[str, Any]]
    current_streak: int
    best_streak: int


class HabitScoreSection(BaseModel):
    score: Optional[float] = None
    level: str = "Insufficient data"
    change: Optional[float] = None
    previous_score: Optional[float] = None
    breakdown: Dict[str, Optional[float]] = {}
    weights: Dict[str, float] = {}
    status: str = "available"


class WakeUpConsistencySection(BaseModel):
    score: Optional[float] = None
    average_wake_time: Optional[str] = None
    target_wake_time: Optional[str] = None
    on_time: int = 0
    total_wakeups: int = 0
    late: int = 0
    missed: int = 0
    average_delay_minutes: Optional[float] = None
    status: str = "available"


class SnoozeBehaviorSection(BaseModel):
    average_per_day: Optional[float] = None
    total: int = 0
    previous_total: int = 0
    change_percent: Optional[float] = None
    average_duration_minutes: Optional[float] = None
    days_with_snoozes: int = 0
    max_snoozes_single_morning: int = 0
    avg_time_to_dismissal_minutes: Optional[float] = None
    status: str = "available"


class SleepAdherenceSection(BaseModel):
    score: Optional[float] = None
    estimated_bedtime: Optional[str] = None
    target_bedtime: Optional[str] = None
    estimated_wake_time: Optional[str] = None
    target_wake_time: Optional[str] = None
    estimated_duration_hours: Optional[float] = None
    estimated: bool = True
    disclaimer: str = "*Estimated from phone inactivity"
    status: str = "available"


class HabitStreakSection(BaseModel):
    current: int = 0
    best: int = 0
    successful_days: int = 0
    missed_days: int = 0
    failed_verification_days: int = 0
    status: str = "available"


class WakefulnessSection(BaseModel):
    average_rating: Optional[float] = None
    rating_label: str = "Awake"
    verification_success_rate: Optional[float] = None
    verification_failures: int = 0
    average_duration_seconds: Optional[float] = None
    average_challenges_required: Optional[float] = None
    consecutive_correct_rate: Optional[float] = None
    rating_distribution: Dict[str, int] = {}
    status: str = "available"


class HabitTrendPoint(BaseModel):
    date: str
    habit_score: Optional[float] = None
    wake_up_consistency: Optional[float] = None
    snooze_rate: Optional[float] = None
    challenge_success: Optional[float] = None
    sleep_schedule_adherence: Optional[float] = None


class ChallengePerformanceSection(BaseModel):
    overall_accuracy: float = 0.0
    total_attempts: int = 0
    passed: int = 0
    failed: int = 0
    avg_time_taken: float = 0.0
    strongest_type: Optional[str] = None
    weakest_type: Optional[str] = None
    by_type: List[ChallengeTypeStat] = []
    by_difficulty: List[DifficultyStat] = []


class HabitAnalyticsResponse(BaseModel):
    period: str = "7d"
    period_days: int = 7
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    habit_score: HabitScoreSection
    wake_up_consistency: WakeUpConsistencySection
    snooze: SnoozeBehaviorSection
    sleep_adherence: SleepAdherenceSection
    streak: HabitStreakSection
    wakefulness: WakefulnessSection
    trend: List[HabitTrendPoint] = []
    challenge_performance: ChallengePerformanceSection
    insights: List[str] = []
    recommendations: List[Dict[str, Any]] = []


class CategorizedRecommendation(BaseModel):
    id: str
    title: str
    category: str
    message: str
    priority: str
    reason: str
    created_at: str


class CategorizedRecommendationsResponse(BaseModel):
    total_recommendations: int
    recommendations: List[CategorizedRecommendation]


class AdminDashboardResponse(BaseModel):
    total_users: int
    active_users: int
    total_alarms: int
    active_alarms: int
    total_challenges: int
    total_snoozes: int
    system_health: str = "operational"


class AdminUserItem(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str
    provider: str
    total_alarms: int
    habit_score: float
    created_at: Optional[str] = None
    last_active: Optional[str] = None


class AdminRoleUpdateRequest(BaseModel):
    role: str


class AdminAnalyticsResponse(BaseModel):
    total_users: int
    active_users: int
    total_alarms: int
    active_alarms: int
    triggered_alarms: int
    successful_wakeups: int
    failed_verifications: int
    total_snoozes: int
    total_challenges: int
    challenge_accuracy: float
    average_verification_time_seconds: float
    most_used_challenge_types: List[Dict[str, Any]]
    most_used_difficulty_levels: List[Dict[str, Any]]
    habit_score_distribution: Dict[str, int]
    role_distribution: Dict[str, int]
    user_growth_trend: Optional[List[Dict[str, Any]]] = []
    alarm_types_distribution: Optional[Dict[str, int]] = {}


class AdminRecommendationsResponse(BaseModel):
    total_recommendations_generated: int
    by_category: Dict[str, int]
    by_priority: Dict[str, int]
    most_common_recommendation_types: List[Dict[str, Any]]
    recent_activity: List[Dict[str, Any]]


class AdminReportsResponse(BaseModel):
    period: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    total_active_users: int
    alarm_events_count: int
    verification_success_rate: float
    challenge_accuracy_rate: float
    average_habit_score: float
    snooze_frequency_rate: float
    daily_platform_activity: List[Dict[str, Any]]


class AdminAuditLogItem(BaseModel):
    time: str
    module: str
    msg: str
    status: str = "success" # success, info, warning


class AdminAuditLogsResponse(BaseModel):
    total: int
    logs: List[AdminAuditLogItem]


class AdminAlarmItem(BaseModel):
    id: int
    user_id: int
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    title: str
    alarm_time: str
    alarm_type: str
    repeat_days: str
    is_active: bool
    challenge: str
    difficulty_level: str
    sound: str
    vibration: str
    verification_method: str
    created_at: Optional[str] = None


class AdminAlarmListResponse(BaseModel):
    total_alarms: int
    active_alarms: int
    alarms: List[AdminAlarmItem]


# ==========================================
# Requirement 11: Notification Schemas
# ==========================================

class NotificationResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    type: str # bedtime, wake_up, habit_alert, challenge, progress, platform_announcement, report_delivery
    title: str
    message: str
    priority: str = "normal" # low, normal, high, urgent
    is_read: bool = False
    created_at: Optional[str] = None
    scheduled_for: Optional[str] = None
    sent_at: Optional[str] = None
    expires_at: Optional[str] = None
    reference_type: Optional[str] = None
    reference_id: Optional[str] = None
    action_url: Optional[str] = None
    time_ago: Optional[str] = None
    delivery_channel: Optional[str] = "in_app" # in_app, email, sms, both
    delivery_status: Optional[str] = "delivered" # scheduled, sent, delivered, failed, cancelled, unconfigured
    email_status: Optional[str] = None
    sms_status: Optional[str] = None


class NotificationListResponse(BaseModel):
    total: int
    unread_count: int
    notifications: List[NotificationResponse]


class NotificationHistoryItemResponse(BaseModel):
    id: int
    type: str
    title: str
    message: str
    delivery_channel: str
    delivery_status: str
    email_status: Optional[str] = None
    sms_status: Optional[str] = None
    priority: str
    created_at: Optional[str] = None
    time_ago: Optional[str] = None


class NotificationHistoryResponse(BaseModel):
    total: int
    history: List[NotificationHistoryItemResponse]


class DeliveryProviderStatus(BaseModel):
    configured: bool
    provider: str
    sender: Optional[str] = None
    host: Optional[str] = None
    sender_number: Optional[str] = None


class DeliveryProviderStatusResponse(BaseModel):
    email: DeliveryProviderStatus
    sms: DeliveryProviderStatus


class NotificationUnreadCountResponse(BaseModel):
    unread_count: int


class NotificationPreferenceResponse(BaseModel):
    user_id: int
    user_email: Optional[str] = None
    user_phone_number: Optional[str] = None
    phone_number_configured: bool = False
    preferred_channel: str = "both" # email, sms, both, disabled

    # In-App category flags
    bedtime_reminders: bool = True
    wake_up_reminders: bool = True
    habit_alerts: bool = True
    challenge_reminders: bool = True
    progress_notifications: bool = True
    platform_announcements: bool = True
    browser_notifications_enabled: bool = False

    # Email & SMS Matrix flags
    bedtime_email: bool = True
    bedtime_sms: bool = False
    wakeup_email: bool = True
    wakeup_sms: bool = True
    habit_email: bool = True
    habit_sms: bool = False
    challenge_email: bool = True
    challenge_sms: bool = False
    progress_email: bool = True
    progress_sms: bool = False
    announcement_email: bool = True
    announcement_sms: bool = False

    # Timing / Lead Times
    bedtime_lead_minutes: int = 30
    wakeup_lead_minutes: int = 10

    # Report Delivery Settings
    report_delivery_enabled: bool = False
    report_delivery_channel: str = "email" # email, sms, both
    report_delivery_frequency: str = "weekly" # weekly, monthly
    report_delivery_type: str = "habit" # habit, wakeup, challenge, sleep, all


class NotificationPreferenceUpdateRequest(BaseModel):
    preferred_channel: Optional[str] = None # email, sms, both, disabled
    phone_number: Optional[str] = None

    # In-App category flags
    bedtime_reminders: Optional[bool] = None
    wake_up_reminders: Optional[bool] = None
    habit_alerts: Optional[bool] = None
    challenge_reminders: Optional[bool] = None
    progress_notifications: Optional[bool] = None
    platform_announcements: Optional[bool] = None
    browser_notifications_enabled: Optional[bool] = None

    # Email & SMS Matrix flags
    bedtime_email: Optional[bool] = None
    bedtime_sms: Optional[bool] = None
    wakeup_email: Optional[bool] = None
    wakeup_sms: Optional[bool] = None
    habit_email: Optional[bool] = None
    habit_sms: Optional[bool] = None
    challenge_email: Optional[bool] = None
    challenge_sms: Optional[bool] = None
    progress_email: Optional[bool] = None
    progress_sms: Optional[bool] = None
    announcement_email: Optional[bool] = None
    announcement_sms: Optional[bool] = None

    # Timing / Lead Times
    bedtime_lead_minutes: Optional[int] = None
    wakeup_lead_minutes: Optional[int] = None

    # Report Delivery Settings
    report_delivery_enabled: Optional[bool] = None
    report_delivery_channel: Optional[str] = None
    report_delivery_frequency: Optional[str] = None
    report_delivery_type: Optional[str] = None


class ScheduleReportRequest(BaseModel):
    delivery_channel: str = "email" # email, sms, both
    frequency: str = "weekly" # weekly, monthly
    report_type: str = "habit" # habit, wakeup, challenge, sleep, all
    enabled: bool = True


class ScheduleReportResponse(BaseModel):
    status: str = "success"
    message: str
    delivery_channel: str
    frequency: str
    report_type: str
    enabled: bool


class CoachNotificationRequest(BaseModel):
    user_id: int
    message: str
    title: Optional[str] = None
    priority: Optional[str] = "normal"
    action_url: Optional[str] = "user/habits.html"


class CoachDispatchedLogItem(BaseModel):
    id: int
    user_id: int
    patient_name: str
    patient_email: str
    title: str
    message: str
    delivery_channel: str
    delivery_status: str
    is_read: bool
    created_at: Optional[str] = None
    time_ago: Optional[str] = None


class CoachDispatchedLogsResponse(BaseModel):
    total: int
    logs: List[CoachDispatchedLogItem]


class AnnouncementCreateRequest(BaseModel):
    title: str
    message: str
    priority: Optional[str] = "normal"
    target_role: Optional[str] = "all"
    is_active: Optional[bool] = True
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class AnnouncementUpdateRequest(BaseModel):
    title: Optional[str] = None
    message: Optional[str] = None
    priority: Optional[str] = None
    target_role: Optional[str] = None
    is_active: Optional[bool] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class AnnouncementResponse(BaseModel):
    id: int
    title: str
    message: str
    priority: str = "normal"
    target_role: str = "all"
    is_active: bool = True
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    created_by: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AnnouncementListResponse(BaseModel):
    total: int
    active_count: int
    announcements: List[AnnouncementResponse]


# ==========================================================
# REQUIREMENT 8: PERFORMANCE METRICS & SYSTEM EVALUATION
# ==========================================================

class AlarmPerformanceMetrics(BaseModel):
    dismissal_success_rate: Optional[float] = None
    dismissal_status: str = "available"  # available, insufficient_data, no_data, error
    total_triggered_alarms: int = 0
    successful_dismissals: int = 0
    verification_accuracy: Optional[float] = None
    verification_status: str = "available"
    correct_answers: int = 0
    total_answers: int = 0
    total_verification_sessions: int = 0
    successful_sessions: int = 0
    failed_sessions: int = 0
    average_attempts_per_session: Optional[float] = None
    snooze_reduction_rate: Optional[float] = None
    snooze_reduction_status: str = "available"  # available, insufficient_data, no_data
    current_period_snoozes: int = 0
    previous_period_snoozes: int = 0
    snooze_reduction_display: str = "Insufficient data"


class CognitiveChallengeMetrics(BaseModel):
    completion_rate: Optional[float] = None
    completion_status: str = "available"
    completed_challenges: int = 0
    started_challenges: int = 0
    overall_accuracy: Optional[float] = None
    accuracy_status: str = "available"
    correct_answers: int = 0
    total_answers: int = 0
    breakdown_by_type: List[Dict[str, Any]] = []
    breakdown_by_difficulty: List[Dict[str, Any]] = []
    breakdown_by_period: List[Dict[str, Any]] = []
    adaptation_effectiveness: Dict[str, Any] = {}


class HabitFormationMetrics(BaseModel):
    habit_score_improvement: Dict[str, Any] = {}
    wake_up_consistency_rate: Optional[float] = None
    wake_up_consistency_status: str = "available"
    scheduled_wake_ups: int = 0
    successful_on_time_wake_ups: int = 0
    sleep_schedule_adherence: Dict[str, Any] = {}


class RecommendationMetrics(BaseModel):
    relevance: Dict[str, Any] = {}
    engagement_improvement: Dict[str, Any] = {}
    productivity_improvement_rate: Dict[str, Any] = {}


class SystemPerformanceMetrics(BaseModel):
    api_response_time: Dict[str, Any] = {}
    dashboard_loading_speed: Dict[str, Any] = {}
    challenge_generation_latency: Dict[str, Any] = {}
    concurrent_user_capacity: Dict[str, Any] = {}


class AdminPerformanceMetricsResponse(BaseModel):
    period: Dict[str, Any]
    alarm_metrics: AlarmPerformanceMetrics
    challenge_metrics: CognitiveChallengeMetrics
    habit_metrics: HabitFormationMetrics
    recommendation_metrics: RecommendationMetrics
    system_metrics: SystemPerformanceMetrics


# ============================================================================
# Admin -> Coach -> User Assignment System Schemas
# ============================================================================

class CoachAssignedUserItem(BaseModel):
    id: int
    name: Optional[str] = None
    email: str
    role: str
    target_bedtime: Optional[str] = None
    target_wake_time: Optional[str] = None
    inactivity_threshold_minutes: Optional[int] = 30
    habit_score: Optional[float] = 0.0
    sleep_quality_score: Optional[float] = None
    wake_up_consistency: Optional[float] = None
    recent_alarm_count: Optional[int] = 0
    assigned_at: Optional[datetime] = None
    assigned_by: Optional[int] = None
    habit_breakdown: Optional[Dict[str, float]] = None

    class Config:
        from_attributes = True


class AvailableUserItem(BaseModel):
    id: int
    name: Optional[str] = None
    email: str
    role: str
    current_coach_id: Optional[int] = None
    current_coach_name: Optional[str] = None
    habit_score: Optional[float] = 0.0

    class Config:
        from_attributes = True


class CoachSummaryItem(BaseModel):
    id: int
    name: Optional[str] = None
    email: str
    role: str
    assigned_count: int = 0
    assigned_users: List[CoachAssignedUserItem] = []

    class Config:
        from_attributes = True


class CoachAssignmentsOverviewResponse(BaseModel):
    total_coaches: int
    total_assigned_users: int
    total_unassigned_users: int
    coaches: List[CoachSummaryItem]
    available_users: List[AvailableUserItem]


class AssignUserRequest(BaseModel):
    coach_id: int
    user_ids: List[int]


class UnassignUserRequest(BaseModel):
    coach_id: int
    user_ids: List[int]


class AssignmentActionResponse(BaseModel):
    status: str = "success"
    message: str
    assigned_count: int
    affected_user_ids: List[int] = []
