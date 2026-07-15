"""
Generates the onboarding/offboarding summary report as PDF and stores it
under app/reports/. Uses reportlab -- lightweight, no external service needed.

Pulls tasks from OnboardingTask/OffboardingTask (whichever matches
report_type) -- NOT the retired ComplianceTask/Approval tables, which no
longer receive any data from either orchestrator. Shows every task's
approval status grouped by track, and compliance items called out
separately using the category="compliance" tag.
"""
import os
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from app.database import get_db
from app.models import Employee, AccessRecommendation, AssetAllocation, OnboardingTask, OffboardingTask, Report

router = APIRouter(prefix="/reports", tags=["reports"])
REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

TASK_MODEL_BY_REPORT_TYPE = {"onboarding": OnboardingTask, "offboarding": OffboardingTask}
TRACKS = ["HR", "IT", "Security", "Manager"]


def _generate_pdf(employee: Employee, access, assets, tasks_by_track: dict, report_type: str) -> str:
    filename = f"{employee.employee_id}_{report_type}.pdf"
    filepath = os.path.join(REPORTS_DIR, filename)
    c = canvas.Canvas(filepath, pagesize=letter)
    y = 750

    def line(text, size=11, gap=18):
        nonlocal y
        c.setFont("Helvetica", size)
        c.drawString(50, y, text)
        y -= gap
        if y < 50:  # crude page-break guard for employees with many tasks
            c.showPage()
            y = 750

    line(f"{report_type.title()} Summary Report", size=16, gap=30)
    line(f"Employee: {employee.name} ({employee.employee_id})")
    line(f"Department: {employee.department}   Role: {employee.role}")
    line(f"Office: {employee.office}   Manager: {employee.manager}")
    line(f"Source: {employee.sync_source}   Status: {employee.status}", gap=26)

    if access:
        line("Assigned Applications:", size=12)
        line(", ".join(json.loads(access.applications or "[]")), gap=22)
        line("Security Groups:", size=12)
        line(", ".join(json.loads(access.security_groups or "[]")), gap=22)

    if assets:
        line("Allocated Assets:", size=12)
        line(", ".join(json.loads(assets.asset_list or "[]")), gap=26)

    for track in TRACKS:
        tasks = tasks_by_track.get(track, [])
        if not tasks:
            continue
        line(f"{track} Track:", size=12)
        for t in tasks:
            tag = " [compliance]" if t.category == "compliance" else ""
            line(f"  - {t.task_name}{tag}: {t.status}", size=10, gap=14)
        y -= 8

    c.save()
    return filepath


@router.get("/{employee_id}")
def get_report_meta(employee_id: str, report_type: str = "onboarding", db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    if report_type not in TASK_MODEL_BY_REPORT_TYPE:
        raise HTTPException(status_code=400, detail="report_type must be 'onboarding' or 'offboarding'")

    access = db.query(AccessRecommendation).filter(AccessRecommendation.employee_id == employee_id).order_by(AccessRecommendation.created_at.desc()).first()
    assets = db.query(AssetAllocation).filter(AssetAllocation.employee_id == employee_id).order_by(AssetAllocation.created_at.desc()).first()

    task_model = TASK_MODEL_BY_REPORT_TYPE[report_type]
    tasks = db.query(task_model).filter(task_model.employee_id == employee_id).all()
    tasks_by_track: dict[str, list] = {}
    for t in tasks:
        tasks_by_track.setdefault(t.track, []).append(t)

    filepath = _generate_pdf(employee, access, assets, tasks_by_track, report_type)
    db.add(Report(employee_id=employee_id, report_type=report_type, file_path=filepath))
    db.commit()

    return {"employee_id": employee_id, "report_type": report_type, "file_path": filepath}


@router.get("/{employee_id}/download")
def download_report(employee_id: str, report_type: str = "onboarding", db: Session = Depends(get_db)):
    record = (
        db.query(Report)
        .filter(Report.employee_id == employee_id, Report.report_type == report_type)
        .order_by(Report.generated_at.desc())
        .first()
    )
    if not record or not os.path.exists(record.file_path):
        raise HTTPException(status_code=404, detail="Report not generated yet -- call GET /reports/{employee_id} first")
    return FileResponse(record.file_path, media_type="application/pdf", filename=os.path.basename(record.file_path))
