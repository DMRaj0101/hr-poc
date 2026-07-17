"""
Validates the "Bank Account Details" document: extracts the Account
Holder Name field and fuzzy-matches it against the employee's name on
file in HRMS. Ported from Mohan's bank_details_check.py -- same
rule-based matching (rapidfuzz), wrapped as a reusable agent with the
standard call_ollama_json + fallback reasoning pattern.
"""
import re
import pdfplumber
from rapidfuzz import fuzz
from app.ai_client import call_ollama_json, OllamaError

MATCH_THRESHOLD = 95
PARTIAL_MATCH_THRESHOLD = 80

REASONING_PROMPT = """In one sentence, summarize this bank-details name
check for an HR reviewer: HRMS name "{hrms_name}", document name
"{pdf_name}", match score {score}, result {status}. Respond ONLY with
JSON: {{"reasoning": "<one sentence>"}}
"""


def extract_account_holder_name(pdf_path: str) -> str | None:
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"

    match = re.search(r"Account Holder Name\s*[:\-]?\s*([A-Za-z ]+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def validate_bank_details(file_path: str, hrms_name: str) -> dict:
    pdf_name = extract_account_holder_name(file_path)

    if not pdf_name:
        return {
            "status": "FAIL",
            "hrms_name": hrms_name,
            "document_name": None,
            "match_score": 0,
            "reasoning": "Could not find an 'Account Holder Name' field in the document.",
        }

    score = fuzz.ratio(hrms_name.upper().strip(), pdf_name.upper().strip())
    if score >= MATCH_THRESHOLD:
        match_status = "MATCH"
    elif score >= PARTIAL_MATCH_THRESHOLD:
        match_status = "PARTIAL_MATCH"
    else:
        match_status = "NOT_MATCH"

    overall_status = "PASS" if match_status == "MATCH" else ("NEEDS_REVIEW" if match_status == "PARTIAL_MATCH" else "FAIL")

    try:
        result = call_ollama_json(REASONING_PROMPT.format(
            hrms_name=hrms_name, pdf_name=pdf_name, score=score, status=match_status,
        ))
        reasoning = result.get("reasoning", "")
    except OllamaError:
        reasoning = f"HRMS name '{hrms_name}' vs document name '{pdf_name}' scored {score} -- {match_status}."

    return {
        "status": overall_status,
        "hrms_name": hrms_name,
        "document_name": pdf_name,
        "match_score": score,
        "match_status": match_status,
        "reasoning": reasoning,
    }
