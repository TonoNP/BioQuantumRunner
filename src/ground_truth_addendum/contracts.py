"""Frozen implementation constants for the approved Addendum."""

ADDENDUM_VERSION = "d4-ground-truth-addendum-1.0"
SCHEMA_VERSION = "d4-gt-sqlite-v1"
EVIDENCE_CATALOG_VERSION = "d4-gt-evidence-v1"
TEMPORAL_SPLIT_VERSION = "d4-gt-temporal-split-v1"

EVIDENCE_LEVELS = ("verified", "reported", "suspected")
DIMENSION_STATUSES = ("asserted", "unknown", "uncertain", "abstained", "not_applicable")
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

