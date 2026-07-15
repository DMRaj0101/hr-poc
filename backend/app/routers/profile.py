"""
Aggregates everything needed for the Employee Profile screen into one call --
personal info, employment details, real completion %, timeline, recent activity.

Both onboarding_tasks and offboarding_tasks are grouped by track with
live-computed track_status, from OnboardingTask/OffboardingTask directly.
The old Approval table is fully retired for both workflows now -- nothing
here queries it. compliance_tasks combines category="compliance" rows
from both task tables, so an employee who's been through both flows
shows their complete compliance history in one place.
"""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    Employee, OnboardingTracker, OffboardingTracker, AccessRecommendation,
    AssetAllocation, AuditLog, OnboardingTask, OffboardingTask,
)
from app.services.progress import get_onboarding_completion_pct
from app.services.track_status import get_all_track_statuses, get_all_offboarding_track_statuses, TRACKS

router = APIRouter(prefix="/employees", tags=["profile"])


def _tasks_by_track(task_rows):
    by_track = {track: [] for track in TRACKS}
    for t in task_rows:
        by_track.setdefault(t.track, []).append({
            "task_name": t.task_name, "status": t.status, "is_mandatory": t.is_mandatory,
            "is_ai_generated": t.is_ai_generated == "true", "ai_recommendation": t.ai_recommendation,
            "category": t.category,
        })
    return by_track


@router.get("/{employee_id}/profile")
def get_profile(employee_id: str, db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    onboarding_steps = (
        db.query(OnboardingTracker)
        .filter(OnboardingTracker.employee_id == employee_id)
        .order_by(OnboardingTracker.timestamp.asc())
        .all()
    )
    offboarding_steps = (
        db.query(OffboardingTracker)
        .filter(OffboardingTracker.employee_id == employee_id)
        .order_by(OffboardingTracker.timestamp.asc())
        .all()
    )

    completion_pct = get_onboarding_completion_pct(db, employee_id)

    timeline = [
        {"step": s.step, "status": s.status, "timestamp": s.timestamp, "flow": "onboarding"}
        for s in onboarding_steps
    ] + [
        {"step": s.step, "status": s.status, "timestamp": s.timestamp, "flow": "offboarding"}
        for s in offboarding_steps
    ]
    timeline.sort(key=lambda x: x["timestamp"])

    recent_activity = (
        db.query(AuditLog)
        .filter(AuditLog.employee_id == employee_id)
        .order_by(AuditLog.timestamp.desc())
        .limit(10)
        .all()
    )

    access = db.query(AccessRecommendation).filter(AccessRecommendation.employee_id == employee_id).order_by(AccessRecommendation.created_at.desc()).first()
    assets = db.query(AssetAllocation).filter(AssetAllocation.employee_id == employee_id).order_by(AssetAllocation.created_at.desc()).first()

    onboarding_tasks_raw = db.query(OnboardingTask).filter(OnboardingTask.employee_id == employee_id).all()
    offboarding_tasks_raw = db.query(OffboardingTask).filter(OffboardingTask.employee_id == employee_id).all()

    compliance_tasks = [
        {"task_name": t.task_name, "status": t.status, "flow": "onboarding"}
        for t in onboarding_tasks_raw if t.category == "compliance"
    ] + [
        {"task_name": t.task_name, "status": t.status, "flow": "offboarding"}
        for t in offboarding_tasks_raw if t.category == "compliance"
    ]

    return {
        "personal_information": {
            "name": employee.name, "employee_id": employee.employee_id,
            "email": employee.email, "office": employee.office,
        },
        "employment_details": {
            "department": employee.department, "title": employee.title, "role": employee.role,
            "experience_level": employee.experience_level,
            "manager": employee.manager, "joining_date": employee.joining_date,
            "status": employee.status, "sync_source": employee.sync_source,
        },
        "profile_completion_pct": completion_pct,
        "timeline": timeline,
        "recent_activity": [
            {"timestamp": a.timestamp, "agent": a.agent, "action": a.action, "detail": a.detail}
            for a in recent_activity
        ],
        "applications": json.loads(access.applications) if access else [],
        "security_groups": json.loads(access.security_groups) if access else [],
        "assets": json.loads(assets.asset_list) if assets else [],
        "compliance_tasks": compliance_tasks,
        "onboarding_tasks": _tasks_by_track(onboarding_tasks_raw),
        "onboarding_track_status": get_all_track_statuses(db, employee_id),
        "offboarding_tasks": _tasks_by_track(offboarding_tasks_raw),
        "offboarding_track_status": get_all_offboarding_track_statuses(db, employee_id),
    }
