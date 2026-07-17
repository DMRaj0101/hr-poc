"""
Single entry point the rest of the app calls once a required document's
file_path is populated (auto-matched from an email reply, manually
matched by HR, or uploaded directly). Looks up which validation agent
applies via config_data/document_validators.json and runs it.

This is what replaces the old filename-keyword-only heuristic in
routers/onboarding.py with real content verification, per the plan
noted there ("Mohan's real document validator will replace this").

Every branch is defensive: if the PDF is unreadable/corrupt or an
agent raises, we return NEEDS_REVIEW rather than crashing the request
or silently marking something PASS -- a human always gets to see it
in the Approval Dashboard either way.
"""
from app.config import get_document_validator_map
from app.agents.resume_validation_agent import validate_resume
from app.agents.bank_details_validation_agent import validate_bank_details
from app.agents.ssn_validation_agent import validate_ssn
from app.agents.signature_validation_agent import validate_signature


def _validate_generic(file_path: str, employee) -> dict:
    """For document types with no dedicated script yet (e.g. Address
    Proof, Educational Certificates): just confirm the file is a
    readable, non-empty PDF. Extend this with a real check (e.g. name
    matching via OCR, same pattern as ssn_validation_agent) whenever a
    dedicated script for that document type exists."""
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            has_text = any((p.extract_text() or "").strip() for p in pdf.pages)
        return {
            "status": "NEEDS_REVIEW",
            "reasoning": "No dedicated content-validation agent for this document type yet -- file received and readable, please review manually.",
            "has_extractable_text": has_text,
        }
    except Exception as e:
        return {"status": "NEEDS_REVIEW", "reasoning": f"Could not open file for review: {e}"}


def validate_document(document_name: str, file_path: str, employee) -> dict:
    """
    employee: the Employee SQLAlchemy row (uses employee.name,
    employee.years_of_experience, employee.ssn_number as ground truth).
    """
    validator_map = get_document_validator_map()
    validator_key = validator_map.get(document_name, "generic")

    try:
        if validator_key == "bank_details":
            return validate_bank_details(file_path, employee.name)
        if validator_key == "ssn":
            return validate_ssn(file_path, employee.ssn_number)
        if validator_key == "signature":
            return validate_signature(file_path)
        return _validate_generic(file_path, employee)
    except Exception as e:
        # A malformed/unreadable file should never block or crash the
        # pipeline -- it just needs a human to look at it.
        return {"status": "NEEDS_REVIEW", "reasoning": f"Validation agent failed to process this file: {e}"}
