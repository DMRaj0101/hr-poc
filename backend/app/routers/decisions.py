"""
AI Decision Center. Consolidates every AI reasoning trail for one
employee into a single view -- role classification (with confidence
score), access/project recommendation reasoning, risk assessment
reasoning (offboarding) -- instead of that reasoning being scattered
across Profile/Tracker/Approvals. No new AI calls happen here; this is
purely a read/aggregation layer over data that already exists.
"""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    Employee, RoleClassification, AccessRecommendation, RiskAssessment,
    OnboardingTask, AuditLog,
)

router = APIRouter(prefix="/employees", tags=["decisions"])


@router.get("/{employee_id}/decisions")
def get_decisions(employee_id: str, db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    role_classification = (
        db.query(RoleClassification)
        .filter(RoleClassification.employee_id == employee_id)
        .order_by(RoleClassification.created_at.desc())
        .first()
    )
    # If HRMS provided the role directly, there's no RoleClassification
    # row (AI never ran) -- surface that fact explicitly rather than
    # showing a blank/missing section.
    if role_classification:
        role_decision = {
            "source": "ai_fallback",
            "predicted_role": role_classification.predicted_role,
            "confidence": role_classification.confidence,
            "reasoning": role_classification.reasoning,
        }
    else:
        role_decision = {
            "source": "hrms_provided",
            "predicted_role": employee.role,
            "confidence": None,
            "reasoning": "Role came directly from HRMS; AI classification was not needed.",
        }

    access = (
        db.query(AccessRecommendation)
        .filter(AccessRecommendation.employee_id == employee_id)
        .order_by(AccessRecommendation.created_at.desc())
        .first()
    )
    access_decision = {"reasoning": access.reasoning} if access else None

    project_task = (
        db.query(OnboardingTask)
        .filter(OnboardingTask.employee_id == employee_id, OnboardingTask.task_name == "Project Recommendation")
        .order_by(OnboardingTask.created_at.desc())
        .first()
    )
    project_decision = (
        {"reasoning": project_task.ai_recommendation,
         "selected": json.loads(project_task.selected_options) if project_task.selected_options else None}
        if project_task else None
    )

    risk = (
        db.query(RiskAssessment)
        .filter(RiskAssessment.employee_id == employee_id)
        .order_by(RiskAssessment.created_at.desc())
        .first()
    )
    risk_decision = (
        {"risk_level": risk.risk_level, "factors": json.loads(risk.factors) if risk.factors else [],
         "reasoning": risk.reasoning}
        if risk else None
    )

    timeline = (
        db.query(AuditLog)
        .filter(AuditLog.employee_id == employee_id)
        .order_by(AuditLog.timestamp.asc())
        .all()
    )

    return {
        "employee_name": employee.name,
        "role_decision": role_decision,
        "access_decision": access_decision,
        "project_decision": project_decision,
        "risk_decision": risk_decision,
        "timeline": [
            {"timestamp": t.timestamp, "agent": t.agent, "action": t.action, "detail": t.detail}
            for t in timeline
        ],
    }
