"""
Compliance Dashboard. Aggregates every compliance item (category="compliance"
tasks) across BOTH onboarding and offboarding, for every employee -- a
monitoring view distinct from the Approval Dashboard's per-role action
queue. All compliance items live under the HR track by design (see the
architecture decision to isolate compliance ownership under HR), so this
endpoint only ever looks at HR-track, category="compliance" rows.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Employee, OnboardingTask, OffboardingTask

router = APIRouter(prefix="/compliance", tags=["compliance"])


def _compliance_rows(db: Session, task_model, workflow_type: str):
    tasks = (
        db.query(task_model)
        .filter(task_model.track == "HR", task_model.category == "compliance")
        .all()
    )
    by_employee: dict[str, list] = {}
    for t in tasks:
        by_employee.setdefault(t.employee_id, []).append(t)

    rows = []
    for employee_id, task_list in by_employee.items():
        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            continue
        approved = sum(1 for t in task_list if t.status == "approved")
        rows.append({
            "employee_id": employee.id, "employee_name": employee.name,
            "department": employee.department, "workflow_type": workflow_type,
            "items": [{"task_name": t.task_name, "status": t.status} for t in task_list],
            "completion_pct": round((approved / len(task_list)) * 100) if task_list else 0,
        })
    return rows


@router.get("/summary")
def get_compliance_summary(db: Session = Depends(get_db)):
    rows = _compliance_rows(db, OnboardingTask, "onboarding") + _compliance_rows(db, OffboardingTask, "offboarding")

    total_items = sum(len(r["items"]) for r in rows)
    approved_items = sum(sum(1 for i in r["items"] if i["status"] == "approved") for r in rows)
    overall_pct = round((approved_items / total_items) * 100) if total_items else 0

    return {
        "overall_completion_pct": overall_pct,
        "total_items": total_items,
        "approved_items": approved_items,
        "employees": rows,
    }
