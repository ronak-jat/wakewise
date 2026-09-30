import os
from typing import Optional
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()

class Settings(BaseSettings):
    APP_NAME: str = "AI Alarm Platform API"
    DEBUG: bool = False
    
    # PostgreSQL Connection String
    _raw_db_url: str = os.getenv(
        "DATABASE_URL", 
        "postgresql://postgres:postgres@localhost:5432/ai_alarm_db"
    )
    DATABASE_URL: str = (
        _raw_db_url.strip().replace("postgres://", "postgresql://", 1)
        if _raw_db_url and _raw_db_url.strip().startswith("postgres://")
        else _raw_db_url.strip() if _raw_db_url else "postgresql://postgres:postgres@localhost:5432/ai_alarm_db"
    )

    @property
    def clean_database_url(self) -> str:
        url = (self.DATABASE_URL or "").strip()
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url
    
    # Server & Environment Settings
    PORT: int = int(os.getenv("PORT", "8000"))
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "https://wakewise.dev")
    
    # JWT & Password Hashing Settings
    SECRET_KEY: str = os.getenv("SECRET_KEY", "super-secret-key-change-this-in-production-123456789")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440 # 24 Hours
    
    # Google OAuth Settings
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "")
    
    # CORS Allowed Origins & Regex (Railway production & custom domain)
    ALLOWED_ORIGINS: str = os.getenv(
        "ALLOWED_ORIGINS", 
        "https://wakewise.dev,https://www.wakewise.dev,https://web-production-de20d.up.railway.app,http://localhost:8000,http://127.0.0.1:8000,http://localhost:5500,http://127.0.0.1:5500,http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173"
    )
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "")
    ALLOWED_ORIGIN_REGEX: Optional[str] = os.getenv(
        "ALLOWED_ORIGIN_REGEX",
        os.getenv("CORS_ORIGIN_REGEX", None)
    )

    def get_allowed_origins(self) -> list[str]:
        """Returns list of unique allowed origins for CORS, including FRONTEND_URL and production domains."""
        origins = {
            "https://wakewise.dev",
            "https://www.wakewise.dev",
            "https://web-production-de20d.up.railway.app",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:5500",
            "http://127.0.0.1:5500",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173"
        }

        def _add_from_str(s: str):
            if not s:
                return
            for item in s.split(","):
                cleaned = item.strip().rstrip("/")
                if cleaned and cleaned != "*":
                    origins.add(cleaned)

        _add_from_str(self.ALLOWED_ORIGINS)
        _add_from_str(self.CORS_ORIGINS)
        _add_from_str(os.getenv("CORS_ORIGINS", ""))
        _add_from_str(os.getenv("ALLOWED_ORIGINS", ""))
        _add_from_str(self.FRONTEND_URL)
        _add_from_str(os.getenv("FRONTEND_URL", ""))

        return sorted(list(origins))

    # AI Provider API Keys
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODELS: str = os.getenv("GROQ_MODELS", "openai/gpt-oss-20b,qwen/qwen3-32b")
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "auto") # auto, groq, gemini, local

    # Email Delivery Settings (SMTP)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_TLS: bool = os.getenv("SMTP_TLS", "true").lower() in ("true", "1", "yes")
    EMAILS_FROM_EMAIL: str = os.getenv("EMAILS_FROM_EMAIL", "notifications@wakewise.ai")
    EMAILS_FROM_NAME: str = os.getenv("EMAILS_FROM_NAME", "WakeWise AI")

    # SMS Delivery Settings (Twilio)
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "")

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

