"""Explicit additive adapter for the frozen D4 manual decision shape."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


D4_COMPATIBILITY_COLUMNS = (
    "decision_id", "runner_id", "source_file", "source_sha256", "revision",
    "author_id", "author_role", "decision_timestamp", "effective_from",
    "supersedes_decision_id", "evidence_type", "evidence_reference",
    "evidence_level", "session_context", "workout_structure", "primary_function",
    "primary_function_detail", "component_role", "performance_relevance",
    "training_load_relevance", "decision_reason", "contract_version",
)


def to_frozen_d4_rows(resolved_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Map only already-resolved Addendum rows; never resolve independent threads here."""
    seen: set[tuple[str, str]] = set()
    output: list[dict[str, Any]] = []
    for row in resolved_rows:
        key = (str(row["runner_id"]), str(row["source_file"]))
        if key in seen:
            raise ValueError("adapter requires one explicitly resolved decision per session")
        seen.add(key)
        mapped = {
            "decision_id": row["decision_id"],
            "runner_id": row["runner_id"],
            "source_file": row["source_file"],
            "source_sha256": row["source_sha256"],
            "revision": row["revision"],
            "author_id": row["author_id"],
            "author_role": row["author_role"],
            "decision_timestamp": row["decision_timestamp"],
            "effective_from": row["effective_from"],
            "supersedes_decision_id": row["supersedes_decision_id"] or "",
            "evidence_type": row["evidence_type"],
            "evidence_reference": row["evidence_reference"],
            "evidence_level": row["evidence_level"],
            "session_context": row["session_context"] or "",
            "workout_structure": row["workout_structure"] or "",
            "primary_function": row["primary_function"] or "unknown",
            "primary_function_detail": row["primary_function_subtype"] or "",
            "component_role": row["component_role"] or "unknown",
            "performance_relevance": row["performance_relevance"] or "uncertain",
            "training_load_relevance": row["training_load_relevance"] or "uncertain",
            "decision_reason": row["comment"] or row["uncertainty_reason"] or "",
            "contract_version": row["contract_version"],
        }
        output.append({column: mapped[column] for column in D4_COMPATIBILITY_COLUMNS})
    return output

