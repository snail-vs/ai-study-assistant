"""Compatibility exports for the split activity workflow services."""

from ..agents.assessment_agent import AssessmentAgent
from ..security.auth import current_user_id
from .activity_assessment import generate_quiz, submit_attempt, submit_follow_up
from .activity_hooks import (
    derive_effective_post_assessment,
    run_post_assessment_hooks,
    should_run_activity_gap_diagnosis,
)
from .activity_query import activity_attempt_response, activity_response, get_activity
from .provider_settings import restore_active_provider

__all__ = [
    "AssessmentAgent", "activity_attempt_response", "activity_response",
    "current_user_id", "derive_effective_post_assessment", "generate_quiz",
    "get_activity", "restore_active_provider", "run_post_assessment_hooks",
    "should_run_activity_gap_diagnosis", "submit_attempt", "submit_follow_up",
]
