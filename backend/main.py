"""
Entry point. Wires up all routers, creates DB tables on startup (fine for
POC -- use Alembic migrations if this grows past the POC), pre-warms Ollama.
"""
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app import models  # noqa: F401 -- ensures models are registered before create_all
from app.ai_client import prewarm
from app.routers import (
    auth, employees, hrms_sync, onboarding, offboarding,
    approvals, reports, audit, dashboard, profile, insights,
    decisions, compliance,
    auth,
    employees,
    hrms_sync,
    onboarding,
    offboarding,
    access,
    assets,
    approvals,
    reports,
    audit,
    dashboard,
    profile,
    insights,
    hr_assistant,   # <-- NEW
)

app = FastAPI(title="Onboarding/Offboarding POC API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Existing Routers
app.include_router(auth.router)
app.include_router(employees.router)
app.include_router(hrms_sync.router)
app.include_router(onboarding.router)
app.include_router(offboarding.router)
app.include_router(approvals.router)
app.include_router(reports.router)
app.include_router(audit.router)
app.include_router(dashboard.router)
app.include_router(profile.router)
app.include_router(insights.router)
app.include_router(decisions.router)
app.include_router(compliance.router)

# HR Assistant Router
app.include_router(hr_assistant.router)


@app.on_event("startup")
def on_startup():
    """
    Create database tables and warm up Ollama.
    """
    Base.metadata.create_all(bind=engine)
    prewarm()


@app.get("/")
def health():
    return {
        "status": "backend running",
        "service": "HR Onboarding/Offboarding POC",
        "hr_assistant": "available"
    }