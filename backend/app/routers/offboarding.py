"""
Mirrors routers/onboarding.py's task endpoints exactly, backed by
OffboardingTask instead of OnboardingTask. Same rules apply: tasks are
read-only from this router's status/tasks endpoints, the Approval
Dashboard is the only writer via decide/selection.
"""
import datetime
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import OffboardingTracker, Employee, OffboardingTask, AssetAllocation
from app.schemas.employee import ExitRequestCreate, TaskDecision, TaskSelectionUpdate
from app.orchestrators.offboarding_orchestrator import run_offboarding
from app.services.track_status import get_all_offboarding_track_statuses, recompute_employee_offboarding_status

router = APIRouter(prefix="/offboarding", tags=["offboarding"])


@router.post("/{employee_id}/start")
def start_offboarding(employee_id: str, payload: ExitRequestCreate, db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return run_offboarding(db, employee_id, payload.last_working_day, payload.exit_reason, "manual")


@router.get("/{employee_id}/status")
def offboarding_status(employee_id: str, db: Session = Depends(get_db)):
    """Read-only -- drives the Offboarding Tracker timeline UI."""
    rows = (
        db.query(OffboardingTracker)
        .filter(OffboardingTracker.employee_id == employee_id)
        .order_by(OffboardingTracker.timestamp.asc())
        .all()
    )
    return [{"step": r.step, "status": r.status, "timestamp": r.timestamp} for r in rows]


@router.get("/{employee_id}/tasks")
def get_tasks(employee_id: str, db: Session = Depends(get_db)):
    """Same shape as GET /onboarding/{id}/tasks -- tasks grouped by
    track, plus each track's live-computed status."""
    tasks = db.query(OffboardingTask).filter(OffboardingTask.employee_id == employee_id).all()
    by_track: dict[str, list] = {"HR": [], "IT": [], "Security": [], "Manager": []}
    for t in tasks:
        by_track.setdefault(t.track, []).append({
            "id": t.id, "task_name": t.task_name, "status": t.status,
            "is_mandatory": t.is_mandatory,
            "is_ai_generated": t.is_ai_generated == "true",
            "ai_recommendation": t.ai_recommendation,
            "task_type": t.task_type,
            "options": json.loads(t.options) if t.options else None,
            "selected_options": json.loads(t.selected_options) if t.selected_options else None,
            "category": t.category,
            "created_at": t.created_at, "decided_at": t.decided_at,
        })

    track_statuses = get_all_offboarding_track_statuses(db, employee_id)
    return {
        "tasks": by_track,
        "track_status": track_statuses,
    }


@router.patch("/{employee_id}/tasks/{task_id}/selection")
def update_task_selection(employee_id: str, task_id: str, payload: TaskSelectionUpdate, db: Session = Depends(get_db)):
    task = db.query(OffboardingTask).filter(
        OffboardingTask.id == task_id, OffboardingTask.employee_id == employee_id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.task_type not in ("multi_select", "single_select"):
        raise HTTPException(status_code=400, detail="This task does not support selection editing")
    if task.status != "pending":
        raise HTTPException(status_code=400, detail="Cannot change selection after a task has been decided")
    if task.task_type == "single_select" and len(payload.selected_options) != 1:
        raise HTTPException(status_code=400, detail="single_select tasks require exactly one selected option")

    task.selected_options = json.dumps(payload.selected_options)
    db.commit()
    return {"id": task.id, "selected_options": payload.selected_options}


@router.post("/{employee_id}/tasks/{task_id}/decide")
def decide_task(employee_id: str, task_id: str, payload: TaskDecision, db: Session = Depends(get_db)):
    """The ONLY place offboarding task status changes -- called from the
    Approval Dashboard exclusively, mirroring onboarding's rule."""
    task = db.query(OffboardingTask).filter(
        OffboardingTask.id == task_id, OffboardingTask.employee_id == employee_id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if payload.status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="status must be 'approved' or 'rejected'")

    task.status = payload.status
    task.decided_at = datetime.datetime.utcnow()
    db.commit()

    # Approving "Recover Assets" is the real-world trigger for the asset
    # actually being returned -- without this, AssetAllocation stayed
    # stuck at "pending_return" forever, even after IT approved the
    # task, which would make AI Insights' overdue-asset check flag it
    # forever regardless of approval.
    if task.track == "IT" and task.task_name == "Recover Assets" and payload.status == "approved":
        asset_record = (
            db.query(AssetAllocation)
            .filter(AssetAllocation.employee_id == employee_id)
            .order_by(AssetAllocation.created_at.desc())
            .first()
        )
        if asset_record:
            asset_record.status = "returned"
            db.commit()

    recompute_employee_offboarding_status(db, employee_id)

    return {"id": task.id, "task_name": task.task_name, "status": task.status}
