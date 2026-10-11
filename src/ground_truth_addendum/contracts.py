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

# Additive D4.1 workout-component contract.  Prior versions remain frozen.
COMPONENT_VERSION = "d4-ground-truth-components-1.0"
COMPONENT_SCHEMA_VERSION = "d4-gt-components-v3"
ACTIVITY_CATALOG_VERSION = "d4-gt-activity-types-v1"
COMPONENT_MIGRATION_VERSION = "d4-gt-membership-projection-v1"

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

# Closed public-purpose vocabulary.  Unknown values fail closed before any
# partition lookup.  True means that the purpose may inspect locked_test;
# False means that it is valid only when no locked_test source is involved.
PURPOSE_LOCKED_TEST_ACCESS = {
    "training": False,
    "calibration": False,
    "feature_selection": False,
    "rule_selection": False,
    "threshold_selection": False,
    "active_learning": False,
    "architecture_optimization": False,
    "evaluation": True,
    "technical_integrity": True,
    "audit": True,
}

RECORDING_STATES = ("recorded", "unrecorded", "unknown")
TEMPORAL_PRECISIONS = ("exact", "approximate", "bounded", "unknown")
DURATION_BASES = ("active", "elapsed", "estimated", "unknown")
COMPONENT_DIMENSIONS = (
    "repetition_count_intended", "repetition_distance_nominal",
    "repetition_count_executed", "repetition_distance_executed",
    "repetition_count_observed", "repetition_distance_measured",
)
COMPONENT_VALUE_KINDS = ("none", "integer", "numeric", "text", "range")
COMPONENT_VALUE_QUALIFIERS = ("exact", "approximate", "minimum", "maximum", "range")
DISTANCE_UNITS = ("m", "km")
ANALYSIS_CONTEXT_STATUSES = (
    "complete_known_context", "partial_known_context",
    "unknown_context_present", "context_not_required",
)
UNKNOWN_CONTEXT_DEPENDENCIES = ("none", "contextual", "structural", "quantitative")
ANALYSIS_USABILITY_RESULTS = ("usable", "usable_with_context_warning", "abstain_unknown_context")
TOTAL_LOAD_STATUSES = ("complete", "partial", "incomplete")

ACTIVITY_TYPES_V1 = {
    "running_drills": "Running-technique drills distinct from continuous running",
    "mobility": "Documented joint or dynamic mobility",
    "stretching": "Documented static or dynamic stretching",
    "walking_recovery": "Documented walking recovery",
    "rest": "Explicitly documented rest",
    "hydration": "Explicitly documented hydration activity or pause",
    "strength": "Documented strength work",
    "preparation": "Documented preparation not covered by another category",
    "other_documented_activity": "Documented known activity without a specific active category",
}


def temporal_partition(session_date: str) -> str:
    year = int(session_date[:4])
    if 2019 <= year <= 2023:
        return "development"
    if year == 2024:
        return "validation"
    if 2025 <= year <= 2026:
        return "locked_test"
    return "descriptive_only"
