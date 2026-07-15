"""
Drafts a short team-communication message announcing a departure, for
the offboarding Manager track's Team Communication task. Simulated
content only, same pattern as team_intro_agent.py -- generated and
shown, never actually sent anywhere.
"""
from app.ai_client import call_ollama_json, OllamaError

PROMPT_TEMPLATE = """Write a short, professional team-communication
message (under 60 words) announcing that {name} ({role}, {department})
is leaving the company, with a last working day of {last_working_day}.
Respectful tone, no speculation about the reason. Respond ONLY with
JSON: {{"message_text": "<the message>"}}
"""


def _fallback_message(name: str, role: str, department: str, last_working_day: str) -> str:
    return (
        f"Please note that {name} ({role}, {department}) will be leaving the "
        f"company, with {last_working_day or 'their last working day'} as their final day. "
        f"We wish them well in their next chapter."
    )


def draft_team_farewell(name: str, role: str, department: str, last_working_day: str) -> dict:
    try:
        result = call_ollama_json(PROMPT_TEMPLATE.format(
            name=name, role=role or "team member", department=department,
            last_working_day=last_working_day or "TBD",
        ))
        if "message_text" not in result:
            raise OllamaError("missing expected key in model output")
        return result
    except OllamaError:
        return {"message_text": _fallback_message(name, role, department, last_working_day)}
