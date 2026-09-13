# WakeWise AI — Backend Architecture & Service Guide

This directory contains the production-grade FastAPI backend, PostgreSQL database models, multi-provider cognitive engines, scheduling daemons, and performance telemetry services.

---

## 🏛️ Architecture Overview

The backend is built around a decoupled service-oriented architecture:

```
┌────────────────────────────────────────────────────────┐
│                   FastAPI APIRouter Layer              │
│  (auth, alarms, challenges, analytics, dashboard, admin)│
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                    Business Services                   │
│  ├─ verification_service.py   (State machine)          │
│  ├─ habit_score_service.py    (Weighted habit formula) │
│  ├─ personalization_service.py (Adaptive difficulty)   │
│  ├─ gemini_service.py         (Gemini AI generator)    │
│  ├─ groq_service.py           (Groq fast AI generator) │
│  ├─ delivery_service.py       (Email / SMS dispatch)   │
│  └─ metrics_collector.py      (Telemetry buffer)       │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│           SQLAlchemy ORM & PostgreSQL Database         │
│  (users, alarms, attempts, snoozes, notifications)     │
└────────────────────────────────────────────────────────┘
```

---

## 📦 Installed Python Dependencies (`requirements.txt`)

| Package | Purpose | Version Constraint |
|---|---|---|
| `fastapi` | Core web framework & routing | `>=0.110.0,<1.0.0` |
| `uvicorn[standard]` | High-performance ASGI server | `>=0.29.0,<1.0.0` |
| `starlette` | ASGI toolkit & middleware | `>=0.36.0,<1.0.0` |
| `sqlalchemy` | Object Relational Mapper (ORM) | `>=2.0.28,<3.0.0` |
| `psycopg2-binary` | PostgreSQL database adapter | `>=2.9.9,<3.0.0` |
| `pydantic` | Schema validation & serialization | `>=2.6.4,<3.0.0` |
| `pydantic-settings`| Environment configuration parsing | `>=2.2.1,<3.0.0` |
| `email-validator` | Email format verification | `>=2.1.1,<3.0.0` |
| `bcrypt` | Salted password encryption | `>=4.1.2,<5.0.0` |
| `python-jose[cryptography]` | JWT token generation & verification | `>=3.3.0,<4.0.0` |
| `python-dotenv` | Loads `.env` environment variables | `>=1.0.1,<2.0.0` |
| `google-auth` | Google OAuth2 token verification | `>=2.28.2,<3.0.0` |
| `requests` | HTTP client for external AI & webhooks | `>=2.31.0,<3.0.0` |
| `httpx` | TestClient & asynchronous HTTP requests | `>=0.27.0,<1.0.0` |

---

## 🛠️ Development & Execution

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Ensure your `.env` contains valid database credentials:
```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ai_alarm_db
SECRET_KEY=your-secure-random-secret-key
```

### 3. Initialize Database & Run Migrations
```bash
python init_db.py
```

### 4. Start Development Server
```bash
python -m uvicorn main:app --reload --port 8000
```

### 5. Run Automated Tests
```bash
# Performance Metrics test suite
python -m unittest tests.test_performance_metrics

# Full test discovery
python -m unittest discover tests
```

### 6. Run Concurrent User Load Test
```bash
python tests/load_test_system.py --concurrency 10 --duration 5
```
