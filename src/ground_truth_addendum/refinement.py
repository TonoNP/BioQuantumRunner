"""Scientific invariants for atomic D4 Ground Truth claims.

This module is additive.  It does not reinterpret or mutate v1 decisions.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

from .contracts import (
    CLAIM_DIMENSIONS,
    CLAIM_KINDS,
    CLAIM_SUBJECT_KINDS,
    DIMENSION_STATUSES,
    EVIDENCE_LEVELS,
)


def validate_claim(row: Mapping[str, Any]) -> None:
    """Validate value/status and epistemic invariants before persistence."""
    status = str(row["claim_status"])
    value = row.get("claim_value")
    if status not in DIMENSION_STATUSES:
        raise ValueError(f"unsupported claim_status: {status}")
    if str(row["claim_kind"]) not in CLAIM_KINDS:
        raise ValueError(f"unsupported claim_kind: {row['claim_kind']}")
    if str(row["subject_kind"]) not in CLAIM_SUBJECT_KINDS:
        raise ValueError(f"unsupported subject_kind: {row['subject_kind']}")
    if str(row["dimension_name"]) not in CLAIM_DIMENSIONS:
        raise ValueError(f"unsupported dimension_name: {row['dimension_name']}")
    if str(row["evidence_level"]) not in EVIDENCE_LEVELS:
        raise ValueError(f"unsupported evidence_level: {row['evidence_level']}")
    if status == "asserted" and (value is None or str(value).strip() == ""):
        raise ValueError("asserted claim requires a non-empty value")
    if status in {"unknown", "abstained", "not_applicable"} and value is not None:
        raise ValueError(f"{status} claim cannot carry a value")
    if status == "uncertain" and not str(row.get("uncertainty_reason") or "").strip():
        raise ValueError("uncertain claim requires uncertainty_reason")
    if status in {"abstained", "not_applicable"} and not str(row.get("uncertainty_reason") or "").strip():
        raise ValueError(f"{status} claim requires a reason")


def compose_dimension_gold(
    claims: Iterable[Mapping[str, Any]], *, product: str
) -> list[dict[str, Any]]:
    """Resolve atomic claims deterministically without manufacturing consensus.

    Missing annotation is intentionally not emitted as a claim.  Callers derive
    it from the eligible population minus represented subject/dimension pairs.
    """
    if product not in {"gold_core", "gold_extended"}:
        raise ValueError("product must be gold_core or gold_extended")
    accepted_levels = {"verified"} if product == "gold_core" else {"verified", "reported"}
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for raw in claims:
        row = dict(raw)
        if row["evidence_level"] in accepted_levels:
            key = (
                row["runner_id"], row["subject_kind"], row["subject_key"],
                row["dimension_name"],
            )
            grouped[key].append(row)

    output: list[dict[str, Any]] = []
    for key, rows in sorted(grouped.items()):
        rows.sort(key=lambda r: (r["annotation_thread_id"], int(r["revision"]), r["claim_id"]))
        meanings = {(r["claim_status"], r.get("claim_value")) for r in rows}
        base = {
            "runner_id": key[0], "subject_kind": key[1], "subject_key": key[2],
            "dimension_name": key[3], "gold_product": product,
            "source_claim_ids": [r["claim_id"] for r in rows],
            "source_thread_ids": sorted({r["annotation_thread_id"] for r in rows}),
        }
        if len(meanings) > 1:
            output.append({
                **base, "resolution_status": "conflicted", "claim_status": None,
                "claim_value": None, "reason_code": "CONFLICT_UNRESOLVED",
            })
            continue
        status, value = next(iter(meanings))
        reason = {
            "abstained": "ABSTAINED", "unknown": "UNKNOWN",
            "not_applicable": "NOT_APPLICABLE",
        }.get(status, "AGREEMENT_NO_ADJUDICATION" if len(rows) > 1 else "SINGLE_CLAIM")
        output.append({
            **base, "resolution_status": "resolved", "claim_status": status,
            "claim_value": value, "reason_code": reason,
            "claim_kinds": sorted({r["claim_kind"] for r in rows}),
            "evidence_levels": sorted({r["evidence_level"] for r in rows}),
        })
    return output
