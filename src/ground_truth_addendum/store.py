"""SQLite system of record for the approved D4 Ground Truth Addendum.

All domain history is append-only. SQLite is the initial transactional profile;
the schema avoids SQLite-specific scientific semantics so that a future
PostgreSQL migration can preserve logical content.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .canonical import logical_hash, logical_records_hash
from .contracts import (
    ACTIVITY_CATALOG_VERSION,
    ACTIVITY_TYPES_V1,
    ADDENDUM_VERSION,
    CLAIM_KINDS,
    COMPONENT_SCHEMA_VERSION,
    COMPONENT_VERSION,
    EVIDENCE_CATALOG_VERSION,
    EVIDENCE_LEVELS,
    MEMBERSHIP_STATES,
    PURPOSE_LOCKED_TEST_ACCESS,
    REFINEMENT_EVIDENCE_CATALOG_VERSION,
    REFINEMENT_SCHEMA_VERSION,
    REFINEMENT_VERSION,
    SCHEMA_VERSION,
    TEMPORAL_SPLIT_VERSION,
    temporal_partition,
)
from .components import compose_component_gold, validate_component, validate_component_claim
from .ids import ID_STRATEGY_VERSION, deterministic_id, new_event_id, validate_uuid
from .refinement import compose_dimension_gold, validate_claim


class LockedTestAccessError(ValueError):
    """Raised when a prohibited adaptive purpose touches locked_test."""


def _utc_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


IMMUTABLE_TABLES = (
    "ground_truth_source_sessions",
    "ground_truth_review_units",
    "ground_truth_review_unit_memberships",
    "ground_truth_annotation_threads",
    "ground_truth_session_decisions",
    "ground_truth_workout_groups",
    "ground_truth_group_memberships",
    "ground_truth_claim_threads_v2",
    "ground_truth_evidence_type_catalog_v2",
    "ground_truth_evidence_records_v2",
    "ground_truth_semantic_claims_v2",
    "ground_truth_claim_evidence_links_v2",
    "ground_truth_workout_memberships_v2",
    "ground_truth_membership_evidence_links_v2",
    "ground_truth_activity_type_catalog_v3",
    "ground_truth_workout_components_v3",
    "ground_truth_component_evidence_links_v3",
    "ground_truth_component_claim_threads_v3",
    "ground_truth_component_claims_v3",
    "ground_truth_component_claim_evidence_links_v3",
    "ground_truth_publications",
)


SCHEMA_SQL = r"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ground_truth_source_sessions (
    runner_id TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_sha256 TEXT NOT NULL CHECK(length(source_sha256) = 64),
    session_date TEXT NOT NULL,
    temporal_partition TEXT NOT NULL CHECK(temporal_partition IN ('development','validation','locked_test','descriptive_only')),
    temporal_partition_policy_version TEXT NOT NULL,
    source_manifest TEXT NOT NULL CHECK(length(source_manifest) = 64),
    PRIMARY KEY (runner_id, source_file, source_sha256)
);

CREATE TABLE IF NOT EXISTS ground_truth_sampling_batches (
    sampling_batch_id TEXT PRIMARY KEY,
    runner_id TEXT NOT NULL,
    sampling_strategy_version TEXT NOT NULL,
    temporal_partition_policy_version TEXT NOT NULL,
    sampling_purpose TEXT NOT NULL CHECK(sampling_purpose IN ('pilot','development','validation','locked_test','active_learning','audit_control')),
    population_manifest TEXT NOT NULL CHECK(length(population_manifest) = 64),
    population_size INTEGER NOT NULL CHECK(population_size >= 0),
    requested_unit_count INTEGER NOT NULL CHECK(requested_unit_count >= 0),
    selection_method TEXT NOT NULL CHECK(selection_method IN ('census','stratified','deterministic_targeted','probabilistic','active_learning','hybrid')),
    random_seed INTEGER,
    strata_definition TEXT NOT NULL CHECK(json_valid(strata_definition)),
    selection_algorithm TEXT NOT NULL,
    feature_snapshot_manifest TEXT CHECK(feature_snapshot_manifest IS NULL OR length(feature_snapshot_manifest) = 64),
    knowledge_cutoff TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    code_commit TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    locked INTEGER NOT NULL DEFAULT 0 CHECK(locked IN (0,1)),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS ground_truth_review_units (
    review_unit_record_id TEXT PRIMARY KEY,
    review_unit_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision >= 1),
    supersedes_review_unit_record_id TEXT REFERENCES ground_truth_review_units(review_unit_record_id),
    runner_id TEXT NOT NULL,
    review_unit_type TEXT NOT NULL CHECK(review_unit_type IN ('individual_session','candidate_session_set','confirmed_workout_view','suspected_workout_view','ambiguous_case','partial_case')),
    sampling_batch_id TEXT NOT NULL REFERENCES ground_truth_sampling_batches(sampling_batch_id),
    sampling_strategy_version TEXT NOT NULL,
    sampling_stratum TEXT NOT NULL,
    selection_reason TEXT NOT NULL,
    selection_probability REAL CHECK(selection_probability IS NULL OR (selection_probability > 0 AND selection_probability <= 1)),
    selection_probability_missing_reason TEXT,
    temporal_partition TEXT NOT NULL CHECK(temporal_partition IN ('development','validation','locked_test','descriptive_only')),
    temporal_partition_policy_version TEXT NOT NULL,
    review_status TEXT NOT NULL CHECK(review_status IN ('created','assigned','in_review','completed','needs_adjudication','closed')),
    reviewer_id TEXT,
    reviewer_role TEXT,
    semantics_mode TEXT NOT NULL CHECK(semantics_mode IN ('retrospective','as_of')),
    knowledge_cutoff TEXT NOT NULL,
    data_manifest TEXT NOT NULL CHECK(length(data_manifest) = 64),
    feature_contract_version TEXT NOT NULL,
    code_commit TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    UNIQUE(review_unit_id, revision),
    CHECK((selection_probability IS NULL) = (selection_probability_missing_reason IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS ground_truth_review_unit_memberships (
    review_membership_record_id TEXT PRIMARY KEY,
    review_unit_record_id TEXT NOT NULL REFERENCES ground_truth_review_units(review_unit_record_id),
    runner_id TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    presentation_order INTEGER NOT NULL CHECK(presentation_order >= 1),
    membership_reason TEXT NOT NULL,
    FOREIGN KEY (runner_id, source_file, source_sha256)
      REFERENCES ground_truth_source_sessions(runner_id, source_file, source_sha256),
    UNIQUE(review_unit_record_id, source_file),
    UNIQUE(review_unit_record_id, presentation_order)
);

CREATE TABLE IF NOT EXISTS ground_truth_annotation_threads (
    annotation_thread_id TEXT PRIMARY KEY,
    runner_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('session','workout_group')),
    target_key TEXT NOT NULL,
    opened_by TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    contract_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ground_truth_session_decisions (
    decision_id TEXT PRIMARY KEY,
    annotation_thread_id TEXT NOT NULL REFERENCES ground_truth_annotation_threads(annotation_thread_id),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    supersedes_decision_id TEXT REFERENCES ground_truth_session_decisions(decision_id),
    decision_kind TEXT NOT NULL CHECK(decision_kind IN ('annotation','correction','adjudication','consensus')),
    runner_id TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    author_id TEXT NOT NULL,
    author_role TEXT NOT NULL,
    evidence_observed_at TEXT,
    decision_timestamp TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    label_available_at TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    evidence_catalog_version TEXT NOT NULL,
    evidence_reference TEXT NOT NULL,
    evidence_level TEXT NOT NULL CHECK(evidence_level IN ('verified','reported','suspected')),
    session_context TEXT,
    session_context_status TEXT NOT NULL CHECK(session_context_status IN ('asserted','unknown','uncertain','abstained','not_applicable')),
    workout_structure TEXT,
    workout_structure_status TEXT NOT NULL CHECK(workout_structure_status IN ('asserted','unknown','uncertain','abstained','not_applicable')),
    primary_function TEXT,
    primary_function_status TEXT NOT NULL CHECK(primary_function_status IN ('asserted','unknown','uncertain','abstained','not_applicable')),
    primary_function_subtype TEXT,
    primary_function_subtype_status TEXT NOT NULL CHECK(primary_function_subtype_status IN ('asserted','unknown','uncertain','abstained','not_applicable')),
    component_role TEXT,
    component_role_status TEXT NOT NULL CHECK(component_role_status IN ('asserted','unknown','uncertain','abstained','not_applicable')),
    performance_relevance TEXT,
    performance_relevance_status TEXT NOT NULL CHECK(performance_relevance_status IN ('asserted','unknown','uncertain','abstained','not_applicable')),
    training_load_relevance TEXT,
    training_load_relevance_status TEXT NOT NULL CHECK(training_load_relevance_status IN ('asserted','unknown','uncertain','abstained','not_applicable')),
    uncertainty_reason TEXT,
    comment TEXT,
    code_commit TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    FOREIGN KEY (runner_id, source_file, source_sha256)
      REFERENCES ground_truth_source_sessions(runner_id, source_file, source_sha256),
    UNIQUE(annotation_thread_id, revision),
    CHECK(label_available_at >= decision_timestamp)
);

CREATE TABLE IF NOT EXISTS ground_truth_workout_groups (
    group_decision_id TEXT PRIMARY KEY,
    workout_group_id TEXT NOT NULL,
    annotation_thread_id TEXT NOT NULL REFERENCES ground_truth_annotation_threads(annotation_thread_id),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    supersedes_group_decision_id TEXT REFERENCES ground_truth_workout_groups(group_decision_id),
    decision_kind TEXT NOT NULL CHECK(decision_kind IN ('annotation','correction','adjudication','consensus')),
    runner_id TEXT NOT NULL,
    group_status TEXT NOT NULL CHECK(group_status IN ('candidate','confirmed','rejected','uncertain')),
    evidence_level TEXT NOT NULL CHECK(evidence_level IN ('verified','reported','suspected')),
    evidence_types TEXT NOT NULL CHECK(json_valid(evidence_types)),
    evidence_catalog_version TEXT NOT NULL,
    evidence_reference TEXT NOT NULL,
    decision_timestamp TEXT NOT NULL,
    label_available_at TEXT NOT NULL,
    author_id TEXT NOT NULL,
    author_role TEXT NOT NULL,
    code_commit TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    UNIQUE(annotation_thread_id, revision),
    CHECK(label_available_at >= decision_timestamp)
);

CREATE TABLE IF NOT EXISTS ground_truth_group_memberships (
    membership_decision_id TEXT PRIMARY KEY,
    annotation_thread_id TEXT NOT NULL REFERENCES ground_truth_annotation_threads(annotation_thread_id),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    supersedes_membership_decision_id TEXT REFERENCES ground_truth_group_memberships(membership_decision_id),
    workout_group_id TEXT NOT NULL,
    group_decision_id TEXT NOT NULL REFERENCES ground_truth_workout_groups(group_decision_id),
    runner_id TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    membership_status TEXT NOT NULL CHECK(membership_status IN ('included','excluded','uncertain')),
    component_order INTEGER CHECK(component_order IS NULL OR component_order >= 1),
    component_role TEXT CHECK(component_role IN ('warmup','main_set','recovery_segment','cooldown','unknown')),
    evidence_level TEXT NOT NULL CHECK(evidence_level IN ('verified','reported','suspected')),
    decision_timestamp TEXT NOT NULL,
    label_available_at TEXT NOT NULL,
    FOREIGN KEY (runner_id, source_file, source_sha256)
      REFERENCES ground_truth_source_sessions(runner_id, source_file, source_sha256),
    UNIQUE(annotation_thread_id, revision),
    CHECK(label_available_at >= decision_timestamp)
);

CREATE TABLE IF NOT EXISTS ground_truth_claim_threads_v2 (
    annotation_thread_id TEXT PRIMARY KEY,
    runner_id TEXT NOT NULL,
    subject_kind TEXT NOT NULL CHECK(subject_kind IN ('recorded_session','workout_group','workout_membership')),
    subject_key TEXT NOT NULL,
    opened_by TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    UNIQUE(runner_id, subject_kind, subject_key, annotation_thread_id)
);

CREATE TABLE IF NOT EXISTS ground_truth_evidence_type_catalog_v2 (
    catalog_version TEXT NOT NULL,
    evidence_type_id TEXT NOT NULL,
    definition TEXT NOT NULL,
    source_class TEXT NOT NULL CHECK(source_class IN ('instrumental','human','manufacturer','analytical','external')),
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('active','deprecated')),
    superseded_by_type_id TEXT,
    PRIMARY KEY (catalog_version, evidence_type_id)
);

CREATE TABLE IF NOT EXISTS ground_truth_evidence_records_v2 (
    evidence_id TEXT PRIMARY KEY,
    runner_id TEXT NOT NULL,
    evidence_type_id TEXT NOT NULL,
    evidence_catalog_version TEXT NOT NULL,
    source_system TEXT NOT NULL,
    source_locator TEXT NOT NULL,
    source_content_sha256 TEXT CHECK(source_content_sha256 IS NULL OR length(source_content_sha256) = 64),
    evidence_observed_at TEXT,
    recorded_at TEXT NOT NULL,
    scientific_purpose TEXT NOT NULL,
    data_minimization_note TEXT NOT NULL,
    code_commit TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    FOREIGN KEY (evidence_catalog_version, evidence_type_id)
      REFERENCES ground_truth_evidence_type_catalog_v2(catalog_version, evidence_type_id)
);

CREATE TABLE IF NOT EXISTS ground_truth_semantic_claims_v2 (
    claim_id TEXT PRIMARY KEY,
    annotation_thread_id TEXT NOT NULL REFERENCES ground_truth_claim_threads_v2(annotation_thread_id),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    supersedes_claim_id TEXT REFERENCES ground_truth_semantic_claims_v2(claim_id),
    decision_kind TEXT NOT NULL CHECK(decision_kind IN ('annotation','correction','adjudication','consensus','migration')),
    runner_id TEXT NOT NULL,
    subject_kind TEXT NOT NULL CHECK(subject_kind IN ('recorded_session','workout_group','workout_membership')),
    subject_key TEXT NOT NULL,
    source_file TEXT,
    source_sha256 TEXT CHECK(source_sha256 IS NULL OR length(source_sha256) = 64),
    dimension_name TEXT NOT NULL,
    claim_value TEXT,
    claim_status TEXT NOT NULL CHECK(claim_status IN ('asserted','unknown','uncertain','abstained','not_applicable')),
    claim_kind TEXT NOT NULL CHECK(claim_kind IN ('instrumental_observation','human_report','manufacturer_interpretation','analytical_inference','legacy_unclassified')),
    evidence_level TEXT NOT NULL CHECK(evidence_level IN ('verified','reported','suspected')),
    author_id TEXT NOT NULL,
    author_role TEXT NOT NULL,
    rationale TEXT,
    uncertainty_reason TEXT,
    evidence_observed_at TEXT,
    decision_timestamp TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    label_available_at TEXT NOT NULL,
    provenance_granularity TEXT NOT NULL CHECK(provenance_granularity IN ('atomic','legacy_decision_wide')),
    legacy_decision_id TEXT,
    code_commit TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    UNIQUE(annotation_thread_id, revision),
    CHECK(label_available_at >= decision_timestamp),
    CHECK((subject_kind = 'recorded_session' AND source_file IS NOT NULL AND source_sha256 IS NOT NULL)
       OR (subject_kind <> 'recorded_session')),
    FOREIGN KEY (runner_id, source_file, source_sha256)
      REFERENCES ground_truth_source_sessions(runner_id, source_file, source_sha256)
);

CREATE TABLE IF NOT EXISTS ground_truth_claim_evidence_links_v2 (
    claim_evidence_link_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES ground_truth_semantic_claims_v2(claim_id),
    evidence_id TEXT NOT NULL REFERENCES ground_truth_evidence_records_v2(evidence_id),
    support_role TEXT NOT NULL CHECK(support_role IN ('support','contradict','contextual','provenance_only')),
    rationale TEXT,
    UNIQUE(claim_id, evidence_id, support_role)
);

CREATE TABLE IF NOT EXISTS ground_truth_workout_memberships_v2 (
    membership_decision_id TEXT PRIMARY KEY,
    annotation_thread_id TEXT NOT NULL REFERENCES ground_truth_claim_threads_v2(annotation_thread_id),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    supersedes_membership_decision_id TEXT REFERENCES ground_truth_workout_memberships_v2(membership_decision_id),
    decision_kind TEXT NOT NULL CHECK(decision_kind IN ('annotation','correction','adjudication','consensus','migration')),
    runner_id TEXT NOT NULL,
    workout_group_id TEXT NOT NULL,
    group_decision_id TEXT NOT NULL REFERENCES ground_truth_workout_groups(group_decision_id),
    source_file TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    membership_state TEXT NOT NULL CHECK(membership_state IN ('included','excluded','uncertain','unknown','abstained')),
    component_order INTEGER CHECK(component_order IS NULL OR component_order >= 1),
    component_role TEXT CHECK(component_role IN ('warmup','main_set','recovery_segment','cooldown','unknown')),
    claim_kind TEXT NOT NULL CHECK(claim_kind IN ('instrumental_observation','human_report','manufacturer_interpretation','analytical_inference','legacy_unclassified')),
    evidence_level TEXT NOT NULL CHECK(evidence_level IN ('verified','reported','suspected')),
    author_id TEXT NOT NULL,
    author_role TEXT NOT NULL,
    rationale TEXT,
    uncertainty_reason TEXT,
    evidence_observed_at TEXT,
    decision_timestamp TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    label_available_at TEXT NOT NULL,
    code_commit TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    UNIQUE(annotation_thread_id, revision),
    CHECK(label_available_at >= decision_timestamp),
    FOREIGN KEY (runner_id, source_file, source_sha256)
      REFERENCES ground_truth_source_sessions(runner_id, source_file, source_sha256)
);

CREATE TABLE IF NOT EXISTS ground_truth_membership_evidence_links_v2 (
    membership_evidence_link_id TEXT PRIMARY KEY,
    membership_decision_id TEXT NOT NULL REFERENCES ground_truth_workout_memberships_v2(membership_decision_id),
    evidence_id TEXT NOT NULL REFERENCES ground_truth_evidence_records_v2(evidence_id),
    support_role TEXT NOT NULL CHECK(support_role IN ('support','contradict','contextual','provenance_only')),
    rationale TEXT,
    UNIQUE(membership_decision_id, evidence_id, support_role)
);

CREATE TABLE IF NOT EXISTS ground_truth_activity_type_catalog_v3 (
    catalog_version TEXT NOT NULL,
    activity_type_id TEXT NOT NULL CHECK(activity_type_id <> 'unknown'),
    definition TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('active','deprecated')),
    superseded_by_type_id TEXT,
    created_at TEXT NOT NULL,
    code_commit TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    PRIMARY KEY (catalog_version, activity_type_id),
    CHECK((lifecycle_status = 'deprecated') OR superseded_by_type_id IS NULL)
);

CREATE TABLE IF NOT EXISTS ground_truth_workout_components_v3 (
    component_decision_id TEXT PRIMARY KEY,
    component_id TEXT NOT NULL,
    supersedes_component_decision_id TEXT REFERENCES ground_truth_workout_components_v3(component_decision_id),
    decision_kind TEXT NOT NULL CHECK(decision_kind IN ('annotation','correction','adjudication','consensus','migration')),
    runner_id TEXT NOT NULL,
    workout_group_id TEXT NOT NULL,
    group_decision_id TEXT NOT NULL REFERENCES ground_truth_workout_groups(group_decision_id),
    component_order INTEGER NOT NULL CHECK(component_order >= 1),
    recording_state TEXT NOT NULL CHECK(recording_state IN ('recorded','unrecorded','unknown')),
    membership_decision_id TEXT REFERENCES ground_truth_workout_memberships_v2(membership_decision_id),
    activity_catalog_version TEXT,
    activity_type_id TEXT,
    component_role TEXT,
    start_time TEXT,
    end_time TEXT,
    temporal_precision TEXT NOT NULL CHECK(temporal_precision IN ('exact','approximate','bounded','unknown')),
    duration_s REAL CHECK(duration_s IS NULL OR (duration_s >= 0 AND duration_s <= 1.7976931348623157e308)),
    duration_basis TEXT NOT NULL CHECK(duration_basis IN ('active','elapsed','estimated','unknown')),
    claim_kind TEXT NOT NULL CHECK(claim_kind IN ('instrumental_observation','human_report','manufacturer_interpretation','analytical_inference','legacy_unclassified')),
    evidence_level TEXT NOT NULL CHECK(evidence_level IN ('verified','reported','suspected')),
    author_id TEXT NOT NULL,
    author_role TEXT NOT NULL,
    evidence_observed_at TEXT,
    decision_timestamp TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    label_available_at TEXT NOT NULL,
    uncertainty_reason TEXT,
    rationale TEXT,
    code_commit TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    FOREIGN KEY (activity_catalog_version, activity_type_id)
      REFERENCES ground_truth_activity_type_catalog_v3(catalog_version, activity_type_id),
    CHECK(label_available_at >= decision_timestamp),
    CHECK((duration_basis <> 'unknown') OR duration_s IS NULL),
    CHECK(
      (recording_state = 'recorded' AND membership_decision_id IS NOT NULL
       AND activity_catalog_version IS NULL AND activity_type_id IS NULL)
      OR
      (recording_state = 'unrecorded' AND membership_decision_id IS NULL
       AND activity_catalog_version IS NOT NULL AND activity_type_id IS NOT NULL)
      OR
      (recording_state = 'unknown' AND membership_decision_id IS NULL
       AND activity_catalog_version IS NULL AND activity_type_id IS NULL
       AND component_role IS NULL AND length(trim(uncertainty_reason)) > 0)
    )
);

CREATE INDEX IF NOT EXISTS idx_gt_components_runner_group_order
ON ground_truth_workout_components_v3(runner_id, workout_group_id, component_order);
CREATE INDEX IF NOT EXISTS idx_gt_components_identity_asof
ON ground_truth_workout_components_v3(component_id, label_available_at);
CREATE INDEX IF NOT EXISTS idx_gt_components_membership
ON ground_truth_workout_components_v3(membership_decision_id);

CREATE TABLE IF NOT EXISTS ground_truth_component_evidence_links_v3 (
    component_evidence_link_id TEXT PRIMARY KEY,
    component_decision_id TEXT NOT NULL REFERENCES ground_truth_workout_components_v3(component_decision_id),
    evidence_id TEXT NOT NULL REFERENCES ground_truth_evidence_records_v2(evidence_id),
    support_role TEXT NOT NULL CHECK(support_role IN ('support','contradict','contextual','provenance_only')),
    rationale TEXT,
    UNIQUE(component_decision_id, evidence_id, support_role)
);

CREATE TABLE IF NOT EXISTS ground_truth_component_claim_threads_v3 (
    annotation_thread_id TEXT PRIMARY KEY,
    runner_id TEXT NOT NULL,
    component_id TEXT NOT NULL,
    dimension_name TEXT NOT NULL CHECK(dimension_name IN (
      'repetition_count_intended','repetition_distance_nominal',
      'repetition_count_executed','repetition_distance_executed',
      'repetition_count_observed','repetition_distance_measured'
    )),
    item_index INTEGER CHECK(item_index IS NULL OR item_index >= 1),
    opened_by TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    UNIQUE(runner_id, component_id, dimension_name, item_index, annotation_thread_id)
);

CREATE TABLE IF NOT EXISTS ground_truth_component_claims_v3 (
    claim_id TEXT PRIMARY KEY,
    annotation_thread_id TEXT NOT NULL REFERENCES ground_truth_component_claim_threads_v3(annotation_thread_id),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    supersedes_claim_id TEXT REFERENCES ground_truth_component_claims_v3(claim_id),
    primary_evidence_id TEXT REFERENCES ground_truth_evidence_records_v2(evidence_id),
    decision_kind TEXT NOT NULL CHECK(decision_kind IN ('annotation','correction','adjudication','consensus','migration')),
    runner_id TEXT NOT NULL,
    component_id TEXT NOT NULL,
    dimension_name TEXT NOT NULL,
    item_index INTEGER CHECK(item_index IS NULL OR item_index >= 1),
    claim_status TEXT NOT NULL CHECK(claim_status IN ('asserted','unknown','uncertain','abstained','not_applicable')),
    value_kind TEXT NOT NULL CHECK(value_kind IN ('none','integer','numeric','text','range')),
    integer_value BLOB,
    numeric_value REAL,
    text_value TEXT,
    range_lower_value REAL,
    range_upper_value REAL,
    unit TEXT,
    value_qualifier TEXT CHECK(value_qualifier IS NULL OR value_qualifier IN ('exact','approximate','minimum','maximum','range')),
    claim_kind TEXT NOT NULL CHECK(claim_kind IN ('instrumental_observation','human_report','manufacturer_interpretation','analytical_inference','legacy_unclassified')),
    evidence_level TEXT NOT NULL CHECK(evidence_level IN ('verified','reported','suspected')),
    author_id TEXT NOT NULL,
    author_role TEXT NOT NULL,
    rationale TEXT,
    uncertainty_reason TEXT,
    evidence_observed_at TEXT,
    decision_timestamp TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    label_available_at TEXT NOT NULL,
    code_commit TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    UNIQUE(annotation_thread_id, revision),
    CHECK(label_available_at >= decision_timestamp),
    CHECK(
      (value_kind = 'none' AND integer_value IS NULL AND numeric_value IS NULL AND text_value IS NULL
       AND range_lower_value IS NULL AND range_upper_value IS NULL AND unit IS NULL AND value_qualifier IS NULL)
      OR
      (value_kind = 'integer' AND integer_value IS NOT NULL AND typeof(integer_value) = 'integer' AND integer_value >= 0
       AND numeric_value IS NULL AND text_value IS NULL AND range_lower_value IS NULL AND range_upper_value IS NULL AND unit IS NULL)
      OR
      (value_kind = 'numeric' AND integer_value IS NULL AND numeric_value IS NOT NULL AND numeric_value >= 0 AND numeric_value <= 1.7976931348623157e308
       AND text_value IS NULL AND range_lower_value IS NULL AND range_upper_value IS NULL)
      OR
      (value_kind = 'text' AND integer_value IS NULL AND numeric_value IS NULL AND length(trim(text_value)) > 0
       AND range_lower_value IS NULL AND range_upper_value IS NULL AND unit IS NULL AND value_qualifier IS NULL)
      OR
      (value_kind = 'range' AND integer_value IS NULL AND numeric_value IS NULL AND text_value IS NULL
       AND range_lower_value IS NOT NULL AND range_lower_value >= 0 AND range_lower_value <= 1.7976931348623157e308
       AND range_upper_value IS NOT NULL AND range_upper_value <= 1.7976931348623157e308 AND range_lower_value <= range_upper_value
       AND value_qualifier = 'range')
    ),
    CHECK((claim_status = 'asserted' AND value_kind <> 'none') OR claim_status <> 'asserted'),
    CHECK((claim_status IN ('asserted','uncertain') AND primary_evidence_id IS NOT NULL)
       OR claim_status NOT IN ('asserted','uncertain')),
    CHECK((claim_status NOT IN ('unknown','abstained','not_applicable') AND value_kind <> 'none')
       OR (claim_status IN ('unknown','abstained','not_applicable') AND value_kind = 'none'))
);

CREATE TABLE IF NOT EXISTS ground_truth_component_claim_evidence_links_v3 (
    claim_evidence_link_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES ground_truth_component_claims_v3(claim_id),
    evidence_id TEXT NOT NULL REFERENCES ground_truth_evidence_records_v2(evidence_id),
    support_role TEXT NOT NULL CHECK(support_role IN ('support','contradict','contextual','provenance_only')),
    rationale TEXT,
    UNIQUE(claim_id, evidence_id, support_role)
);

CREATE TABLE IF NOT EXISTS ground_truth_publications (
    publication_id TEXT PRIMARY KEY,
    product_name TEXT NOT NULL CHECK(product_name IN ('gold_core','gold_extended','sampling_batch','review_snapshot','audit')),
    published_at TEXT NOT NULL,
    knowledge_cutoff TEXT NOT NULL,
    population_manifest TEXT NOT NULL CHECK(length(population_manifest) = 64),
    evidence_manifest TEXT NOT NULL CHECK(length(evidence_manifest) = 64),
    logical_hash TEXT NOT NULL CHECK(length(logical_hash) = 64),
    binary_hash TEXT CHECK(binary_hash IS NULL OR length(binary_hash) = 64),
    row_count INTEGER NOT NULL CHECK(row_count >= 0),
    contract_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    code_commit TEXT NOT NULL,
    receipt_path TEXT NOT NULL,
    UNIQUE(product_name, knowledge_cutoff, logical_hash)
);
"""


def _immutable_triggers() -> str:
    chunks: list[str] = []
    for table in IMMUTABLE_TABLES:
        chunks.append(
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, 'append-only: update forbidden on {table}'); END;"
        )
        chunks.append(
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, 'append-only: delete forbidden on {table}'); END;"
        )
    return "\n".join(chunks)


INTEGRITY_TRIGGERS = r"""
CREATE TRIGGER IF NOT EXISTS sampling_batch_no_delete
BEFORE DELETE ON ground_truth_sampling_batches
BEGIN SELECT RAISE(ABORT, 'append-only: delete forbidden on ground_truth_sampling_batches'); END;

CREATE TRIGGER IF NOT EXISTS sampling_batch_lock_only
BEFORE UPDATE ON ground_truth_sampling_batches
WHEN NOT (
  OLD.locked = 0 AND NEW.locked = 1
  AND OLD.sampling_batch_id = NEW.sampling_batch_id
  AND OLD.runner_id = NEW.runner_id
  AND OLD.sampling_strategy_version = NEW.sampling_strategy_version
  AND OLD.temporal_partition_policy_version = NEW.temporal_partition_policy_version
  AND OLD.sampling_purpose = NEW.sampling_purpose
  AND OLD.population_manifest = NEW.population_manifest
  AND OLD.population_size = NEW.population_size
  AND OLD.requested_unit_count = NEW.requested_unit_count
  AND OLD.selection_method = NEW.selection_method
  AND OLD.random_seed IS NEW.random_seed
  AND OLD.strata_definition = NEW.strata_definition
  AND OLD.selection_algorithm = NEW.selection_algorithm
  AND OLD.feature_snapshot_manifest IS NEW.feature_snapshot_manifest
  AND OLD.knowledge_cutoff = NEW.knowledge_cutoff
  AND OLD.created_at = NEW.created_at
  AND OLD.created_by = NEW.created_by
  AND OLD.code_commit = NEW.code_commit
  AND OLD.contract_version = NEW.contract_version
  AND OLD.notes IS NEW.notes
)
BEGIN SELECT RAISE(ABORT, 'sampling batch permits only irreversible lock transition'); END;

CREATE TRIGGER IF NOT EXISTS session_decision_thread_guard
BEFORE INSERT ON ground_truth_session_decisions
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM ground_truth_annotation_threads t
    WHERE t.annotation_thread_id = NEW.annotation_thread_id
      AND t.runner_id = NEW.runner_id
      AND t.target_kind = 'session'
      AND t.target_key = NEW.source_file
  ) THEN RAISE(ABORT, 'annotation thread target mismatch') END;
  SELECT CASE WHEN NEW.revision = 1 AND NEW.supersedes_decision_id IS NOT NULL
    THEN RAISE(ABORT, 'first revision cannot supersede') END;
  SELECT CASE WHEN NEW.revision > 1 AND NOT EXISTS (
    SELECT 1 FROM ground_truth_session_decisions p
    WHERE p.decision_id = NEW.supersedes_decision_id
      AND p.annotation_thread_id = NEW.annotation_thread_id
      AND p.revision = NEW.revision - 1
  ) THEN RAISE(ABORT, 'invalid supersedes chain') END;
END;

CREATE TRIGGER IF NOT EXISTS review_membership_locked_guard
BEFORE INSERT ON ground_truth_review_unit_memberships
BEGIN
  SELECT CASE WHEN EXISTS (
    SELECT 1 FROM ground_truth_review_units u
    JOIN ground_truth_sampling_batches b ON b.sampling_batch_id = u.sampling_batch_id
    WHERE u.review_unit_record_id = NEW.review_unit_record_id AND b.locked = 1
  ) THEN RAISE(ABORT, 'locked batch membership is immutable') END;
END;

CREATE TRIGGER IF NOT EXISTS group_membership_identity_guard
BEFORE INSERT ON ground_truth_group_memberships
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM ground_truth_workout_groups g
    WHERE g.group_decision_id = NEW.group_decision_id
      AND g.workout_group_id = NEW.workout_group_id
      AND g.runner_id = NEW.runner_id
  ) THEN RAISE(ABORT, 'workout group identity mismatch') END;
  SELECT CASE WHEN NEW.revision = 1 AND NEW.supersedes_membership_decision_id IS NOT NULL
    THEN RAISE(ABORT, 'first membership revision cannot supersede') END;
  SELECT CASE WHEN NEW.revision > 1 AND NOT EXISTS (
    SELECT 1 FROM ground_truth_group_memberships p
    WHERE p.membership_decision_id = NEW.supersedes_membership_decision_id
      AND p.annotation_thread_id = NEW.annotation_thread_id
      AND p.revision = NEW.revision - 1
  ) THEN RAISE(ABORT, 'invalid membership supersedes chain') END;
END;

CREATE TRIGGER IF NOT EXISTS workout_group_thread_guard
BEFORE INSERT ON ground_truth_workout_groups
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM ground_truth_annotation_threads t
    WHERE t.annotation_thread_id = NEW.annotation_thread_id
      AND t.runner_id = NEW.runner_id
      AND t.target_kind = 'workout_group'
      AND t.target_key = NEW.workout_group_id
  ) THEN RAISE(ABORT, 'workout annotation thread target mismatch') END;
  SELECT CASE WHEN NEW.revision = 1 AND NEW.supersedes_group_decision_id IS NOT NULL
    THEN RAISE(ABORT, 'first group revision cannot supersede') END;
  SELECT CASE WHEN NEW.revision > 1 AND NOT EXISTS (
    SELECT 1 FROM ground_truth_workout_groups p
    WHERE p.group_decision_id = NEW.supersedes_group_decision_id
      AND p.annotation_thread_id = NEW.annotation_thread_id
      AND p.revision = NEW.revision - 1
  ) THEN RAISE(ABORT, 'invalid group supersedes chain') END;
END;

CREATE TRIGGER IF NOT EXISTS semantic_claim_v2_guard
BEFORE INSERT ON ground_truth_semantic_claims_v2
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM ground_truth_claim_threads_v2 t
    WHERE t.annotation_thread_id = NEW.annotation_thread_id
      AND t.runner_id = NEW.runner_id
      AND t.subject_kind = NEW.subject_kind
      AND t.subject_key = NEW.subject_key
  ) THEN RAISE(ABORT, 'claim thread target mismatch') END;
  SELECT CASE WHEN NEW.revision = 1 AND NEW.supersedes_claim_id IS NOT NULL
    THEN RAISE(ABORT, 'first claim revision cannot supersede') END;
  SELECT CASE WHEN NEW.revision > 1 AND NOT EXISTS (
    SELECT 1 FROM ground_truth_semantic_claims_v2 p
    WHERE p.claim_id = NEW.supersedes_claim_id
      AND p.annotation_thread_id = NEW.annotation_thread_id
      AND p.dimension_name = NEW.dimension_name
      AND p.revision = NEW.revision - 1
  ) THEN RAISE(ABORT, 'invalid claim supersedes chain') END;
END;

CREATE TRIGGER IF NOT EXISTS workout_membership_v2_guard
BEFORE INSERT ON ground_truth_workout_memberships_v2
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM ground_truth_workout_groups g
    WHERE g.group_decision_id = NEW.group_decision_id
      AND g.workout_group_id = NEW.workout_group_id
      AND g.runner_id = NEW.runner_id
  ) THEN RAISE(ABORT, 'workout group identity mismatch') END;
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM ground_truth_claim_threads_v2 t
    WHERE t.annotation_thread_id = NEW.annotation_thread_id
      AND t.runner_id = NEW.runner_id
      AND t.subject_kind = 'workout_membership'
  ) THEN RAISE(ABORT, 'membership thread target mismatch') END;
  SELECT CASE WHEN NEW.revision = 1 AND NEW.supersedes_membership_decision_id IS NOT NULL
    THEN RAISE(ABORT, 'first membership revision cannot supersede') END;
  SELECT CASE WHEN NEW.revision > 1 AND NOT EXISTS (
    SELECT 1 FROM ground_truth_workout_memberships_v2 p
    WHERE p.membership_decision_id = NEW.supersedes_membership_decision_id
      AND p.annotation_thread_id = NEW.annotation_thread_id
      AND p.revision = NEW.revision - 1
  ) THEN RAISE(ABORT, 'invalid membership supersedes chain') END;
END;

CREATE TRIGGER IF NOT EXISTS workout_component_v3_guard
BEFORE INSERT ON ground_truth_workout_components_v3
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM ground_truth_workout_groups g
    WHERE g.group_decision_id = NEW.group_decision_id
      AND g.workout_group_id = NEW.workout_group_id
      AND g.runner_id = NEW.runner_id
  ) THEN RAISE(ABORT, 'workout component group identity mismatch') END;
  SELECT CASE WHEN NEW.recording_state = 'recorded' AND NOT EXISTS (
    SELECT 1 FROM ground_truth_workout_memberships_v2 m
    WHERE m.membership_decision_id = NEW.membership_decision_id
      AND m.runner_id = NEW.runner_id
      AND m.workout_group_id = NEW.workout_group_id
      AND m.group_decision_id = NEW.group_decision_id
      AND m.membership_state = 'included'
  ) THEN RAISE(ABORT, 'recorded component membership identity mismatch') END;
  SELECT CASE WHEN NEW.supersedes_component_decision_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM ground_truth_workout_components_v3 p
    WHERE p.component_decision_id = NEW.supersedes_component_decision_id
      AND p.component_id = NEW.component_id
      AND p.runner_id = NEW.runner_id
      AND p.workout_group_id = NEW.workout_group_id
      AND p.group_decision_id = NEW.group_decision_id
      AND p.component_order = NEW.component_order
  ) THEN RAISE(ABORT, 'invalid component supersedes chain') END;
  SELECT CASE WHEN NEW.supersedes_component_decision_id IS NOT NULL AND EXISTS (
    SELECT 1 FROM ground_truth_workout_components_v3 p
    WHERE p.component_decision_id = NEW.supersedes_component_decision_id
      AND (NEW.decision_timestamp < p.decision_timestamp
           OR NEW.label_available_at < p.label_available_at)
  ) THEN RAISE(ABORT, 'component revision temporal regression') END;
  SELECT CASE WHEN NEW.supersedes_component_decision_id IS NULL AND EXISTS (
    SELECT 1 FROM ground_truth_workout_components_v3 p WHERE p.component_id = NEW.component_id
  ) THEN RAISE(ABORT, 'component identity already exists') END;
  SELECT CASE WHEN NEW.supersedes_component_decision_id IS NULL AND EXISTS (
    SELECT 1 FROM ground_truth_workout_components_v3 p
    WHERE p.group_decision_id = NEW.group_decision_id AND p.component_order = NEW.component_order
      AND p.supersedes_component_decision_id IS NULL
  ) THEN RAISE(ABORT, 'component order already assigned') END;
  SELECT CASE WHEN NEW.supersedes_component_decision_id IS NOT NULL AND EXISTS (
    SELECT 1 FROM ground_truth_workout_components_v3 c
    WHERE c.supersedes_component_decision_id = NEW.supersedes_component_decision_id
  ) THEN RAISE(ABORT, 'component revision already superseded') END;
END;

CREATE TRIGGER IF NOT EXISTS component_evidence_v3_guard
BEFORE INSERT ON ground_truth_component_evidence_links_v3
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM ground_truth_workout_components_v3 c
    JOIN ground_truth_evidence_records_v2 e ON e.evidence_id = NEW.evidence_id
    WHERE c.component_decision_id = NEW.component_decision_id
      AND c.runner_id = e.runner_id
      AND e.recorded_at <= c.label_available_at
  ) THEN RAISE(ABORT, 'component evidence mismatch or unavailable') END;
END;

CREATE TRIGGER IF NOT EXISTS component_claim_thread_v3_guard
BEFORE INSERT ON ground_truth_component_claim_threads_v3
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM ground_truth_workout_components_v3 c
    WHERE c.component_id = NEW.component_id AND c.runner_id = NEW.runner_id
  ) THEN RAISE(ABORT, 'component claim thread target mismatch') END;
END;

CREATE TRIGGER IF NOT EXISTS component_claim_v3_guard
BEFORE INSERT ON ground_truth_component_claims_v3
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM ground_truth_component_claim_threads_v3 t
    WHERE t.annotation_thread_id = NEW.annotation_thread_id
      AND t.runner_id = NEW.runner_id
      AND t.component_id = NEW.component_id
      AND t.dimension_name = NEW.dimension_name
      AND t.item_index IS NEW.item_index
  ) THEN RAISE(ABORT, 'component claim thread target mismatch') END;
  SELECT CASE WHEN NEW.revision = 1 AND NEW.supersedes_claim_id IS NOT NULL
    THEN RAISE(ABORT, 'first component claim revision cannot supersede') END;
  SELECT CASE WHEN NEW.revision > 1 AND NOT EXISTS (
    SELECT 1 FROM ground_truth_component_claims_v3 p
    WHERE p.claim_id = NEW.supersedes_claim_id
      AND p.annotation_thread_id = NEW.annotation_thread_id
      AND p.revision = NEW.revision - 1
  ) THEN RAISE(ABORT, 'invalid component claim supersedes chain') END;
  SELECT CASE WHEN NEW.revision > 1 AND EXISTS (
    SELECT 1 FROM ground_truth_component_claims_v3 p
    WHERE p.claim_id = NEW.supersedes_claim_id
      AND (NEW.decision_timestamp < p.decision_timestamp
           OR NEW.label_available_at < p.label_available_at)
  ) THEN RAISE(ABORT, 'component claim temporal regression') END;
  SELECT CASE WHEN NEW.primary_evidence_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM ground_truth_evidence_records_v2 e
    WHERE e.evidence_id = NEW.primary_evidence_id
      AND e.runner_id = NEW.runner_id
      AND e.recorded_at <= NEW.label_available_at
  ) THEN RAISE(ABORT, 'component claim primary evidence mismatch or unavailable') END;
END;

CREATE TRIGGER IF NOT EXISTS component_claim_evidence_v3_guard
BEFORE INSERT ON ground_truth_component_claim_evidence_links_v3
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM ground_truth_component_claims_v3 c
    JOIN ground_truth_evidence_records_v2 e ON e.evidence_id = NEW.evidence_id
    WHERE c.claim_id = NEW.claim_id AND c.runner_id = e.runner_id
      AND e.recorded_at <= c.label_available_at
  ) THEN RAISE(ABORT, 'component claim evidence runner mismatch') END;
END;
"""


class GroundTruthStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "GroundTruthStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def initialize(self) -> None:
        self.connection.executescript(SCHEMA_SQL)
        self.connection.executescript(_immutable_triggers())
        self.connection.executescript(INTEGRITY_TRIGGERS)
        evidence_types = (
            ("canonical_instrumental", "Canonical measurement from a device or instrument", "instrumental"),
            ("manufacturer_interface", "Observation or interpretation exposed by a manufacturer interface", "manufacturer"),
            ("human_contemporary_log", "Human record created contemporaneously with the event", "human"),
            ("human_retrospective_report", "Human recollection reported after the event", "human"),
            ("coach_annotation", "Annotation supplied by a coach or qualified reviewer", "human"),
            ("external_document", "Documented evidence external to the wearable ecosystem", "external"),
            ("analytical_signal_inference", "Inference derived from an analytical procedure", "analytical"),
            ("synthetic_fixture", "Synthetic evidence used exclusively for tests", "analytical"),
            ("legacy_decision_evidence", "Evidence reference inherited from an unmodified v1 decision", "external"),
        )
        self.connection.executemany(
            """INSERT OR IGNORE INTO ground_truth_evidence_type_catalog_v2
            (catalog_version,evidence_type_id,definition,source_class,lifecycle_status,superseded_by_type_id)
            VALUES (?,?,?,?, 'active', NULL)""",
            [(REFINEMENT_EVIDENCE_CATALOG_VERSION, *row) for row in evidence_types],
        )
        self.connection.executemany(
            """INSERT OR IGNORE INTO ground_truth_activity_type_catalog_v3
            (catalog_version,activity_type_id,definition,lifecycle_status,
             superseded_by_type_id,created_at,code_commit,contract_version)
            VALUES (?,?,?,'active',NULL,?,?,?)""",
            [
                (
                    ACTIVITY_CATALOG_VERSION, activity_type, definition,
                    "2026-10-06T00:00:00.000000Z",
                    "389c748c82156be38cb856d52a5da8d361a6e342", COMPONENT_VERSION,
                )
                for activity_type, definition in sorted(ACTIVITY_TYPES_V1.items())
            ],
        )
        self.connection.commit()

    def table_names(self) -> list[str]:
        rows = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ground_truth_%' ORDER BY name"
        ).fetchall()
        return [row[0] for row in rows]

    def add_source_session(self, row: Mapping[str, Any]) -> None:
        date.fromisoformat(str(row["session_date"]))
        expected = temporal_partition(str(row["session_date"]))
        if row.get("temporal_partition", expected) != expected:
            raise ValueError("temporal partition does not match approved policy")
        with self.transaction() as db:
            db.execute(
                """INSERT INTO ground_truth_source_sessions
                (runner_id,source_file,source_sha256,session_date,temporal_partition,
                 temporal_partition_policy_version,source_manifest)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    row["runner_id"], row["source_file"], row["source_sha256"], row["session_date"],
                    expected, TEMPORAL_SPLIT_VERSION, row["source_manifest"],
                ),
            )

    def create_annotation_thread(
        self, *, runner_id: str, source_file: str, opened_by: str, opened_at: str,
        annotation_thread_id: str | None = None,
    ) -> str:
        return self.create_thread(
            runner_id=runner_id, target_kind="session", target_key=source_file,
            opened_by=opened_by, opened_at=opened_at,
            annotation_thread_id=annotation_thread_id,
        )

    def create_thread(
        self, *, runner_id: str, target_kind: str, target_key: str, opened_by: str,
        opened_at: str, annotation_thread_id: str | None = None,
    ) -> str:
        thread_id = annotation_thread_id or new_event_id()
        validate_uuid(thread_id, version=4)
        opened_at = _utc_timestamp(opened_at)
        with self.transaction() as db:
            db.execute(
                "INSERT INTO ground_truth_annotation_threads VALUES (?,?,?,?,?,?,?)",
                (thread_id, runner_id, target_kind, target_key, opened_by, opened_at, ADDENDUM_VERSION),
            )
        return thread_id

    def create_sampling_batch(self, row: Mapping[str, Any]) -> str:
        values = dict(row)
        batch_id = values.get("sampling_batch_id") or deterministic_id(
            "sampling-batch",
            (
                values["runner_id"], values["sampling_purpose"],
                values["sampling_strategy_version"], values["population_manifest"],
                values["knowledge_cutoff"],
            ),
        )
        values["sampling_batch_id"] = batch_id
        values.setdefault("temporal_partition_policy_version", TEMPORAL_SPLIT_VERSION)
        values.setdefault("contract_version", ADDENDUM_VERSION)
        values.setdefault("locked", 0)
        values["knowledge_cutoff"] = _utc_timestamp(values["knowledge_cutoff"])
        values["created_at"] = _utc_timestamp(values["created_at"])
        columns = [
            "sampling_batch_id", "runner_id", "sampling_strategy_version",
            "temporal_partition_policy_version", "sampling_purpose", "population_manifest",
            "population_size", "requested_unit_count", "selection_method", "random_seed",
            "strata_definition", "selection_algorithm", "feature_snapshot_manifest",
            "knowledge_cutoff", "created_at", "created_by", "code_commit",
            "contract_version", "locked", "notes",
        ]
        if not isinstance(values["strata_definition"], str):
            values["strata_definition"] = json.dumps(values["strata_definition"], sort_keys=True, separators=(",", ":"))
        with self.transaction() as db:
            db.execute(
                f"INSERT INTO ground_truth_sampling_batches ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(values.get(column) for column in columns),
            )
        return batch_id

    def create_review_unit(self, row: Mapping[str, Any]) -> tuple[str, str]:
        values = dict(row)
        unit_id = values.get("review_unit_id") or deterministic_id(
            "review-unit", (values["runner_id"], values["review_unit_type"], values["data_manifest"])
        )
        revision = int(values.get("revision", 1))
        record_id = values.get("review_unit_record_id") or deterministic_id(
            "review-unit-record", (unit_id, revision, values["data_manifest"])
        )
        values.update(
            review_unit_id=unit_id, review_unit_record_id=record_id, revision=revision,
            temporal_partition_policy_version=TEMPORAL_SPLIT_VERSION,
            contract_version=ADDENDUM_VERSION,
        )
        values["knowledge_cutoff"] = _utc_timestamp(values["knowledge_cutoff"])
        columns = [
            "review_unit_record_id", "review_unit_id", "revision",
            "supersedes_review_unit_record_id", "runner_id", "review_unit_type",
            "sampling_batch_id", "sampling_strategy_version", "sampling_stratum",
            "selection_reason", "selection_probability", "selection_probability_missing_reason",
            "temporal_partition", "temporal_partition_policy_version", "review_status",
            "reviewer_id", "reviewer_role", "semantics_mode", "knowledge_cutoff",
            "data_manifest", "feature_contract_version", "code_commit", "contract_version",
        ]
        with self.transaction() as db:
            db.execute(
                f"INSERT INTO ground_truth_review_units ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(values.get(column) for column in columns),
            )
        return unit_id, record_id

    def add_review_membership(self, row: Mapping[str, Any]) -> str:
        values = dict(row)
        record_id = values.get("review_membership_record_id") or deterministic_id(
            "review-membership",
            (values["review_unit_record_id"], values["source_file"], values["presentation_order"]),
        )
        values["review_membership_record_id"] = record_id
        columns = [
            "review_membership_record_id", "review_unit_record_id", "runner_id",
            "source_file", "source_sha256", "presentation_order", "membership_reason",
        ]
        with self.transaction() as db:
            db.execute(
                f"INSERT INTO ground_truth_review_unit_memberships ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(values[column] for column in columns),
            )
        return record_id

    def lock_sampling_batch(self, sampling_batch_id: str) -> None:
        with self.transaction() as db:
            changed = db.execute(
                "UPDATE ground_truth_sampling_batches SET locked=1 WHERE sampling_batch_id=? AND locked=0",
                (sampling_batch_id,),
            ).rowcount
            if changed != 1:
                raise ValueError("sampling batch is missing or already locked")

    def add_session_decision(self, row: Mapping[str, Any]) -> None:
        validate_uuid(str(row["decision_id"]), version=4)
        columns = [
            "decision_id", "annotation_thread_id", "revision", "supersedes_decision_id",
            "decision_kind", "runner_id", "source_file", "source_sha256", "author_id",
            "author_role", "evidence_observed_at", "decision_timestamp", "effective_from",
            "label_available_at", "evidence_type", "evidence_catalog_version",
            "evidence_reference", "evidence_level", "session_context", "session_context_status",
            "workout_structure", "workout_structure_status", "primary_function",
            "primary_function_status", "primary_function_subtype",
            "primary_function_subtype_status", "component_role", "component_role_status",
            "performance_relevance", "performance_relevance_status",
            "training_load_relevance", "training_load_relevance_status",
            "uncertainty_reason", "comment", "code_commit", "contract_version",
        ]
        values = dict(row)
        for field in ("decision_timestamp", "effective_from", "label_available_at"):
            values[field] = _utc_timestamp(values[field])
        if values.get("evidence_observed_at") is not None:
            values["evidence_observed_at"] = _utc_timestamp(values["evidence_observed_at"])
        if values["label_available_at"] < values["decision_timestamp"]:
            raise ValueError("label_available_at cannot precede decision_timestamp")
        values.setdefault("evidence_catalog_version", EVIDENCE_CATALOG_VERSION)
        values.setdefault("contract_version", ADDENDUM_VERSION)
        with self.transaction() as db:
            db.execute(
                f"INSERT INTO ground_truth_session_decisions ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(values.get(column) for column in columns),
            )

    def add_workout_group(self, row: Mapping[str, Any]) -> None:
        values = dict(row)
        validate_uuid(str(values["group_decision_id"]), version=4)
        validate_uuid(str(values["workout_group_id"]), version=4)
        values.setdefault("evidence_catalog_version", EVIDENCE_CATALOG_VERSION)
        values.setdefault("contract_version", ADDENDUM_VERSION)
        values["decision_timestamp"] = _utc_timestamp(values["decision_timestamp"])
        values["label_available_at"] = _utc_timestamp(values["label_available_at"])
        if not isinstance(values["evidence_types"], str):
            values["evidence_types"] = json.dumps(values["evidence_types"], sort_keys=True, separators=(",", ":"))
        columns = [
            "group_decision_id", "workout_group_id", "annotation_thread_id", "revision",
            "supersedes_group_decision_id", "decision_kind", "runner_id", "group_status",
            "evidence_level", "evidence_types", "evidence_catalog_version",
            "evidence_reference", "decision_timestamp", "label_available_at", "author_id",
            "author_role", "code_commit", "contract_version",
        ]
        with self.transaction() as db:
            db.execute(
                f"INSERT INTO ground_truth_workout_groups ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(values.get(column) for column in columns),
            )

    def add_group_membership(self, row: Mapping[str, Any]) -> None:
        values = dict(row)
        validate_uuid(str(values["membership_decision_id"]), version=4)
        values["decision_timestamp"] = _utc_timestamp(values["decision_timestamp"])
        values["label_available_at"] = _utc_timestamp(values["label_available_at"])
        columns = [
            "membership_decision_id", "annotation_thread_id", "revision",
            "supersedes_membership_decision_id", "workout_group_id", "group_decision_id",
            "runner_id", "source_file", "source_sha256", "membership_status",
            "component_order", "component_role", "evidence_level", "decision_timestamp",
            "label_available_at",
        ]
        with self.transaction() as db:
            db.execute(
                f"INSERT INTO ground_truth_group_memberships ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(values.get(column) for column in columns),
            )

    def create_claim_thread_v2(
        self, *, runner_id: str, subject_kind: str, subject_key: str,
        opened_by: str, opened_at: str, annotation_thread_id: str | None = None,
    ) -> str:
        thread_id = annotation_thread_id or new_event_id()
        try:
            validate_uuid(thread_id, version=4)
        except ValueError:
            validate_uuid(thread_id, version=5)
        opened_at = _utc_timestamp(opened_at)
        with self.transaction() as db:
            db.execute(
                """INSERT INTO ground_truth_claim_threads_v2
                (annotation_thread_id,runner_id,subject_kind,subject_key,opened_by,opened_at,contract_version)
                VALUES (?,?,?,?,?,?,?)""",
                (thread_id, runner_id, subject_kind, subject_key, opened_by, opened_at, REFINEMENT_VERSION),
            )
        return thread_id

    def add_evidence_record_v2(self, row: Mapping[str, Any]) -> None:
        values = dict(row)
        try:
            validate_uuid(str(values["evidence_id"]), version=4)
        except ValueError:
            validate_uuid(str(values["evidence_id"]), version=5)
        values.setdefault("evidence_catalog_version", REFINEMENT_EVIDENCE_CATALOG_VERSION)
        values.setdefault("contract_version", REFINEMENT_VERSION)
        values["recorded_at"] = _utc_timestamp(values["recorded_at"])
        if values.get("evidence_observed_at") is not None:
            values["evidence_observed_at"] = _utc_timestamp(values["evidence_observed_at"])
        columns = (
            "evidence_id", "runner_id", "evidence_type_id", "evidence_catalog_version",
            "source_system", "source_locator", "source_content_sha256",
            "evidence_observed_at", "recorded_at", "scientific_purpose",
            "data_minimization_note", "code_commit", "contract_version",
        )
        with self.transaction() as db:
            db.execute(
                f"INSERT INTO ground_truth_evidence_records_v2 ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(values.get(column) for column in columns),
            )

    def add_semantic_claim_v2(self, row: Mapping[str, Any]) -> None:
        values = dict(row)
        validate_uuid(
            str(values["claim_id"]),
            version=5 if values.get("decision_kind") == "migration" else 4,
        )
        validate_claim(values)
        for field in ("decision_timestamp", "effective_from", "label_available_at"):
            values[field] = _utc_timestamp(values[field])
        if values.get("evidence_observed_at") is not None:
            values["evidence_observed_at"] = _utc_timestamp(values["evidence_observed_at"])
        if values["label_available_at"] < values["decision_timestamp"]:
            raise ValueError("label_available_at cannot precede decision_timestamp")
        values.setdefault("provenance_granularity", "atomic")
        values.setdefault("contract_version", REFINEMENT_VERSION)
        columns = (
            "claim_id", "annotation_thread_id", "revision", "supersedes_claim_id",
            "decision_kind", "runner_id", "subject_kind", "subject_key", "source_file",
            "source_sha256", "dimension_name", "claim_value", "claim_status", "claim_kind",
            "evidence_level", "author_id", "author_role", "rationale", "uncertainty_reason",
            "evidence_observed_at", "decision_timestamp", "effective_from", "label_available_at",
            "provenance_granularity", "legacy_decision_id", "code_commit", "contract_version",
        )
        with self.transaction() as db:
            db.execute(
                f"INSERT INTO ground_truth_semantic_claims_v2 ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(values.get(column) for column in columns),
            )

    def link_claim_evidence_v2(
        self, *, claim_id: str, evidence_id: str, support_role: str,
        rationale: str | None = None, link_id: str | None = None,
    ) -> str:
        link_id = link_id or deterministic_id("claim-evidence-v2", (claim_id, evidence_id, support_role))
        with self.transaction() as db:
            db.execute(
                """INSERT INTO ground_truth_claim_evidence_links_v2
                (claim_evidence_link_id,claim_id,evidence_id,support_role,rationale)
                VALUES (?,?,?,?,?)""",
                (link_id, claim_id, evidence_id, support_role, rationale),
            )
        return link_id

    def add_workout_membership_v2(self, row: Mapping[str, Any]) -> None:
        values = dict(row)
        validate_uuid(str(values["membership_decision_id"]), version=4)
        if values["membership_state"] not in MEMBERSHIP_STATES:
            raise ValueError(f"unsupported membership_state: {values['membership_state']}")
        if values["claim_kind"] not in CLAIM_KINDS:
            raise ValueError(f"unsupported claim_kind: {values['claim_kind']}")
        if values["evidence_level"] not in EVIDENCE_LEVELS:
            raise ValueError(f"unsupported evidence_level: {values['evidence_level']}")
        if values["membership_state"] in {"unknown", "abstained"}:
            if values.get("component_order") is not None or values.get("component_role") is not None:
                raise ValueError("unknown or abstained membership cannot assert order or role")
            if not str(values.get("uncertainty_reason") or "").strip():
                raise ValueError("unknown or abstained membership requires a reason")
        for field in ("decision_timestamp", "effective_from", "label_available_at"):
            values[field] = _utc_timestamp(values[field])
        if values.get("evidence_observed_at") is not None:
            values["evidence_observed_at"] = _utc_timestamp(values["evidence_observed_at"])
        values.setdefault("contract_version", REFINEMENT_VERSION)
        columns = (
            "membership_decision_id", "annotation_thread_id", "revision",
            "supersedes_membership_decision_id", "decision_kind", "runner_id",
            "workout_group_id", "group_decision_id", "source_file", "source_sha256",
            "membership_state", "component_order", "component_role", "claim_kind",
            "evidence_level", "author_id", "author_role", "rationale", "uncertainty_reason",
            "evidence_observed_at", "decision_timestamp", "effective_from", "label_available_at",
            "code_commit", "contract_version",
        )
        with self.transaction() as db:
            db.execute(
                f"INSERT INTO ground_truth_workout_memberships_v2 ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(values.get(column) for column in columns),
            )

    def link_membership_evidence_v2(
        self, *, membership_decision_id: str, evidence_id: str, support_role: str,
        rationale: str | None = None, link_id: str | None = None,
    ) -> str:
        link_id = link_id or deterministic_id(
            "membership-evidence-v2", (membership_decision_id, evidence_id, support_role)
        )
        with self.transaction() as db:
            db.execute(
                """INSERT INTO ground_truth_membership_evidence_links_v2
                (membership_evidence_link_id,membership_decision_id,evidence_id,support_role,rationale)
                VALUES (?,?,?,?,?)""",
                (link_id, membership_decision_id, evidence_id, support_role, rationale),
            )
        return link_id

    def add_workout_component_v3(
        self, row: Mapping[str, Any], *, evidence_links: Sequence[Mapping[str, Any]]
    ) -> None:
        """Atomically add a component and at least one provenance link."""
        if not evidence_links:
            raise ValueError("workout component requires evidence")
        values = dict(row)
        validate_component(values)
        decision_version = 5 if values.get("decision_kind") == "migration" else 4
        validate_uuid(str(values["component_decision_id"]), version=decision_version)
        try:
            validate_uuid(str(values["component_id"]), version=4)
        except ValueError:
            validate_uuid(str(values["component_id"]), version=5)
        values.setdefault("contract_version", COMPONENT_VERSION)
        if values.get("activity_type_id") is not None:
            values.setdefault("activity_catalog_version", ACTIVITY_CATALOG_VERSION)
        for field in ("start_time", "end_time", "decision_timestamp", "effective_from", "label_available_at"):
            if values.get(field) is not None:
                values[field] = _utc_timestamp(values[field])
        if values.get("evidence_observed_at") is not None:
            values["evidence_observed_at"] = _utc_timestamp(values["evidence_observed_at"])
        if values["label_available_at"] < values["decision_timestamp"]:
            raise ValueError("label_available_at cannot precede decision_timestamp")
        columns = (
            "component_decision_id", "component_id", "supersedes_component_decision_id",
            "decision_kind",
            "runner_id", "workout_group_id", "group_decision_id", "component_order",
            "recording_state", "membership_decision_id", "activity_catalog_version",
            "activity_type_id", "component_role", "start_time", "end_time",
            "temporal_precision", "duration_s", "duration_basis", "claim_kind",
            "evidence_level", "author_id", "author_role", "evidence_observed_at",
            "decision_timestamp", "effective_from", "label_available_at",
            "uncertainty_reason", "rationale", "code_commit", "contract_version",
        )
        with self.transaction() as db:
            self._insert_workout_component_v3(db, values, evidence_links, columns=columns)

    def _insert_workout_component_v3(
        self, db: sqlite3.Connection, values: Mapping[str, Any],
        evidence_links: Sequence[Mapping[str, Any]], *, columns: Sequence[str] | None = None,
    ) -> None:
        columns = columns or (
            "component_decision_id", "component_id", "supersedes_component_decision_id", "decision_kind",
            "runner_id", "workout_group_id", "group_decision_id", "component_order",
            "recording_state", "membership_decision_id", "activity_catalog_version",
            "activity_type_id", "component_role", "start_time", "end_time",
            "temporal_precision", "duration_s", "duration_basis", "claim_kind",
            "evidence_level", "author_id", "author_role", "evidence_observed_at",
            "decision_timestamp", "effective_from", "label_available_at",
            "uncertainty_reason", "rationale", "code_commit", "contract_version",
        )
        db.execute(
                f"INSERT INTO ground_truth_workout_components_v3 ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(values.get(column) for column in columns),
            )
        for raw_link in evidence_links:
            link = dict(raw_link)
            support_role = str(link.get("support_role", "support"))
            link_id = link.get("component_evidence_link_id") or deterministic_id(
                "component-evidence-v3", (values["component_decision_id"], link["evidence_id"], support_role),
            )
            db.execute(
                    """INSERT INTO ground_truth_component_evidence_links_v3
                    (component_evidence_link_id,component_decision_id,evidence_id,support_role,rationale)
                    VALUES (?,?,?,?,?)""",
                    (link_id, values["component_decision_id"], link["evidence_id"], support_role, link.get("rationale")),
                )

    def create_component_claim_thread_v3(
        self, *, runner_id: str, component_id: str, dimension_name: str,
        opened_by: str, opened_at: str, item_index: int | None = None,
        annotation_thread_id: str | None = None,
    ) -> str:
        thread_id = annotation_thread_id or new_event_id()
        try:
            validate_uuid(thread_id, version=4)
        except ValueError:
            validate_uuid(thread_id, version=5)
        with self.transaction() as db:
            db.execute(
                """INSERT INTO ground_truth_component_claim_threads_v3
                (annotation_thread_id,runner_id,component_id,dimension_name,item_index,
                 opened_by,opened_at,contract_version)
                VALUES (?,?,?,?,?,?,?,?)""",
                (
                    thread_id, runner_id, component_id, dimension_name, item_index,
                    opened_by, _utc_timestamp(opened_at), COMPONENT_VERSION,
                ),
            )
        return thread_id

    def add_component_claim_v3(
        self, row: Mapping[str, Any], *, evidence_links: Sequence[Mapping[str, Any]] = ()
    ) -> None:
        values = dict(row)
        validate_uuid(
            str(values["claim_id"]),
            version=5 if values.get("decision_kind") == "migration" else 4,
        )
        validate_component_claim(values)
        if values["claim_status"] in {"asserted", "uncertain"} and not evidence_links:
            raise ValueError("asserted or uncertain component claim requires evidence")
        if evidence_links:
            values.setdefault("primary_evidence_id", evidence_links[0]["evidence_id"])
        for field in ("decision_timestamp", "effective_from", "label_available_at"):
            values[field] = _utc_timestamp(values[field])
        if values.get("evidence_observed_at") is not None:
            values["evidence_observed_at"] = _utc_timestamp(values["evidence_observed_at"])
        if values["label_available_at"] < values["decision_timestamp"]:
            raise ValueError("label_available_at cannot precede decision_timestamp")
        values.setdefault("contract_version", COMPONENT_VERSION)
        columns = (
            "claim_id", "annotation_thread_id", "revision", "supersedes_claim_id", "primary_evidence_id",
            "decision_kind", "runner_id", "component_id", "dimension_name", "item_index",
            "claim_status", "value_kind", "integer_value", "numeric_value", "text_value",
            "range_lower_value", "range_upper_value", "unit", "value_qualifier",
            "claim_kind", "evidence_level", "author_id", "author_role", "rationale",
            "uncertainty_reason", "evidence_observed_at", "decision_timestamp",
            "effective_from", "label_available_at", "code_commit", "contract_version",
        )
        with self.transaction() as db:
            db.execute(
                f"INSERT INTO ground_truth_component_claims_v3 ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(values.get(column) for column in columns),
            )
            for raw_link in evidence_links:
                link = dict(raw_link)
                role = str(link.get("support_role", "support"))
                link_id = link.get("claim_evidence_link_id") or deterministic_id(
                    "component-claim-evidence-v3", (values["claim_id"], link["evidence_id"], role),
                )
                db.execute(
                    """INSERT INTO ground_truth_component_claim_evidence_links_v3
                    (claim_evidence_link_id,claim_id,evidence_id,support_role,rationale)
                    VALUES (?,?,?,?,?)""",
                    (link_id, values["claim_id"], link["evidence_id"], role, link.get("rationale")),
                )

    def _component_source_files(self, component_rows: Sequence[Mapping[str, Any]]) -> list[str]:
        sources: set[str] = set()
        for row in component_rows:
            if row.get("membership_decision_id"):
                found = self.connection.execute(
                    "SELECT source_file FROM ground_truth_workout_memberships_v2 WHERE membership_decision_id=?",
                    (row["membership_decision_id"],),
                ).fetchone()
                if found: sources.add(str(found[0]))
            else:
                sources.update(str(item[0]) for item in self.connection.execute(
                    """SELECT source_file FROM ground_truth_workout_memberships_v2
                       WHERE group_decision_id=? AND membership_state='included'""",
                    (row["group_decision_id"],),
                ).fetchall())
        return sorted(sources)

    def latest_workout_components_as_of_v3(
        self, knowledge_cutoff: str, *, purpose: str
    ) -> list[dict[str, Any]]:
        cutoff = _utc_timestamp(knowledge_cutoff)
        rows = self.connection.execute(
            """WITH visible_groups AS (
                 SELECT g.*, ROW_NUMBER() OVER (
                   PARTITION BY g.workout_group_id ORDER BY g.revision DESC
                 ) AS group_rank
                 FROM ground_truth_workout_groups g
                 WHERE g.decision_timestamp <= ? AND g.label_available_at <= ?
               )
               , visible_components AS (
                 SELECT c.*
                 FROM ground_truth_workout_components_v3 c
                 WHERE c.decision_timestamp <= ? AND c.label_available_at <= ?
               )
               SELECT c.* FROM visible_components c
               JOIN visible_groups g ON g.group_decision_id=c.group_decision_id AND g.group_rank=1
               WHERE NOT EXISTS (
                 SELECT 1 FROM visible_components successor
                 WHERE successor.supersedes_component_decision_id=c.component_decision_id
               )
               ORDER BY c.runner_id,c.workout_group_id,c.component_order""",
            (cutoff, cutoff, cutoff, cutoff),
        ).fetchall()
        output = [dict(row) for row in rows]
        self.assert_purpose_allowed(purpose=purpose, source_files=self._component_source_files(output))
        return output

    def latest_component_claims_as_of_v3(self, knowledge_cutoff: str, *, purpose: str) -> list[dict[str, Any]]:
        self.assert_purpose_allowed(purpose=purpose, source_files=())
        cutoff = _utc_timestamp(knowledge_cutoff)
        rows = self.connection.execute(
            """WITH eligible AS (
                 SELECT c.*, ROW_NUMBER() OVER (
                   PARTITION BY c.annotation_thread_id ORDER BY c.revision DESC
                 ) AS rank_in_thread
                 FROM ground_truth_component_claims_v3 c
                 WHERE c.decision_timestamp <= ? AND c.label_available_at <= ?
               )
               SELECT * FROM eligible WHERE rank_in_thread=1
               ORDER BY runner_id,component_id,dimension_name,item_index,annotation_thread_id""",
            (cutoff, cutoff),
        ).fetchall()
        output = [dict(row) for row in rows]
        component_ids = sorted({row["component_id"] for row in output})
        if component_ids:
            marks = ",".join("?" for _ in component_ids)
            components = [dict(row) for row in self.connection.execute(
                f"SELECT * FROM ground_truth_workout_components_v3 WHERE component_id IN ({marks})", component_ids
            ).fetchall()]
            self.assert_purpose_allowed(purpose=purpose, source_files=self._component_source_files(components))
        return output

    def build_component_gold_v3(self, *, product: str, knowledge_cutoff: str, purpose: str) -> list[dict[str, Any]]:
        return compose_component_gold(
            self.latest_component_claims_as_of_v3(knowledge_cutoff, purpose=purpose), product=product
        )

    def latest_semantic_claims_as_of_v2(self, knowledge_cutoff: str) -> list[dict[str, Any]]:
        cutoff = _utc_timestamp(knowledge_cutoff)
        rows = self.connection.execute(
            """WITH eligible AS (
                SELECT c.*, ROW_NUMBER() OVER (
                    PARTITION BY c.annotation_thread_id ORDER BY c.revision DESC
                ) AS rank_in_thread
                FROM ground_truth_semantic_claims_v2 c
                WHERE c.decision_timestamp <= ? AND c.label_available_at <= ?
            )
            SELECT * FROM eligible WHERE rank_in_thread = 1
            ORDER BY runner_id,subject_kind,subject_key,dimension_name,annotation_thread_id""",
            (cutoff, cutoff),
        ).fetchall()
        return [dict(row) for row in rows]

    def latest_workout_memberships_as_of_v2(self, knowledge_cutoff: str) -> list[dict[str, Any]]:
        cutoff = _utc_timestamp(knowledge_cutoff)
        rows = self.connection.execute(
            """WITH eligible AS (
                SELECT m.*, ROW_NUMBER() OVER (
                    PARTITION BY m.annotation_thread_id ORDER BY m.revision DESC
                ) AS rank_in_thread
                FROM ground_truth_workout_memberships_v2 m
                WHERE m.decision_timestamp <= ? AND m.label_available_at <= ?
            )
            SELECT * FROM eligible WHERE rank_in_thread = 1
            ORDER BY runner_id,workout_group_id,component_order,source_file""",
            (cutoff, cutoff),
        ).fetchall()
        return [dict(row) for row in rows]

    def build_dimension_gold_v2(self, *, product: str, knowledge_cutoff: str) -> list[dict[str, Any]]:
        return compose_dimension_gold(
            self.latest_semantic_claims_as_of_v2(knowledge_cutoff), product=product
        )

    def latest_session_decisions_as_of(self, knowledge_cutoff: str) -> list[dict[str, Any]]:
        knowledge_cutoff = _utc_timestamp(knowledge_cutoff)
        rows = self.connection.execute(
            """WITH eligible AS (
                SELECT d.*, ROW_NUMBER() OVER (
                    PARTITION BY d.annotation_thread_id ORDER BY d.revision DESC
                ) AS rank_in_thread
                FROM ground_truth_session_decisions d
                WHERE d.decision_timestamp <= ? AND d.label_available_at <= ?
            )
            SELECT * FROM eligible WHERE rank_in_thread = 1
            ORDER BY runner_id, source_file, annotation_thread_id""",
            (knowledge_cutoff, knowledge_cutoff),
        ).fetchall()
        return [dict(row) for row in rows]

    def build_gold(self, *, product: str, knowledge_cutoff: str) -> list[dict[str, Any]]:
        if product not in {"gold_core", "gold_extended"}:
            raise ValueError("product must be gold_core or gold_extended")
        levels = {"verified"} if product == "gold_core" else {"verified", "reported"}
        decisions = self.latest_session_decisions_as_of(knowledge_cutoff)
        output: list[dict[str, Any]] = []
        by_session: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in decisions:
            if row["evidence_level"] in levels:
                by_session.setdefault((row["runner_id"], row["source_file"]), []).append(row)
        semantic_fields = (
            "session_context", "session_context_status", "workout_structure",
            "workout_structure_status", "primary_function", "primary_function_status",
            "primary_function_subtype", "primary_function_subtype_status", "component_role",
            "component_role_status", "performance_relevance", "performance_relevance_status",
            "training_load_relevance", "training_load_relevance_status",
        )
        for key, rows in sorted(by_session.items()):
            asserted = {
                logical_hash({field: row[field] for field in semantic_fields}, domain="d4-gt-semantic-label-v1")
                for row in rows
            }
            if len(asserted) != 1 and len(rows) > 1:
                continue  # unresolved independent opinions remain preserved but are not gold
            row = dict(sorted(rows, key=lambda item: item["annotation_thread_id"])[0])
            row.pop("rank_in_thread", None)
            row["gold_product"] = product
            output.append(row)
        return output

    def assert_purpose_allowed(self, *, purpose: str, source_files: Sequence[str]) -> None:
        if purpose not in PURPOSE_LOCKED_TEST_ACCESS:
            raise ValueError(f"unknown access purpose: {purpose}")
        if PURPOSE_LOCKED_TEST_ACCESS[purpose]:
            return
        if not source_files:
            return
        marks = ",".join("?" for _ in source_files)
        found = self.connection.execute(
            f"SELECT source_file FROM ground_truth_source_sessions WHERE temporal_partition='locked_test' AND source_file IN ({marks}) LIMIT 1",
            tuple(source_files),
        ).fetchone()
        if found:
            raise LockedTestAccessError(f"{purpose} cannot access locked_test: {found['source_file']}")

    def source_population_manifest(self) -> str:
        rows = [dict(row) for row in self.connection.execute(
            "SELECT * FROM ground_truth_source_sessions ORDER BY runner_id, source_file"
        ).fetchall()]
        return logical_records_hash(
            rows, domain="d4-gt-population-manifest-v1", order_by=("runner_id", "source_file", "source_sha256")
        )

    def schema_manifest(self) -> str:
        rows = [dict(row) for row in self.connection.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE name LIKE 'ground_truth_%' ORDER BY type,name"
        ).fetchall()]
        return logical_hash(
            {
                "legacy_schema_version": SCHEMA_VERSION,
                "refinement_schema_version": REFINEMENT_SCHEMA_VERSION,
                "component_schema_version": COMPONENT_SCHEMA_VERSION,
                "id_strategy": ID_STRATEGY_VERSION,
                "objects": rows,
            },
            domain="d4-gt-schema-manifest-v2",
        )
