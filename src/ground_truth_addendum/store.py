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
    ADDENDUM_VERSION,
    EVIDENCE_CATALOG_VERSION,
    PROHIBITED_LOCKED_TEST_PURPOSES,
    SCHEMA_VERSION,
    TEMPORAL_SPLIT_VERSION,
    temporal_partition,
)
from .ids import ID_STRATEGY_VERSION, deterministic_id, new_event_id, validate_uuid


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
        if purpose not in PROHIBITED_LOCKED_TEST_PURPOSES:
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
            {"schema_version": SCHEMA_VERSION, "id_strategy": ID_STRATEGY_VERSION, "objects": rows},
            domain="d4-gt-schema-manifest-v1",
        )
