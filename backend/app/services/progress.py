"""
Shared completion-percentage calculation -- used by both the Employee
Profile endpoint and the Employee Directory listing, so they can never
show two different numbers for the same employee again.

REDEFINED: previously counted tracker steps being GENERATED (a step
marked "completed" the moment tasks existed, regardless of approval
state) -- this drifted out of sync with the Tracker's live track_status,
which reflects real approval progress. Now both use the same underlying
definition: 2 pipeline stages (Registered, Validation) + 4 tracks, where
each track contributes its FRACTIONAL approval progress (see
track_status.get_track_completion_fraction), not a binary generated/not.
"""
from sqlalchemy.orm import Session
from app.models import OnboardingTracker, OffboardingTracker
from app.services.track_status import (
    TRACKS, get_track_completion_fraction, get_offboarding_track_completion_fraction,
)

PIPELINE_STAGES = ["Registered", "Validation"]
OFFBOARDING_PIPELINE_STAGES = ["Exit Request", "Access Discovery", "Risk Assessment"]
TOTAL_UNITS = len(PIPELINE_STAGES) + len(TRACKS)  # 2 + 4 = 6
OFFBOARDING_TOTAL_UNITS = len(OFFBOARDING_PIPELINE_STAGES) + len(TRACKS)  # 3 + 4 = 7


def _stage_completed(db: Session, tracker_model, employee_id: str, step: str) -> bool:
    return db.query(tracker_model).filter(
        tracker_model.employee_id == employee_id,
        tracker_model.step == step,
        tracker_model.status == "completed",
    ).first() is not None


def get_onboarding_completion_pct(db: Session, employee_id: str) -> int:
    stage_credit = sum(1.0 for step in PIPELINE_STAGES if _stage_completed(db, OnboardingTracker, employee_id, step))
    track_credit = sum(get_track_completion_fraction(db, employee_id, track) for track in TRACKS)

    total_credit = stage_credit + track_credit
    if total_credit == 0:
        return 0
    return round((total_credit / TOTAL_UNITS) * 100)


def get_offboarding_completion_pct(db: Session, employee_id: str) -> int:
    stage_credit = sum(
        1.0 for step in OFFBOARDING_PIPELINE_STAGES if _stage_completed(db, OffboardingTracker, employee_id, step)
    )
    track_credit = sum(get_offboarding_track_completion_fraction(db, employee_id, track) for track in TRACKS)

    total_credit = stage_credit + track_credit
    if total_credit == 0:
        return 0
    return round((total_credit / OFFBOARDING_TOTAL_UNITS) * 100)
