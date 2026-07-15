"""
Owns the offboarding step sequence -- mirrors onboarding_orchestrator.py's
pattern: pre-track pipeline stages, then a fan-out into 4 parallel tracks
(HR/IT/Security/Manager), each populated with OffboardingTask rows.

Step order: Exit Request -> Access Discovery -> Risk Assessment ->
(fan out) HR Track / IT Track / Security Track / Manager Track.

Every task starts 'pending'. Approval is per-task, in the Approval
Dashboard only (mirrors onboarding's architecture change) -- there is
no Approval-table usage here anymore; that table is now fully retired
for both workflows. Employee status flips 'offboarding' -> 'exited'
via services.track_status.recompute_employee_offboarding_status once
every track is completed.
"""
import json
import datetime
from sqlalchemy.orm import Session
from app.models import (
    Employee, OffboardingTracker, ExitRequest, AccessRecommendation,
    AssetAllocation, RiskAssessment, AuditLog, OffboardingTask,
)
from app.agents.risk_assessor import assess_risk
from app.agents.team_farewell_agent import draft_team_farewell
from app.config import get_risk_factors

STEP_EXIT_REQUEST = "Exit Request"
STEP_ACCESS_DISCOVERY = "Access Discovery"
STEP_RISK_ASSESSMENT = "Risk Assessment"
STEP_HR_TRACK = "HR Track"
STEP_IT_TRACK = "IT Track"
STEP_SECURITY_TRACK = "Security Track"
STEP_MANAGER_TRACK = "Manager Track"

STEPS = [
    STEP_EXIT_REQUEST, STEP_ACCESS_DISCOVERY, STEP_RISK_ASSESSMENT,
    STEP_HR_TRACK, STEP_IT_TRACK, STEP_SECURITY_TRACK, STEP_MANAGER_TRACK,
]


def _mark(db: Session, employee_id: str, step: str, status: str):
    db.add(OffboardingTracker(employee_id=employee_id, step=step, status=status))
    db.commit()


def _audit(db: Session, employee_id: str, agent: str, action: str, detail: str = ""):
    db.add(AuditLog(employee_id=employee_id, agent=agent, action=action, detail=detail))
    db.commit()


def _add_task(db: Session, employee_id: str, track: str, task_name: str,
              is_mandatory: bool = True, is_ai_generated: bool = False, ai_recommendation: str = None,
              task_type: str = "simple", options: list = None, selected_options: list = None,
              category: str = None):
    """Every task starts 'pending' -- the Approval Dashboard is the only
    place status ever changes, exactly mirroring onboarding's pattern."""
    db.add(OffboardingTask(
        employee_id=employee_id, track=track, task_name=task_name, status="pending",
        is_mandatory=is_mandatory,
        is_ai_generated="true" if is_ai_generated else "false",
        ai_recommendation=ai_recommendation,
        task_type=task_type,
        options=json.dumps(options) if options is not None else None,
        selected_options=json.dumps(selected_options) if selected_options is not None else None,
        category=category,
    ))
    db.commit()


def run_offboarding(db: Session, employee_id: str, last_working_day: str = None,
                     exit_reason: str = None, sync_source: str = "manual"):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise ValueError(f"Employee {employee_id} not found")

    # 1. Exit Request
    db.add(ExitRequest(employee_id=employee_id, last_working_day=last_working_day,
                        exit_reason=exit_reason, sync_source=sync_source))
    db.commit()
    _mark(db, employee_id, STEP_EXIT_REQUEST, "completed")

    employee.status = "offboarding"
    db.commit()

    # 2. Access Discovery -- pull from this employee's own onboarding records
    _mark(db, employee_id, STEP_ACCESS_DISCOVERY, "running")
    access_record = (
        db.query(AccessRecommendation)
        .filter(AccessRecommendation.employee_id == employee_id)
        .order_by(AccessRecommendation.created_at.desc())
        .first()
    )
    asset_record = (
        db.query(AssetAllocation)
        .filter(AssetAllocation.employee_id == employee_id)
        .order_by(AssetAllocation.created_at.desc())
        .first()
    )
    has_admin_rights = access_record is not None and "Admin Groups" in (access_record.security_groups or "")

    risk_factors_config = get_risk_factors()
    role_factors = risk_factors_config.get(employee.role, {})
    has_legal_access = role_factors.get("legal_access", False)
    has_financial_access = role_factors.get("financial_access", False)
    has_client_data_access = role_factors.get("client_data_access", False)

    _mark(db, employee_id, STEP_ACCESS_DISCOVERY, "completed")
    _audit(db, employee_id, "Access Discovery", "Access inventory captured")

    # 3. Risk Assessment (Ollama, with fallback)
    _mark(db, employee_id, STEP_RISK_ASSESSMENT, "running")
    risk = assess_risk(has_admin_rights, has_client_data_access, has_financial_access, has_legal_access)
    db.add(RiskAssessment(employee_id=employee_id, risk_level=risk["risk_level"],
                           factors=json.dumps(risk["factors"]), reasoning=risk["reasoning"]))
    db.commit()
    _mark(db, employee_id, STEP_RISK_ASSESSMENT, "completed")
    _audit(db, employee_id, "Risk Agent", f"{risk['risk_level']} risk classified", risk["reasoning"])

    # --- HR track ---
    _mark(db, employee_id, STEP_HR_TRACK, "running")
    _add_task(db, employee_id, "HR", "Update Records")
    for item_name in ["NDA Reminder", "Client Confidentiality Reminder", "Exit Interview Completed"]:
        _add_task(db, employee_id, "HR", item_name, is_ai_generated=True, category="compliance",
                  ai_recommendation="Standard exit compliance item -- confirm before employee's last working day.")
    _mark(db, employee_id, STEP_HR_TRACK, "completed")
    _audit(db, employee_id, "HR Track", "Task list generated", "Tasks created for HR")

    # --- IT track ---
    _mark(db, employee_id, STEP_IT_TRACK, "running")
    applications = json.loads(access_record.applications) if access_record and access_record.applications else []
    _add_task(db, employee_id, "IT", "Disable User Account")
    _add_task(db, employee_id, "IT", "Revoke Applications", is_ai_generated=True,
              ai_recommendation=f"Applications to revoke: {', '.join(applications) if applications else 'none on record'}")
    asset_list = json.loads(asset_record.asset_list) if asset_record and asset_record.asset_list else []
    _add_task(db, employee_id, "IT", "Recover Assets", is_ai_generated=True,
              ai_recommendation=f"Assets to recover: {', '.join(asset_list) if asset_list else 'none on record'}")
    if asset_record:
        asset_record.status = "pending_return"
        asset_record.pending_return_at = datetime.datetime.utcnow()
        db.commit()
    _mark(db, employee_id, STEP_IT_TRACK, "completed")
    _audit(db, employee_id, "IT Track", "Task list generated", "Tasks created for IT")

    # --- Security track ---
    _mark(db, employee_id, STEP_SECURITY_TRACK, "running")
    security_groups = json.loads(access_record.security_groups) if access_record and access_record.security_groups else []
    _add_task(db, employee_id, "Security", "Revoke Security Groups", is_ai_generated=True,
              ai_recommendation=f"Groups to revoke: {', '.join(security_groups) if security_groups else 'none on record'}")
    urgency_note = "URGENT -- high risk profile, prioritize removal." if risk["risk_level"] == "High" else risk["reasoning"]
    _add_task(db, employee_id, "Security", "Privileged Access Removal", is_ai_generated=True,
              ai_recommendation=urgency_note)
    _mark(db, employee_id, STEP_SECURITY_TRACK, "completed")
    _audit(db, employee_id, "Security Track", "Task list generated", "Tasks created for Security")

    # --- Manager track ---
    _mark(db, employee_id, STEP_MANAGER_TRACK, "running")
    _add_task(db, employee_id, "Manager", "Knowledge Transfer")
    farewell = draft_team_farewell(employee.name, employee.role, employee.department, last_working_day)
    _add_task(db, employee_id, "Manager", "Team Communication", is_mandatory=False, is_ai_generated=True,
              ai_recommendation=farewell["message_text"])
    _mark(db, employee_id, STEP_MANAGER_TRACK, "completed")
    _audit(db, employee_id, "Manager Track", "Task list generated", "Tasks created for Manager")

    return {"status": "in_progress", "risk_level": risk["risk_level"]}
