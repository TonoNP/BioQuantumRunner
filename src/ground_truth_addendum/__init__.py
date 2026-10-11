"""Append-only Ground Truth Addendum infrastructure for D4."""

from .canonical import canonical_json, logical_hash, logical_records_hash
from .components import (
    compose_component_gold,
    evaluate_unknown_context,
    summarize_observed_load,
    validate_component,
    validate_component_claim,
)
from .ids import deterministic_id, new_event_id
from .store import GroundTruthStore, LockedTestAccessError

__all__ = [
    "GroundTruthStore",
    "LockedTestAccessError",
    "canonical_json",
    "compose_component_gold",
    "deterministic_id",
    "evaluate_unknown_context",
    "logical_hash",
    "logical_records_hash",
    "new_event_id",
    "summarize_observed_load",
    "validate_component",
    "validate_component_claim",
]

