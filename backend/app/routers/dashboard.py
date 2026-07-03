"""
Executive Dashboard summary endpoint. Trimmed from the original 11-widget
plan to 6 widgets + 2 charts that this schema can answer honestly with
the data currently being generated (see architecture doc, Screen 1 MVP scope).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import Employee, Approval, RiskAssessment, ComplianceTask

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def get_dashboard_summary(db: Session = Depends(get_db)):
    total_employees = db.query(Employee).count()
    onboarding_in_progress = db.query(Employee).filter(Employee.status == "onboarding").count()
    offboarding_in_progress = db.query(Employee).filter(Employee.status == "offboarding").count()
    pending_approvals = db.query(Approval).filter(Approval.status == "pending").count()
    high_risk_employees = db.query(RiskAssessment).filter(RiskAssessment.risk_level == "High").count()

    total_tasks = db.query(ComplianceTask).count()
    completed_tasks = db.query(ComplianceTask).filter(ComplianceTask.status == "completed").count()
    compliance_completion_pct = round((completed_tasks / total_tasks * 100), 1) if total_tasks else 0.0

    department_rows = (
        db.query(Employee.department, func.count(Employee.id))
        .group_by(Employee.department)
        .all()
    )
    role_rows = (
        db.query(Employee.role, func.count(Employee.id))
        .filter(Employee.role.isnot(None))
        .group_by(Employee.role)
        .all()
    )

    return {
        "total_employees": total_employees,
        "onboarding_in_progress": onboarding_in_progress,
        "offboarding_in_progress": offboarding_in_progress,
        "pending_approvals": pending_approvals,
        "high_risk_employees": high_risk_employees,
        "compliance_completion_pct": compliance_completion_pct,
        "department_distribution": [{"name": d or "Unassigned", "count": c} for d, c in department_rows],
        "role_distribution": [{"name": r, "count": c} for r, c in role_rows],
    }