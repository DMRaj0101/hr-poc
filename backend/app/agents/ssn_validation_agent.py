"""
Validates the "Government ID Proof" document: extracts an SSN-shaped
number from the (often scanned) PDF and compares it to employee.ssn_number
from HRMS. Ported from Mohan's ssn_numeber_check.py -- reuses the shared
OCR-aware text extractor (app/agents/pdf_text_utils.py) instead of
hardcoding easyocr calls per-script, everything else (normalization,
comparison) kept as designed.
"""
import re
from app.agents.pdf_text_utils import extract_text
from app.ai_client import call_ollama_json, OllamaError

REASONING_PROMPT = """In one sentence, summarize this SSN document check
for an HR reviewer: document SSN "{doc_ssn}", HRMS SSN "{hrms_ssn}",
match: {matched}. Respond ONLY with JSON: {{"reasoning": "<one sentence>"}}
"""


def normalize_ssn(ssn: str) -> str:
    digits = re.sub(r"\D", "", ssn or "")
    if len(digits) == 9:
        return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
    return ""


def validate_ssn(file_path: str, hrms_ssn: str) -> dict:
    hrms_ssn_normalized = normalize_ssn(hrms_ssn)

    text = extract_text(file_path)
    match = re.search(r"\d{3}[- ]?\d{2}[- ]?\d{4}", text)
    doc_ssn = normalize_ssn(match.group()) if match else ""

    if not doc_ssn:
        return {
            "status": "FAIL",
            "document_ssn": None,
            "hrms_ssn": hrms_ssn_normalized,
            "reasoning": "No SSN-shaped number could be found in the document (including after OCR).",
        }

    matched = doc_ssn == hrms_ssn_normalized
    overall_status = "PASS" if matched else "FAIL"

    try:
        result = call_ollama_json(REASONING_PROMPT.format(
            doc_ssn=doc_ssn, hrms_ssn=hrms_ssn_normalized, matched=matched,
        ))
        reasoning = result.get("reasoning", "")
    except OllamaError:
        reasoning = f"Document SSN {'matches' if matched else 'does not match'} HRMS record."

    return {
        "status": overall_status,
        "document_ssn": doc_ssn,
        "hrms_ssn": hrms_ssn_normalized,
        "matched": matched,
        "reasoning": reasoning,
    }
