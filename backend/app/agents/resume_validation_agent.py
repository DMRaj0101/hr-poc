"""
Validates a candidate's resume against HRMS. Extracts structured data
ONLY (name, years of experience) -- this agent does not judge resume
quality or content, only that it's genuinely this candidate's resume
and that the claimed experience roughly matches what HRMS has on file.

Ported from Mohan's resume_extractor.py (rule-based matching kept
exactly as designed -- name similarity via difflib + experience delta);
the only addition is a one-line AI-written reasoning summary, with a
rule-based fallback if Ollama is unavailable, matching every other
agent in app/agents/.
"""
import re
import difflib
import pdfplumber
from app.ai_client import call_ollama_json, OllamaError

NAME_SIMILARITY_THRESHOLD = 0.85

REASONING_PROMPT = """In one sentence, summarize this resume validation
result for an HR reviewer: name match {name_match} (similarity {similarity}%),
experience match {experience_match} (resume claims {resume_exp} years,
HRMS has {hrms_exp} years). Respond ONLY with JSON:
{{"reasoning": "<one sentence>"}}
"""


def _normalize_name(name: str) -> str:
    return " ".join((name or "").lower().split())


def _name_similarity(name1: str, name2: str) -> float:
    return difflib.SequenceMatcher(None, _normalize_name(name1), _normalize_name(name2)).ratio()


def extract_resume_details(pdf_path: str) -> dict:
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    name = lines[0] if lines else ""

    exp_match = re.search(r"(\d+)\s+years?", text, re.IGNORECASE)
    experience = int(exp_match.group(1)) if exp_match else 0

    return {"name": name, "experience": experience}


def validate_resume(file_path: str, hrms_name: str, hrms_experience: int) -> dict:
    """
    hrms_name / hrms_experience come from the Employee row (populated
    from HRMS -- employee.name and employee.years_of_experience).
    """
    resume_details = extract_resume_details(file_path)

    name_similarity = _name_similarity(resume_details["name"], hrms_name)
    name_match = name_similarity >= NAME_SIMILARITY_THRESHOLD

    hrms_experience = hrms_experience or 0
    experience_match = resume_details["experience"] == hrms_experience

    if hrms_experience > 0:
        experience_score = max(0, 1 - abs(resume_details["experience"] - hrms_experience) / hrms_experience)
    else:
        experience_score = 1 if resume_details["experience"] == 0 else 0

    agent_score = round((name_similarity * 0.7 + experience_score * 0.3) * 100, 2)
    overall_status = "PASS" if (name_match and experience_match) else "FAIL"

    try:
        result = call_ollama_json(REASONING_PROMPT.format(
            name_match=name_match, similarity=round(name_similarity * 100, 2),
            experience_match=experience_match, resume_exp=resume_details["experience"],
            hrms_exp=hrms_experience,
        ))
        reasoning = result.get("reasoning", "")
    except OllamaError:
        reasoning = (
            f"Name similarity {round(name_similarity * 100, 2)}% "
            f"({'match' if name_match else 'no match'}); "
            f"experience {resume_details['experience']} vs HRMS {hrms_experience} years "
            f"({'match' if experience_match else 'mismatch'})."
        )

    return {
        "status": overall_status,
        "resume_name": resume_details["name"],
        "hrms_name": hrms_name,
        "name_similarity_pct": round(name_similarity * 100, 2),
        "name_match": name_match,
        "resume_experience": resume_details["experience"],
        "hrms_experience": hrms_experience,
        "experience_match": experience_match,
        "agent_score": agent_score,
        "reasoning": reasoning,
    }
