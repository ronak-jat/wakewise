import os
import sys
import time
import logging
import asyncio
import datetime

# Ensure current directory is always in sys.path for direct or module execution
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from starlette.requests import Request

from config import settings
from database import engine, Base, run_db_migrations
from routes import auth, alarms, challenges, analytics, dashboard, admin, notifications
from scheduler import start_scheduler_if_not_running, stop_scheduler_task
from services.metrics_collector import metrics_collector

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI App
app = FastAPI(
    title=settings.APP_NAME,
    description="Unified FastAPI Backend, Database & Frontend Server.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS middleware
cors_origins = settings.get_allowed_origins()
if "*" in cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_origin_regex=os.getenv("ALLOWED_ORIGIN_REGEX", r"^https:\/\/.*\.vercel\.app$"),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Lightweight Server-Side Timing Middleware for System Performance Monitoring
@app.middleware("http")
async def performance_timing_middleware(request: Request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start_time) * 1000.0

    # Attach timing header
    response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"

    # Record to metrics collector for API response time measurements
    # (omits query params and sensitive bodies)
    metrics_collector.record_request(
        path=request.url.path,
        method=request.method,
        status_code=response.status_code,
        duration_ms=duration_ms
    )

    return response

# Include Routers
app.include_router(auth.router)
app.include_router(alarms.router)
app.include_router(challenges.router)
app.include_router(analytics.router)
app.include_router(dashboard.router)
app.include_router(admin.router)
app.include_router(notifications.router)


@app.on_event("startup")
async def startup_event():
    """
    Creates tables in Database, runs column migrations, and starts background scheduler service.
    """
    try:
        logger.info("Initializing Database tables and running migrations...")
        Base.metadata.create_all(bind=engine)
        run_db_migrations()
        logger.info("Database tables and migrations initialized successfully.")
    except Exception as e:
        logger.error(f"Warning during DB table initialization: {e}")

    # Launch the background alarm scheduler loop (guaranteed single instance)
    await start_scheduler_if_not_running()


@app.on_event("shutdown")
def shutdown_event():
    """Gracefully cancel background tasks upon application shutdown."""
    stop_scheduler_task()


@app.get("/health", tags=["Health Check"])
@app.get("/api/health", tags=["Health Check"])
def health_check():
    """Lightweight health check endpoint indicating API operational status."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }


# Top-level Dashboard & Navigation convenience redirects
def get_frontend_redirect(relative_path: str) -> str:
    """Returns absolute frontend URL in production, or relative path in development."""
    fe = (settings.FRONTEND_URL or "").strip().rstrip("/")
    if fe and not ("localhost" in fe or "127.0.0.1" in fe):
        return f"{fe}/{relative_path.lstrip('/')}"
    return relative_path


@app.get("/dashboard-user.html", include_in_schema=False)
@app.get("/dashboard", include_in_schema=False)
def redirect_user_dashboard():
    return RedirectResponse(url=get_frontend_redirect("/user/dashboard-user.html"))

@app.get("/dashboard-admin.html", include_in_schema=False)
@app.get("/admin", include_in_schema=False)
@app.get("/admin/dashboard", include_in_schema=False)
def redirect_admin_dashboard():
    return RedirectResponse(url=get_frontend_redirect("/admin/dashboard-admin.html"))

@app.get("/dashboard-coach.html", include_in_schema=False)
@app.get("/coach", include_in_schema=False)
@app.get("/coach/dashboard", include_in_schema=False)
def redirect_coach_dashboard():
    return RedirectResponse(url=get_frontend_redirect("/coach/dashboard-coach.html"))

@app.get("/login", include_in_schema=False)
def redirect_login():
    return RedirectResponse(url=get_frontend_redirect("/login.html"))


# Mount static frontend directory if present (for local development convenience)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
frontend_root = os.path.join(project_root, "frontend")
assets_root = os.path.join(project_root, "assets")

if os.path.exists(assets_root):
    app.mount("/assets", StaticFiles(directory=assets_root), name="assets")

if os.path.exists(frontend_root):
    app.mount("/", StaticFiles(directory=frontend_root, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", settings.PORT or 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=settings.DEBUG)

