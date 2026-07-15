"""
Generic track/completion computation, shared by BOTH onboarding
(OnboardingTask) and offboarding (OffboardingTask) -- same logic, two
separate backing tables (kept separate deliberately -- see architecture
decision against a shared table with a workflow_type discriminator).

The private _get_* functions hold the one real implementation. Public
functions below are thin, named wrappers per workflow so existing
callers (profile.py, routers/onboarding.py, progress.py) don't need to
change signatures, and new offboarding callers get matching names.

A track is "completed" only when every MANDATORY task in it is approved.
Never cached/stored -- computed fresh every call, so nothing can drift
out of sync with reality (see the earlier hardcoded-step-count bug for
exactly why that matters).
"""
import datetime
from sqlalchemy.orm import Session
from app.models import OnboardingTask, OffboardingTask, Employee

TRACKS = ["HR", "IT", "Security", "Manager"]


def _get_track_status(db: Session, task_model, employee_id: str, track: str) -> str:
    tasks = db.query(task_model).filter(
        task_model.employee_id == employee_id, task_model.track == track
    ).all()
    if not tasks:
        return "not_started"
    mandatory = [t for t in tasks if t.is_mandatory]
    if not mandatory:
        return "completed"
    if any(t.status == "rejected" for t in mandatory):
        return "blocked"
    if all(t.status == "approved" for t in mandatory):
        return "completed"
    return "in_progress"


def _get_track_completion_fraction(db: Session, task_model, employee_id: str, track: str) -> float:
    tasks = db.query(task_model).filter(
        task_model.employee_id == employee_id, task_model.track == track
    ).all()
    if not tasks:
        return 0.0
    mandatory = [t for t in tasks if t.is_mandatory]
    if not mandatory:
        return 1.0
    approved = sum(1 for t in mandatory if t.status == "approved")
    return approved / len(mandatory)


def _get_all_track_statuses(db: Session, task_model, employee_id: str) -> dict:
    return {track: _get_track_status(db, task_model, employee_id, track) for track in TRACKS}


def _recompute_employee_status(db: Session, task_model, employee_id: str,
                                from_status: str, to_status: str, timestamp_attr: str = None):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee or employee.status != from_status:
        return
    statuses = _get_all_track_statuses(db, task_model, employee_id)
    if all(s == "completed" for s in statuses.values()):
        employee.status = to_status
        if timestamp_attr:
            setattr(employee, timestamp_attr, datetime.datetime.utcnow())
        db.commit()


# --- Onboarding (unchanged names/signatures -- existing callers untouched) ---

def get_track_status(db: Session, employee_id: str, track: str) -> str:
    return _get_track_status(db, OnboardingTask, employee_id, track)


def get_track_completion_fraction(db: Session, employee_id: str, track: str) -> float:
    return _get_track_completion_fraction(db, OnboardingTask, employee_id, track)


def get_all_track_statuses(db: Session, employee_id: str) -> dict:
    return _get_all_track_statuses(db, OnboardingTask, employee_id)


def recompute_employee_status(db: Session, employee_id: str):
    """Flips employee to 'active' once every onboarding track is
    completed; records activated_at for AI Insights duration calc."""
    _recompute_employee_status(db, OnboardingTask, employee_id, "onboarding", "active", "activated_at")


# --- Offboarding (new) ---

def get_offboarding_track_status(db: Session, employee_id: str, track: str) -> str:
    return _get_track_status(db, OffboardingTask, employee_id, track)


def get_offboarding_track_completion_fraction(db: Session, employee_id: str, track: str) -> float:
    return _get_track_completion_fraction(db, OffboardingTask, employee_id, track)


def get_all_offboarding_track_statuses(db: Session, employee_id: str) -> dict:
    return _get_all_track_statuses(db, OffboardingTask, employee_id)


def recompute_employee_offboarding_status(db: Session, employee_id: str):
    """Flips employee to 'exited' once every offboarding track is completed."""
    _recompute_employee_status(db, OffboardingTask, employee_id, "offboarding", "exited")
