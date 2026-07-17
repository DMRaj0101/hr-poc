from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import datetime
import os
import re
import json
from app import email_client
from app.config import get_document_keywords, get_required_documents
from app.database import get_db
from app.models import OnboardingTracker, Employee, EmployeeDocument, OnboardingTask, DocumentRequestEmail, ReceivedAttachment
from app.schemas.employee import TaskDecision, TaskSelectionUpdate, EmailDraftUpdate
from app.orchestrators.onboarding_orchestrator import run_onboarding, resume_after_documents, create_document_review_task, resume_after_documents, _draft_and_queue_missing_document_email
from app.services.track_status import get_all_track_statuses, recompute_employee_status
from app.agents.document_content_validator import validate_document
from app.agents.resume_validation_agent import validate_resume

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.post("/{employee_id}/start")
def start_onboarding(employee_id: str, db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return run_onboarding(db, employee_id)


@router.get("/{employee_id}/status")
def onboarding_status(employee_id: str, db: Session = Depends(get_db)):
    """Frontend polls this to drive the Onboarding Tracker timeline UI.
    Read-only -- the Tracker never writes through this or any other
    onboarding endpoint anymore; only the Approval Dashboard's decide
    endpoint changes task state."""
    rows = (
        db.query(OnboardingTracker)
        .filter(OnboardingTracker.employee_id == employee_id)
        .order_by(OnboardingTracker.timestamp.asc())
        .all()
    )
    return [{"step": r.step, "status": r.status, "timestamp": r.timestamp} for r in rows]


@router.get("/{employee_id}/documents")
def get_document_status(employee_id: str, db: Session = Depends(get_db)):
    """Shows required-document status. Email drafting was removed --
    HR reviews document status directly and marks received, no
    simulated email in between."""
    docs = db.query(EmployeeDocument).filter(EmployeeDocument.employee_id == employee_id).all()
    return {
        "documents": [
            {"document_name": d.document_name, "status": d.status,
             "requested_at": d.requested_at, "received_at": d.received_at,
             "validation_status": d.validation_status,
             "validation_detail": json.loads(d.validation_detail) if d.validation_detail else None}
            for d in docs
        ],
    }


# @router.post("/{employee_id}/documents/mark-received")
# def mark_documents_received(employee_id: str, db: Session = Depends(get_db)):
#     """HR confirms documents were received -- resumes a paused pipeline."""
#     employee = db.query(Employee).filter(Employee.id == employee_id).first()
#     if not employee:
#         raise HTTPException(status_code=404, detail="Employee not found")
#     try:
#         return resume_after_documents(db, employee_id)
#     except ValueError as e:
#         raise HTTPException(status_code=400, detail=str(e))


@router.get("/{employee_id}/tasks")
def get_tasks(employee_id: str, db: Session = Depends(get_db)):
    """Tasks grouped by track, PLUS each track's live-computed status --
    the single source of truth both the read-only Tracker and the
    Approval Dashboard read from. Track status is never stored, always
    computed fresh from task state (see services/track_status.py).

    options/selected_options are parsed from JSON here so the frontend
    gets real arrays, not JSON strings -- multi_select/single_select
    tasks only, null for 'simple' tasks."""
    import json as _json
    tasks = db.query(OnboardingTask).filter(OnboardingTask.employee_id == employee_id).all()
    by_track: dict[str, list] = {"HR": [], "IT": [], "Security": [], "Manager": []}
    for t in tasks:
        entry = {
            "id": t.id, "task_name": t.task_name, "status": t.status,
            "is_mandatory": t.is_mandatory,
            "is_ai_generated": t.is_ai_generated == "true",
            "ai_recommendation": t.ai_recommendation,
            "task_type": t.task_type,
            "options": _json.loads(t.options) if t.options else None,
            "selected_options": _json.loads(t.selected_options) if t.selected_options else None,
            "category": t.category,
            "created_at": t.created_at, "decided_at": t.decided_at,
        }

        if t.task_type == "email_draft":
            email_record = (
                db.query(DocumentRequestEmail)
                .filter(DocumentRequestEmail.employee_id == employee_id)
                .order_by(DocumentRequestEmail.generated_at.desc())
                .first()
            )
            if email_record:
                entry["email_subject"] = email_record.subject
                entry["email_body"] = email_record.body
                entry["email_status"] = email_record.status

        by_track.setdefault(t.track, []).append(entry)

    track_statuses = get_all_track_statuses(db, employee_id)
    return {
        "tasks": by_track,
        "track_status": track_statuses,
    }


@router.patch("/{employee_id}/tasks/{task_id}/selection")
def update_task_selection(employee_id: str, task_id: str, payload: TaskSelectionUpdate, db: Session = Depends(get_db)):
    """Lets the approver edit a multi_select/single_select task's choice
    before deciding -- the 'AI suggests, human can change it' pattern.
    Locked once the task has been decided, so history can't be silently
    rewritten after approval/rejection."""
    task = db.query(OnboardingTask).filter(
        OnboardingTask.id == task_id, OnboardingTask.employee_id == employee_id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.task_type not in ("multi_select", "single_select"):
        raise HTTPException(status_code=400, detail="This task does not support selection editing")
    if task.status != "pending":
        raise HTTPException(status_code=400, detail="Cannot change selection after a task has been decided")

    import json as _json
    if task.task_type == "single_select" and len(payload.selected_options) != 1:
        raise HTTPException(status_code=400, detail="single_select tasks require exactly one selected option")

    task.selected_options = _json.dumps(payload.selected_options)
    db.commit()
    return {"id": task.id, "selected_options": payload.selected_options}


@router.post("/{employee_id}/tasks/{task_id}/decide")
def decide_task(employee_id: str, task_id: str, payload: TaskDecision, db: Session = Depends(get_db)):
    """The ONLY place onboarding task status changes -- called from the
    Approval Dashboard exclusively. The Tracker has no write path
    anymore (see architecture change #5/#7)."""
    task = db.query(OnboardingTask).filter(
        OnboardingTask.id == task_id, OnboardingTask.employee_id == employee_id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if payload.status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="status must be 'approved' or 'rejected'")

    task.status = payload.status
    task.decided_at = datetime.datetime.utcnow()
    db.commit()

    if task.task_type == "email_draft" and payload.status == "approved":
        email_record = (
            db.query(DocumentRequestEmail)
            .filter(DocumentRequestEmail.employee_id == employee_id, DocumentRequestEmail.status == "drafted")
            .order_by(DocumentRequestEmail.generated_at.desc())
            .first()
        )
        if email_record:
            employee = db.query(Employee).filter(Employee.id == employee_id).first()
            try:
                message_id = email_client.send_email(employee.email, email_record.subject, email_record.body)
                email_record.status = "sent"
                email_record.message_id = message_id
                email_record.sent_at = datetime.datetime.utcnow()
                db.commit()
            except email_client.EmailClientError as e:
                raise HTTPException(status_code=502, detail=f"Email send failed: {e}")

    if task.task_name == "Review Received Documents" and payload.status == "approved":
        under_review_docs = db.query(EmployeeDocument).filter(
            EmployeeDocument.employee_id == employee_id, EmployeeDocument.status == "under_review"
        ).all()
        for doc in under_review_docs:
            doc.status = "received"
        db.commit()
        try:
            resume_after_documents(db, employee_id)
        except ValueError:
            pass

    recompute_employee_status(db, employee_id)

    return {"id": task.id, "task_name": task.task_name, "status": task.status}

@router.patch("/{employee_id}/documents/email-draft")
def update_email_draft(employee_id: str, payload: EmailDraftUpdate, db: Session = Depends(get_db)):
    email_record = (
        db.query(DocumentRequestEmail)
        .filter(DocumentRequestEmail.employee_id == employee_id, DocumentRequestEmail.status == "drafted")
        .order_by(DocumentRequestEmail.generated_at.desc())
        .first()
    )
    if not email_record:
        raise HTTPException(status_code=404, detail="No drafted email found for this employee")
    email_record.subject = payload.subject
    email_record.body = payload.body
    db.commit()
    return {"subject": email_record.subject, "body": email_record.body}


def _safe_filename(employee_id: str, doc_index: int, extension: str) -> str:
    return f"{employee_id}_{doc_index}{extension}"


def _run_content_validation(db: Session, employee: Employee, doc: EmployeeDocument):
    """Runs the appropriate validation agent (resume/bank_details/ssn/
    signature/generic -- see document_content_validator.py) against a
    document as soon as its file_path is known, and stores the result
    directly on the EmployeeDocument row. Never raises -- a validation
    failure just surfaces as NEEDS_REVIEW for a human to look at."""
    if not doc.file_path:
        return
    result = validate_document(doc.document_name, doc.file_path, employee)
    doc.validation_status = result.get("status", "NEEDS_REVIEW")
    doc.validation_detail = json.dumps(result)
    db.commit()

@router.post("/{employee_id}/documents/check-inbox")
def check_inbox_for_employee(employee_id: str, db: Session = Depends(get_db)):
    email_record = (
        db.query(DocumentRequestEmail)
        .filter(DocumentRequestEmail.employee_id == employee_id, DocumentRequestEmail.status == "sent")
        .order_by(DocumentRequestEmail.sent_at.desc())
        .first()
    )
    if not email_record or not email_record.message_id:
        return {"checked": True, "reply_found": False, "reason": "No sent email awaiting reply for this employee"}

    claimed = db.query(DocumentRequestEmail).filter(
        DocumentRequestEmail.id == email_record.id, DocumentRequestEmail.status == "sent"
    ).update({"status": "checking"})
    db.commit()
    if claimed == 0:
        return {"checked": True, "reply_found": False, "reason": "Already being checked by another request right now"}

    try:
        reply = email_client.check_for_reply(email_record.message_id)
    except email_client.EmailClientError as e:
        email_record.status = "sent"
        db.commit()
        raise HTTPException(status_code=502, detail=str(e))

    if not reply or not reply["attachments"]:
        email_record.status = "sent"
        db.commit()
        return {"checked": True, "reply_found": False}

    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", employee_id)
    os.makedirs(upload_dir, exist_ok=True)

    pending_docs = db.query(EmployeeDocument).filter(
        EmployeeDocument.employee_id == employee_id, EmployeeDocument.status == "pending"
    ).all()

    saved_attachments = []
    for idx, attachment in enumerate(reply["attachments"]):
        safe_name = _safe_filename(employee_id, idx, attachment["extension"])
        filepath = os.path.join(upload_dir, safe_name)
        with open(filepath, "wb") as f:
            f.write(attachment["content"])
        record = ReceivedAttachment(
            employee_id=employee_id, file_path=filepath,
            original_filename=attachment["original_filename"],
        )
        db.add(record)
        saved_attachments.append(record)
    db.commit()

    unassigned_attachments = list(saved_attachments)
    newly_matched = []

    if len(saved_attachments) == 1 and len(pending_docs) == 1:
        # Genuinely unambiguous regardless of filename -- skip keyword matching
        attachment_record = saved_attachments[0]
        doc = pending_docs[0]
        doc.status = "under_review"
        doc.file_path = attachment_record.file_path
        attachment_record.matched_document_name = doc.document_name
        newly_matched.append(doc.document_name)
        unassigned_attachments.remove(attachment_record)
        db.commit()
        _run_content_validation(db, employee, doc)
    else:
        # Interim filename-keyword heuristic -- replaced below by real
        # content verification once a document is matched.
        keywords_by_doc = get_document_keywords()
        for doc in pending_docs:
            match = next(
                (a for a in unassigned_attachments
                 if _match_attachment_by_keywords(doc.document_name, a.original_filename, keywords_by_doc)),
                None,
            )
            if match:
                doc.status = "under_review"
                doc.file_path = match.file_path
                match.matched_document_name = doc.document_name
                newly_matched.append(doc.document_name)
                unassigned_attachments.remove(match)
                db.commit()
                _run_content_validation(db, employee, doc)

    db.commit()

    email_record.status = "replied"
    email_record.replied_at = datetime.datetime.utcnow()
    db.commit()

    # Whatever's still pending after matching -- automatically draft a
    # follow-up email requesting just those, so the employee doesn't
    # have to guess what's still outstanding. Self-sustaining loop.
    still_missing = [d.document_name for d in pending_docs if d.status == "pending"]
    if still_missing:
        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        _draft_and_queue_missing_document_email(db, employee, still_missing)

    if newly_matched:
        create_document_review_task(db, employee_id, newly_matched, unmatched_count=len(unassigned_attachments))

    return {
        "checked": True, "reply_found": True,
        "attachments_received": len(saved_attachments),
        "auto_matched": newly_matched,
        "still_missing": still_missing,
        "needs_manual_matching": len(unassigned_attachments),
    }

@router.get("/{employee_id}/documents/{doc_id}/file")
def download_received_document(employee_id: str, doc_id: str, db: Session = Depends(get_db)):
    doc = db.query(EmployeeDocument).filter(
        EmployeeDocument.id == doc_id, EmployeeDocument.employee_id == employee_id
    ).first()
    if not doc or not doc.file_path:
        raise HTTPException(status_code=404, detail="No file on record for this document")
    if not os.path.exists(doc.file_path):
        raise HTTPException(status_code=404, detail="File missing from disk")
    return FileResponse(doc.file_path)

@router.post("/{employee_id}/documents/{doc_id}/match-attachment")
def match_attachment_to_document(employee_id: str, doc_id: str, attachment_id: str, db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    doc = db.query(EmployeeDocument).filter(
        EmployeeDocument.id == doc_id, EmployeeDocument.employee_id == employee_id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    attachment_record = db.query(ReceivedAttachment).filter(
        ReceivedAttachment.id == attachment_id, ReceivedAttachment.employee_id == employee_id,
        ReceivedAttachment.matched_document_name.is_(None),
    ).first()
    if not attachment_record:
        raise HTTPException(status_code=404, detail="Attachment not found or already matched to a document")

    doc.status = "under_review"
    doc.file_path = attachment_record.file_path
    attachment_record.matched_document_name = doc.document_name
    db.commit()

    _run_content_validation(db, employee, doc)

    return {"document_name": doc.document_name, "matched": True, "validation_status": doc.validation_status}


@router.get("/{employee_id}/documents/unmatched-attachments")
def get_unmatched_attachments(employee_id: str, db: Session = Depends(get_db)):
    attachments = db.query(ReceivedAttachment).filter(
        ReceivedAttachment.employee_id == employee_id, ReceivedAttachment.matched_document_name.is_(None),
    ).all()
    return [{"id": a.id, "original_filename": a.original_filename, "received_at": a.received_at} for a in attachments]

def _match_attachment_by_keywords(document_name: str, filename: str, keywords_by_doc: dict) -> bool:
    filename_lower = (filename or "").lower()
    keywords = keywords_by_doc.get(document_name, [])
    return any(kw in filename_lower for kw in keywords)


@router.post("/{employee_id}/documents/{document_name}/upload")
def upload_document(employee_id: str, document_name: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Direct upload path (no email round-trip) -- saves the file, sets
    the EmployeeDocument to under_review, and runs the same content
    validation as the email-reply path."""
    if document_name not in get_required_documents():
        raise HTTPException(status_code=400, detail=f"'{document_name}' is not a recognized required document")

    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    doc = db.query(EmployeeDocument).filter(
        EmployeeDocument.employee_id == employee_id, EmployeeDocument.document_name == document_name
    ).first()
    if not doc:
        doc = EmployeeDocument(employee_id=employee_id, document_name=document_name, status="pending")
        db.add(doc)
        db.commit()

    upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", employee_id)
    os.makedirs(upload_dir, exist_ok=True)
    extension = os.path.splitext(file.filename or "")[1] or ".pdf"
    filepath = os.path.join(upload_dir, f"{employee_id}_{document_name.replace(' ', '_')}{extension}")
    with open(filepath, "wb") as f:
        f.write(file.file.read())

    doc.status = "under_review"
    doc.file_path = filepath
    db.commit()

    _run_content_validation(db, employee, doc)

    create_document_review_task(db, employee_id, [document_name])

    return {
        "document_name": doc.document_name, "status": doc.status,
        "validation_status": doc.validation_status,
        "validation_detail": json.loads(doc.validation_detail) if doc.validation_detail else None,
    }


@router.post("/{employee_id}/resume/validate")
def validate_employee_resume(employee_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Standalone resume check -- Resume isn't one of the required
    onboarding documents, so this doesn't gate onboarding progress.
    Result is returned for HR to review and logged to the audit log."""
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", employee_id)
    os.makedirs(upload_dir, exist_ok=True)
    extension = os.path.splitext(file.filename or "")[1] or ".pdf"
    filepath = os.path.join(upload_dir, f"{employee_id}_resume{extension}")
    with open(filepath, "wb") as f:
        f.write(file.file.read())

    result = validate_resume(filepath, employee.name, employee.years_of_experience)

    from app.models import AuditLog
    db.add(AuditLog(
        employee_id=employee_id, agent="Resume Validation Agent",
        action=f"Resume validation: {result['status']}", detail=json.dumps(result),
    ))
    db.commit()

    return result