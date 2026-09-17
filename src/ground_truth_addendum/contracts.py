"""Frozen implementation constants for the approved Addendum."""

ADDENDUM_VERSION = "d4-ground-truth-addendum-1.0"
SCHEMA_VERSION = "d4-gt-sqlite-v1"
EVIDENCE_CATALOG_VERSION = "d4-gt-evidence-v1"
TEMPORAL_SPLIT_VERSION = "d4-gt-temporal-split-v1"

# Additive post-dry-run refinement.  The v1 constants above remain frozen so
# historical receipts and logical hashes retain their original meaning.
REFINEMENT_VERSION = "d4-ground-truth-refinement-1.0"
REFINEMENT_SCHEMA_VERSION = "d4-gt-claims-v2"
REFINEMENT_EVIDENCE_CATALOG_VERSION = "d4-gt-evidence-v2"

EVIDENCE_LEVELS = ("verified", "reported", "suspected")
DIMENSION_STATUSES = ("asserted", "unknown", "uncertain", "abstained", "not_applicable")
CLAIM_KINDS = (
    "instrumental_observation", "human_report",
    "manufacturer_interpretation", "analytical_inference",
    "legacy_unclassified",
)
CLAIM_SUBJECT_KINDS = ("recorded_session", "workout_group", "workout_membership")
CLAIM_DIMENSIONS = (
    "session_context", "workout_structure", "primary_function",
    "primary_function_subtype", "component_role", "performance_relevance",
    "training_load_relevance", "intensity_character", "distance_context",
    "competition_context", "health_context", "subjective_context",
)
EVIDENCE_SUPPORT_ROLES = ("support", "contradict", "contextual", "provenance_only")
MEMBERSHIP_STATES = ("included", "excluded", "uncertain", "unknown", "abstained")
GOLD_REASON_CODES = (
    "SINGLE_CLAIM", "COMPLEMENTARY_CLAIMS", "AGREEMENT_NO_ADJUDICATION",
    "CONSENSUS_ADJUDICATED", "CONFLICT_UNRESOLVED", "INDEPENDENT_OPINIONS",
    "ABSTAINED", "UNKNOWN", "NOT_APPLICABLE", "NO_VISIBLE_CLAIM",
)
PARTITIONS = ("development", "validation", "locked_test", "descriptive_only")
PROHIBITED_LOCKED_TEST_PURPOSES = (
    "training", "calibration", "feature_selection", "rule_selection",
    "threshold_selection", "active_learning", "architecture_optimization",
)


def temporal_partition(session_date: str) -> str:
    year = int(session_date[:4])
    if 2019 <= year <= 2023:
        return "development"
    if year == 2024:
        return "validation"
    if 2025 <= year <= 2026:
        return "locked_test"
    return "descriptive_only"
