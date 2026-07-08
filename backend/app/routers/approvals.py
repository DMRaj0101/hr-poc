from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import datetime
from app.database import get_db
from app.models import Approval, OnboardingTracker
from app.schemas.employee import ApprovalDecision

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("/{employee_id}")
def get_approvals(employee_id: str, db: Session = Depends(get_db)):
    rows = db.query(Approval).filter(Approval.employee_id == employee_id).all()
    return [
        {"approver_role": r.approver_role, "workflow_type": r.workflow_type, "status": r.status}
        for r in rows
    ]


@router.post("/{employee_id}/{approver_role}/decide")
def decide_approval(employee_id: str, approver_role: str, payload: ApprovalDecision, db: Session = Depends(get_db)):
    record = (
        db.query(Approval)
        .filter(Approval.employee_id == employee_id, Approval.approver_role == approver_role)
        .order_by(Approval.id.desc())
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Approval record not found")
    if payload.status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="status must be 'approved' or 'rejected'")
    record.status = payload.status
    record.decided_at = datetime.datetime.utcnow()
    db.commit()

    # Mirror Manager/IT approval decisions onto the onboarding tracker so
    # profile completion % can actually reach 100.
    if record.workflow_type == "onboarding" and approver_role in ("Manager", "IT") and payload.status == "approved":
        db.add(OnboardingTracker(
            employee_id=employee_id, step=f"{approver_role} Approval", status="completed"
        ))
        db.commit()

    return {"employee_id": employee_id, "approver_role": approver_role, "status": record.status}