import os
import logging
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from config import settings
from database import engine, Base, run_db_migrations
from routes import auth, alarms, challenges, analytics, dashboard, admin, notifications
from scheduler import alarm_scheduler_loop

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

import time
from starlette.requests import Request
from services.metrics_collector import metrics_collector

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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

    # Launch the background alarm scheduler loop
    asyncio.create_task(alarm_scheduler_loop())


@app.get("/api/health", tags=["Health Check"])
def health_check():
    return {"status": "healthy", "app": settings.APP_NAME}

# Mount static frontend directory if present
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
frontend_root = os.path.join(project_root, "frontend")
assets_root = os.path.join(project_root, "assets")

# Top-level Dashboard & Navigation convenience redirects
from fastapi.responses import RedirectResponse

@app.get("/dashboard-user.html", include_in_schema=False)
@app.get("/dashboard", include_in_schema=False)
def redirect_user_dashboard():
    return RedirectResponse(url="/user/dashboard-user.html")

@app.get("/dashboard-admin.html", include_in_schema=False)
@app.get("/admin", include_in_schema=False)
@app.get("/admin/dashboard", include_in_schema=False)
def redirect_admin_dashboard():
    return RedirectResponse(url="/admin/dashboard-admin.html")

@app.get("/dashboard-coach.html", include_in_schema=False)
@app.get("/coach", include_in_schema=False)
@app.get("/coach/dashboard", include_in_schema=False)
def redirect_coach_dashboard():
    return RedirectResponse(url="/coach/dashboard-coach.html")

@app.get("/login", include_in_schema=False)
def redirect_login():
    return RedirectResponse(url="/login.html")

# Serve static frontend pages from the frontend folder.
# Mounting at root handles all non-/api routes automatically.
if os.path.exists(assets_root):
    app.mount("/assets", StaticFiles(directory=assets_root), name="assets")

if os.path.exists(frontend_root):
    app.mount("/", StaticFiles(directory=frontend_root, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
