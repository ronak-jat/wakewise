# WakeWise AI — Intelligent Cognitive Alarm & Sleep Wellness Platform

WakeWise AI is a comprehensive full-stack platform designed to systematically eliminate morning sleep inertia, build circadian rhythm consistency, and track sleep wellness. By combining multi-step cognitive verification challenges, multi-provider AI generation (Google Gemini & Groq), an adaptive difficulty engine, a behavioral habit scoring engine, multi-channel notifications, and live performance telemetry, WakeWise ensures users wake up alert, energized, and on schedule.

---

## Table of Contents
- [Key Features & Capabilities](#-key-features--capabilities)
- [System Architecture](#-system-architecture)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Getting Started](#-getting-started)
  - [Prerequisites](#prerequisites)
  - [Environment Configuration](#environment-configuration)
  - [Database Initialization](#database-initialization)
  - [Running the Server](#running-the-server)
- [API Architecture & Documentation](#-api-architecture--documentation)
- [Role-Based Access Control (RBAC)](#-role-based-access-control-rbac)
- [Automated Testing & Load Benchmarking](#-automated-testing--load-benchmarking)
- [Security & Data Integrity](#-security--data-integrity)
- [License](#-license)

---

## 🌟 Key Features & Capabilities

### 1. Multi-Step Wake-Up Verification Protocols
Eliminates mindless alarm snoozing by requiring cognitive problem solving before an alarm can be dismissed:
- **Puzzle Completion**: Requires solving an assigned cognitive problem to silence the alarm.
- **Multi-Step Challenge**: Demands 2–3 sequential cognitive questions in the same wake-up session.
- **Consecutive Correct**: Requires a streak of consecutive correct answers; wrong answers reset the streak.
- **Time-Based Verification**: Enforces strict configurable timers per challenge with recorded timeouts.
- **Cognitive Accuracy Check**: Validates that the user exceeds a threshold accuracy percentage across questions.

### 2. Multi-Provider AI Challenge Engine
Generates diverse, engaging wake-up challenges across 7 canonical categories:
- **Challenge Types**: Math Problems, Logic Puzzles, Memory Challenges, Word Games, Pattern Recognition, Riddles, and Quick Quizzes.
- **Multi-Provider Fallback**: Orchestrates **Google Gemini Flash** (dynamic reasoning), **Groq API** (sub-second high-speed inference), and a high-reliability **Local Cognitive Engine** to guarantee 100% alarm reliability even when offline.

### 3. Intelligent Adaptive Difficulty Engine
Analyzes historical user challenge attempts and dynamically adjusts cognitive intensity across 5 canonical tiers:
$$\text{Beginner} \longleftrightarrow \text{Easy} \longleftrightarrow \text{Medium} \longleftrightarrow \text{Hard} \longleftrightarrow \text{Expert}$$
- Tracks accuracy trends, response speed ratios, consecutive streaks, and type-specific domain strengths.

### 4. Behavioral Habit Scoring Engine (Requirement 8)
Computes a transparent, explainable 0–100 Habit Score based on a weighted multi-factor formula:
$$\text{Habit Score} = (\text{Wake-Up Consistency} \times 0.35) + (\text{Challenge Completion} \times 0.25) + (\text{Snooze Reduction} \times 0.20) + (\text{Sleep Schedule Adherence} \times 0.20)$$

### 5. Sleep Schedule & Phone Inactivity Tracking
Estimates bedtime and wake-up regularity using non-intrusive phone inactivity thresholds and wake-up dismissals. All estimated sleep data is transparently labeled as *Estimated from phone inactivity*.

### 6. Multi-Channel Notification & Announcement System
- Dispatches bedtime reminders, wake-up alerts, habit score milestones, and challenge prompts across **In-App**, **Email**, and **SMS** channels.
- Administrator-controlled broadcast platform announcements with priority levels and target audience filtering.

### 7. Administrator Performance Metrics & Telemetry Cockpit
- Real-time evaluation of Alarm Performance (Dismissal rates, Verification accuracy, Snooze deltas).
- Cognitive Challenge performance breakdowns by type, difficulty, and daily time periods.
- Server-side telemetry tracking API Response Times (Avg, Median, P95, slowest endpoints), Dashboard Loading Speeds, and Challenge Generation Latencies.
- Transparent data quality reporting with distinct `available`, `insufficient_data`, and `not_enough_feedback` states (never coercing missing denominators to 0%).

---

## 🏛️ System Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        WakeWise AI Platform Architecture                │
└────────────────────────────────────────────────────────────────────────┘

    [ User Web Client ]      [ Wellness Coach ]      [ Admin Cockpit ]
           │                        │                       │
           └────────────────────────┼───────────────────────┘
                                    │ HTTP / REST / JSON
                                    ▼
                 ┌──────────────────────────────────────┐
                 │          FastAPI ASGI Backend        │
                 │  - CORS & Non-blocking Middleware    │
                 │  - Server-Side Timing Telemetry      │
                 │  - BCrypt & JWT Security Guard       │
                 │  - Background Scheduler Loop         │
                 └──────────────────┬───────────────────┘
                                    │
       ┌────────────────────────────┼───────────────────────────┐
       ▼                            ▼                           ▼
┌──────────────┐          ┌───────────────────┐       ┌───────────────────┐
│  PostgreSQL  │          │   AI Generators   │       │ Delivery Services │
│  - Users     │          │  - Google Gemini  │       │  - In-App Alerts  │
│  - Alarms    │          │  - Groq HighSpeed │       │  - SMTP Email     │
│  - Attempts  │          │  - Local Fallback │       │  - Twilio SMS     │
│  - Snoozes   │          └───────────────────┘       └───────────────────┘
│  - Alerts    │
└──────────────┘
```

---

## 💻 Tech Stack

- **Backend Framework**: [FastAPI](https://fastapi.tiangolo.com/) (Python 3.10+)
- **ASGI Server**: [Uvicorn](https://www.uvicorn.org/)
- **Database & ORM**: [PostgreSQL](https://www.postgresql.org/) with [SQLAlchemy 2.0](https://www.sqlalchemy.org/)
- **Authentication**: JWT Access Tokens ([python-jose](https://github.com/mpdavy/python-jose)) & [BCrypt](https://github.com/pyca/bcrypt/) password hashing, Google OAuth2
- **AI Providers**: Google Gemini Flash API (`generativelanguage.googleapis.com`) & Groq AI
- **Frontend**: Responsive HTML5, Modern Vanilla JavaScript (ES6+), Modern Glassmorphism CSS design system, [Chart.js](https://www.chartjs.org/) for analytics visualization.

---

## 📁 Project Structure

```
ai-alarm/
├── assets/                  # Shared static assets & sound tones
├── backend/
│   ├── routes/              # FastAPI APIRouters
│   │   ├── admin.py         # Admin cockpit & performance metrics APIs
│   │   ├── alarms.py        # Alarm management & schedule endpoints
│   │   ├── analytics.py     # User behavioral analytics & insights
│   │   ├── auth.py          # Registration, login, profile & Google OAuth
│   │   ├── challenges.py    # Cognitive verification & challenge flows
│   │   ├── dashboard.py     # User overview, history & habit snapshots
│   │   └── notifications.py # Notification dispatch & preferences
│   ├── services/            # Core business engines
│   │   ├── delivery_service.py        # Multi-channel delivery handler
│   │   ├── fallback_challenges.py     # Curated offline challenge bank
│   │   ├── gemini_service.py          # Gemini AI challenge generator
│   │   ├── groq_service.py            # Groq AI challenge generator
│   │   ├── habit_score_service.py     # Habit scoring engine & sleep rules
│   │   ├── metrics_collector.py       # Performance timing collector
│   │   ├── notification_service.py    # Notification rules & dispatch
│   │   ├── performance_metrics_service.py # Consolidated metrics engine
│   │   ├── personalization_service.py # Adaptive difficulty engine
│   │   ├── sleep_quality_service.py   # Sleep regularity analytics
│   │   └── verification_service.py    # Wake-up verification state machine
│   ├── tests/               # Comprehensive automated test suite
│   │   ├── test_adaptive_engine.py
│   │   ├── test_alarm_behavior.py
│   │   ├── test_auth_and_admin_security.py
│   │   ├── test_behavioral_analytics.py
│   │   ├── test_dashboard_analytics.py
│   │   ├── test_habit_score_engine.py
│   │   ├── test_performance_metrics.py
│   │   └── load_test_system.py        # Standalone load testing benchmark
│   ├── config.py            # Environment settings & validation
│   ├── database.py          # SQLAlchemy session & migration handlers
│   ├── main.py              # Application entry point & middleware
│   ├── models.py            # PostgreSQL SQLAlchemy data models
│   ├── requirements.txt     # Pinned Python package dependencies
│   ├── scheduler.py         # Background alarm daemon
│   ├── schemas.py           # Pydantic serialization schemas
│   ├── security.py          # BCrypt hashing & JWT utilities
│   └── seed_rich_data.py    # Development data seeder
└── frontend/
    ├── admin/               # Administrator Cockpit UI & reports
    ├── coach/               # Wellness Coach Console
    ├── user/                # User Dashboard & verification screens
    ├── css/                 # Modern styling & glassmorphism theme
    ├── js/                  # Frontend controllers & state managers
    ├── index.html           # Landing page
    └── login.html           # Unified authentication portal
```

---

## 🚀 Getting Started

### Prerequisites
- **Python**: 3.10 or higher
- **PostgreSQL**: 13 or higher (or Docker)

### Environment Configuration
Copy `.env.example` to `.env` inside the `backend` folder and configure your settings:

```bash
cd backend
cp .env.example .env
```

Key environment variables:
```env
APP_NAME=WakeWise AI
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ai_alarm_db
SECRET_KEY=your-secure-random-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# AI Generation Keys (Optional - Falls back to local cognitive engine if omitted)
GEMINI_API_KEY=your-gemini-api-key
GROQ_API_KEY=your-groq-api-key
AI_PROVIDER=auto
```

### Database Initialization
Run the database initialization script to create tables, apply column migrations, and seed default administrative credentials:

```bash
python init_db.py
```

Optional: Seed rich sample data for local development:
```bash
python seed_rich_data.py
```

### Running the Server
Launch the FastAPI server with hot-reloading enabled:

```bash
python -m uvicorn main:app --reload --port 8000
```

Access the platform:
- **Landing Page**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **User Dashboard**: [http://127.0.0.1:8000/user/dashboard-user.html](http://127.0.0.1:8000/user/dashboard-user.html)
- **Admin Cockpit**: [http://127.0.0.1:8000/admin/dashboard-admin.html](http://127.0.0.1:8000/admin/dashboard-admin.html)
- **Interactive OpenAPI Documentation**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 📡 API Architecture & Documentation

| Method | Endpoint | Description | Access |
|---|---|---|---|
| `POST` | `/api/auth/register` | Register new platform user | Public |
| `POST` | `/api/auth/login` | Authenticate credentials & receive JWT | Public |
| `POST` | `/api/auth/google` | Google OAuth2 token verification | Public |
| `GET` | `/api/alarms` | Retrieve user alarms | User |
| `POST` | `/api/alarms` | Create configured wake-up schedule | User |
| `POST` | `/api/challenges/verification/start` | Start wake-up verification session | User |
| `POST` | `/api/challenges/verification/step` | Submit answer for verification step | User |
| `GET` | `/api/dashboard/overview` | Retrieve habit snapshot & metrics | User |
| `GET` | `/api/analytics/summary` | User cognitive score & trend analysis | User |
| `GET` | `/api/admin/dashboard` | Platform statistics & totals | Admin |
| `GET` | `/api/admin/performance-metrics` | Consolidated Performance Metrics (Req 8) | Admin |
| `GET` | `/api/admin/users` | Manage user accounts & permissions | Admin |
| `GET` | `/api/admin/logs` | Audit trail & security event ledger | Admin |

---

## 🛡️ Role-Based Access Control (RBAC)

WakeWise enforces strict authorization boundaries across three user roles:
1. **`USER` / `STUDENT`**: Access to personal alarms, cognitive challenges, habit score analytics, sleep routine settings, and personalized recommendations.
2. **`WELLNESS COACH`**: Access to wellness progress reports, habit streaks, sleep trends, and guidance tools.
3. **`ADMINISTRATOR` / `ADMIN`**: Complete access to the Admin Cockpit, user console, role updates, platform announcements, audit logs, performance metrics telemetry, and report exports.

---

## 🧪 Automated Testing & Load Benchmarking

### Running Automated Test Suite
The project uses Python's standard `unittest` framework with zero external test-runner requirements:

```bash
# Run Performance Metrics & System Evaluation Tests
python -m unittest tests.test_performance_metrics

# Run Complete Test Suite
python -m unittest discover tests
```

### Running Concurrent User Load Benchmark
Measure real server throughput, average latency, and P95 response times under simulated concurrent load:

```bash
python tests/load_test_system.py --concurrency 10 --duration 5
```

---

## 🔒 Security & Data Integrity

- **Password Security**: Passwords are encrypted with salted **BCrypt** hashes before persisting to PostgreSQL.
- **JWT Authentication**: Stateless, signed tokens using **HS256** algorithm with configurable expiration.
- **Data Quality Safeguards**: Missing telemetry is strictly flagged as `Insufficient data` rather than coerced to artificial zero values.
- **Telemetry Privacy**: Server timing middleware strictly sanitizes request paths and excludes credentials, tokens, passwords, and private bodies from logs.

---

## 📄 License
This project is licensed under the terms of the [MIT License](LICENSE).
