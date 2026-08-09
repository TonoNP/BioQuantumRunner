"""Normative constants and schemas for the D3 contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

D3_CONTRACT_VERSION = "d3-1.0"
RUNNER_ID = "bqr_runner_001"

DISTANCE_CLASSES = ("3K", "5K", "10K", "Half Marathon", "Marathon", "Other", "Unknown")
EVENT_TYPES = ("race", "training", "time_trial", "unknown")
COMPETITION_CONTEXTS = (
    "official_competition", "organized_non_official", "self_organized",
    "training_environment", "unknown",
)
CONTEXT_FLAGS = (
    "illness", "injury", "extreme_weather", "gps_error", "irregular_pacing",
    "interruption", "incomplete_recovery", "insufficient_evidence",
    "course_irregularity", "nutrition_issue", "equipment_issue",
    "other_verified_context",
)
EVIDENCE_STATUSES = ("verified", "reported", "suspected")
CANDIDATE_STATUSES = ("verified", "pending_evidence", "discarded")
PREDICTION_STATUSES = ("predicted", "insufficient_history", "ineligible_target", "model_error")

RACE_REGISTRY_COLUMNS = [
    "race_id", "runner_id", "source_file", "source_sha256", "event_name",
    "event_date", "session_date", "observed_distance_km", "nominal_distance_km",
    "distance_class", "event_type", "competition_context", "candidate_status",
    "verification_status", "evidence_status", "evidence_type", "evidence_reference",
    "context_flags", "descriptive_eligible", "default_modeling_eligible",
    "exclusion_reason", "registry_version", "recorded_at", "recorded_by", "notes",
]

PREDICTION_COLUMNS = [
    "prediction_id", "runner_id", "target_race_id", "model_id", "model_version",
    "evaluation_protocol_id", "prediction_generated_at", "training_cutoff",
    "training_race_ids", "training_session_manifest_hash", "feature_contract_version",
    "predicted_pace_sec_per_km", "predicted_total_time_s", "prediction_status",
    "actual_pace_sec_per_km", "actual_total_time_s", "error_pace_sec_per_km",
    "error_total_time_s", "coverage_status", "code_commit",
]

@dataclass(frozen=True)
class ModelDeclaration:
    model_id: str
    model_version: str
    feature_contract: str
    training_window: str
    hyperparameters: dict[str, Any]
    eligibility_rules: str
    exclusion_rules: str
    evaluation_protocol: str = "walk_forward_pre_race_v1"

