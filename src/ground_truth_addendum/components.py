"""Scientific invariants for additive D4.1 workout components.

This module contains no data-loading heuristics.  In particular, temporal
gaps are never converted into components and unknown context is never treated
as zero load.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import math
from numbers import Integral, Real
from typing import Any, Iterable, Mapping

from .contracts import (
    ACTIVITY_TYPES_V1,
    ANALYSIS_USABILITY_RESULTS,
    CLAIM_KINDS,
    COMPONENT_DIMENSIONS,
    COMPONENT_VALUE_KINDS,
    COMPONENT_VALUE_QUALIFIERS,
    DIMENSION_STATUSES,
    DISTANCE_UNITS,
    DURATION_BASES,
    EVIDENCE_LEVELS,
    RECORDING_STATES,
    TEMPORAL_PRECISIONS,
    UNKNOWN_CONTEXT_DEPENDENCIES,
)


COUNT_DIMENSIONS = {
    "repetition_count_intended", "repetition_count_executed",
    "repetition_count_observed",
}
DISTANCE_DIMENSIONS = {
    "repetition_distance_nominal", "repetition_distance_executed",
    "repetition_distance_measured",
}


def _text(value: object | None) -> str:
    return "" if value is None else str(value).strip()


def _strict_non_negative_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{field} must be a strict integer")
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"{field} must be non-negative")
    return normalized


def _finite_non_negative_number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return normalized


def validate_component(row: Mapping[str, Any]) -> None:
    """Validate a component decision without inferring missing facts."""
    state = str(row["recording_state"])
    if state not in RECORDING_STATES:
        raise ValueError(f"unsupported recording_state: {state}")
    component_order = _strict_non_negative_integer(
        row["component_order"], field="component_order"
    )
    if component_order < 1:
        raise ValueError("component_order must be positive")
    if str(row["temporal_precision"]) not in TEMPORAL_PRECISIONS:
        raise ValueError("unsupported temporal_precision")
    if str(row["duration_basis"]) not in DURATION_BASES:
        raise ValueError("unsupported duration_basis")
    if str(row["claim_kind"]) not in CLAIM_KINDS:
        raise ValueError("unsupported claim_kind")
    if str(row["evidence_level"]) not in EVIDENCE_LEVELS:
        raise ValueError("unsupported evidence_level")

    membership = row.get("membership_decision_id")
    activity = row.get("activity_type_id")
    role = row.get("component_role")
    uncertainty = _text(row.get("uncertainty_reason"))
    if state == "recorded":
        if not _text(membership):
            raise ValueError("recorded component requires membership")
        if activity is not None:
            raise ValueError("recorded component must derive activity from its recorded session")
    elif state == "unrecorded":
        if membership is not None:
            raise ValueError("unrecorded component cannot reference membership")
        if not _text(activity):
            raise ValueError("unrecorded component requires activity_type")
        if str(activity) not in ACTIVITY_TYPES_V1:
            raise ValueError(f"unsupported activity_type: {activity}")
    else:
        if membership is not None:
            raise ValueError("unknown component cannot reference membership")
        if activity is not None:
            raise ValueError("unknown component cannot assert activity_type")
        if role is not None:
            raise ValueError("unknown component cannot assert component_role")
        if not uncertainty:
            raise ValueError("unknown component requires uncertainty_reason")

    duration = row.get("duration_s")
    if duration is not None:
        _finite_non_negative_number(duration, field="duration_s")
    if row["duration_basis"] == "unknown" and duration is not None:
        raise ValueError("unknown duration_basis cannot carry duration_s")
    start, end = row.get("start_time"), row.get("end_time")
    if start and end:
        left = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        right = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        if right < left:
            raise ValueError("end_time cannot precede start_time")


def validate_component_claim(row: Mapping[str, Any]) -> None:
    """Validate typed prescription/execution/observation/measurement claims."""
    dimension = str(row["dimension_name"])
    status = str(row["claim_status"])
    kind = str(row["value_kind"])
    qualifier = row.get("value_qualifier")
    if dimension not in COMPONENT_DIMENSIONS:
        raise ValueError(f"unsupported component dimension: {dimension}")
    if status not in DIMENSION_STATUSES:
        raise ValueError(f"unsupported claim_status: {status}")
    if kind not in COMPONENT_VALUE_KINDS:
        raise ValueError(f"unsupported value_kind: {kind}")
    if qualifier is not None and qualifier not in COMPONENT_VALUE_QUALIFIERS:
        raise ValueError(f"unsupported value_qualifier: {qualifier}")
    if str(row["claim_kind"]) not in CLAIM_KINDS:
        raise ValueError("unsupported claim_kind")
    if str(row["evidence_level"]) not in EVIDENCE_LEVELS:
        raise ValueError("unsupported evidence_level")

    values = {
        "integer": row.get("integer_value"), "numeric": row.get("numeric_value"),
        "text": row.get("text_value"), "lower": row.get("range_lower_value"),
        "upper": row.get("range_upper_value"),
    }
    present = {name for name, value in values.items() if value is not None}
    if status in {"unknown", "abstained", "not_applicable"}:
        if kind != "none" or present or row.get("unit") is not None or qualifier is not None:
            raise ValueError(f"{status} claim cannot carry a typed value")
        if status in {"abstained", "not_applicable"} and not _text(row.get("uncertainty_reason")):
            raise ValueError(f"{status} claim requires a reason")
        return
    if status == "asserted" and kind == "none":
        raise ValueError("asserted claim requires a typed value")
    if status == "uncertain" and not _text(row.get("uncertainty_reason")):
        raise ValueError("uncertain claim requires uncertainty_reason")

    if kind == "integer":
        if present != {"integer"}:
            raise ValueError("integer value_kind requires only integer_value")
        _strict_non_negative_integer(values["integer"], field="integer_value")
        if row.get("unit") is not None:
            raise ValueError("count dimensions cannot carry a unit")
        if qualifier not in {"exact", "minimum", "maximum"}:
            raise ValueError("integer claims require exact, minimum, or maximum qualifier")
    elif kind == "numeric":
        if present != {"numeric"}:
            raise ValueError("numeric value_kind requires only numeric_value")
        _finite_non_negative_number(values["numeric"], field="numeric_value")
        if qualifier not in {"exact", "approximate", "minimum", "maximum"}:
            raise ValueError("numeric claim has incompatible qualifier")
    elif kind == "text":
        if present != {"text"} or not _text(values["text"]) or row.get("unit") is not None:
            raise ValueError("text value_kind requires only non-empty text_value and no unit")
        if qualifier is not None:
            raise ValueError("text claims cannot carry numeric qualifier")
    elif kind == "range":
        if present != {"lower", "upper"}:
            raise ValueError("range value_kind requires lower and upper only")
        lower = _finite_non_negative_number(values["lower"], field="range_lower_value")
        upper = _finite_non_negative_number(values["upper"], field="range_upper_value")
        if lower > upper:
            raise ValueError("range must be non-negative and ordered")
        if qualifier != "range":
            raise ValueError("range value_kind requires range qualifier")
    else:
        raise ValueError("value_kind none is only valid for value-less claim statuses")

    if dimension in COUNT_DIMENSIONS:
        if kind != "integer" or row.get("item_index") is not None:
            raise ValueError("count dimensions require a global integer value")
    elif dimension in DISTANCE_DIMENSIONS:
        if kind not in {"numeric", "range"} or row.get("unit") not in DISTANCE_UNITS:
            raise ValueError("distance dimensions require numeric/range value in m or km")
        if dimension == "repetition_distance_measured" and row.get("item_index") is None:
            raise ValueError("individual measured repetition distance requires item_index")


def typed_claim_meaning(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row["claim_status"], row["value_kind"], row.get("integer_value"),
        row.get("numeric_value"), row.get("text_value"), row.get("range_lower_value"),
        row.get("range_upper_value"), row.get("unit"), row.get("value_qualifier"),
    )


def compose_component_gold(
    claims: Iterable[Mapping[str, Any]], *, product: str
) -> list[dict[str, Any]]:
    if product not in {"gold_core", "gold_extended"}:
        raise ValueError("product must be gold_core or gold_extended")
    accepted = {"verified"} if product == "gold_core" else {"verified", "reported"}
    grouped: dict[tuple[str, str, str, int | None], list[dict[str, Any]]] = defaultdict(list)
    for raw in claims:
        row = dict(raw)
        if row["evidence_level"] in accepted:
            grouped[(row["runner_id"], row["component_id"], row["dimension_name"], row.get("item_index"))].append(row)
    output: list[dict[str, Any]] = []
    for key, rows in sorted(grouped.items(), key=lambda item: tuple("" if v is None else str(v) for v in item[0])):
        rows.sort(key=lambda row: (row["annotation_thread_id"], int(row["revision"]), row["claim_id"]))
        meanings = {typed_claim_meaning(row) for row in rows}
        base = {
            "runner_id": key[0], "component_id": key[1], "dimension_name": key[2],
            "item_index": key[3], "gold_product": product,
            "source_claim_ids": [row["claim_id"] for row in rows],
            "source_thread_ids": sorted({row["annotation_thread_id"] for row in rows}),
        }
        if len(meanings) > 1:
            output.append({**base, "resolution_status": "conflicted", "reason_code": "CONFLICT_UNRESOLVED"})
        else:
            output.append({
                **base, "resolution_status": "resolved",
                "reason_code": {"unknown": "UNKNOWN", "abstained": "ABSTAINED", "not_applicable": "NOT_APPLICABLE"}.get(
                    rows[0]["claim_status"], "AGREEMENT_NO_ADJUDICATION" if len(rows) > 1 else "SINGLE_CLAIM"
                ),
                "meaning": list(next(iter(meanings))),
                "evidence_levels": sorted({row["evidence_level"] for row in rows}),
            })
    return output


def evaluate_unknown_context(
    components: Iterable[Mapping[str, Any]], *, dependency: str,
    contract_version: str, knowledge_cutoff: str,
) -> dict[str, Any]:
    """Calculate query-specific usability; never persist this as Ground Truth."""
    if dependency not in UNKNOWN_CONTEXT_DEPENDENCIES:
        raise ValueError(f"unsupported dependency: {dependency}")
    rows = [dict(row) for row in components]
    unknown = [row for row in rows if row["recording_state"] == "unknown"]
    unrecorded = [row for row in rows if row["recording_state"] == "unrecorded"]
    included = [row["component_id"] for row in rows if row["recording_state"] == "recorded"]
    omitted = [row["component_id"] for row in rows if row["recording_state"] != "recorded"]
    if dependency == "none":
        status, result = "context_not_required", "usable"
    elif unknown:
        status = "unknown_context_present"
        result = "usable_with_context_warning" if dependency == "contextual" else "abstain_unknown_context"
    elif unrecorded:
        status = "partial_known_context"
        result = "abstain_unknown_context" if dependency == "quantitative" else "usable_with_context_warning"
    else:
        status, result = "complete_known_context", "usable"
    if result not in ANALYSIS_USABILITY_RESULTS:  # defensive contract assertion
        raise AssertionError(result)
    return {
        "analysis_context_status": status,
        "analysis_dependency_on_unknown_context": dependency,
        "result": result,
        "included_component_ids": included,
        "omitted_component_ids": omitted,
        "recorded_component_count": len(included),
        "total_component_count": len(rows),
        "coverage_fraction": (len(included) / len(rows)) if rows else None,
        "unknown_context_present": bool(unknown),
        "contract_version": contract_version,
        "knowledge_cutoff": knowledge_cutoff,
    }


def summarize_observed_load(
    components: Iterable[Mapping[str, Any]], observed_load_by_component: Mapping[str, float]
) -> dict[str, Any]:
    rows = [dict(row) for row in components]
    all_ids = {row["component_id"] for row in rows}
    recorded_ids = {row["component_id"] for row in rows if row["recording_state"] == "recorded"}
    unexpected = sorted(set(observed_load_by_component) - recorded_ids)
    if unexpected:
        raise ValueError(
            "load measurements may reference recorded components only: "
            + ",".join(unexpected)
        )
    measured: dict[str, float] = {
        key: _finite_non_negative_number(value, field=f"observed_load[{key}]")
        for key, value in observed_load_by_component.items()
    }
    measured_ids = set(measured)
    missing_ids = sorted(all_ids - measured_ids)
    observed = sum(measured.values())
    incomplete = bool(missing_ids)
    return {
        "observed_load": observed,
        "unobserved_context_present": incomplete,
        "total_load_status": "incomplete" if incomplete else "complete",
        "observed_component_ids": sorted(measured_ids),
        "missing_load_component_ids": missing_ids,
        "measured_component_count": len(measured_ids),
        "total_component_count": len(all_ids),
        "coverage_fraction": (len(measured_ids) / len(all_ids)) if all_ids else None,
    }
