"""Candidate inventory, race registry validation, and canonical linkage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from .contracts import (
    CANDIDATE_STATUSES, COMPETITION_CONTEXTS, CONTEXT_FLAGS, DISTANCE_CLASSES,
    D3_CONTRACT_VERSION, EVENT_TYPES, EVIDENCE_STATUSES, RACE_REGISTRY_COLUMNS,
    RUNNER_ID,
)

NOTEBOOK_CANDIDATES = [
    ("2019-11-03", "marathon"), ("2019-11-17", "half"),
    ("2020-07-19", "race"), ("2020-10-11", "race"),
    ("2021-07-18", "race"), ("2021-12-12", "marathon"),
    ("2022-07-24", "race"), ("2022-09-04", "half"),
    ("2022-11-06", "marathon"), ("2022-12-04", "half"),
    ("2023-02-26", "half"), ("2023-03-26", "half"),
    ("2023-09-03", "half"), ("2023-11-05", "marathon"),
    ("2023-12-03", "half"), ("2024-04-07", "race"),
    ("2024-11-24", "marathon"), ("2024-12-06", "3k"),
    ("2025-02-23", "half"), ("2025-05-03", "10k"),
    ("2025-07-27", "10k"), ("2025-09-07", "half"),
    ("2025-11-30", "marathon"), ("2026-02-22", "half"),
]

NOMINAL = {"3k": 3.0, "5k": 5.0, "10k": 10.0, "half": 21.0975, "marathon": 42.195}
CLASS = {"3k": "3K", "5k": "5K", "10k": "10K", "half": "Half Marathon", "marathon": "Marathon"}

def load_candidate_ranges(path: Path | str) -> dict:
    """Load JSON-compatible YAML without adding a new dependency."""
    return json.loads(Path(path).read_text(encoding="utf-8"))

def _race_id(date: str, label: str) -> str:
    slug = label.replace(" ", "-")
    return f"{RUNNER_ID}__{date}__{slug}__01"

def build_registry(master: pd.DataFrame, *, recorded_at: str = "2026-08-03T00:00:00") -> pd.DataFrame:
    """Build the complete audited inventory from the notebook's 24 candidates."""
    df = master.copy()
    df["session_date"] = pd.to_datetime(
        df["session_date"], format="mixed", errors="coerce", utc=True
    ).dt.tz_localize(None)
    rows: list[dict] = []
    for date, label in NOTEBOOK_CANDIDATES:
        matches = df[df["session_date"].dt.strftime("%Y-%m-%d").eq(date)].sort_values("source_file")
        specific = label in CLASS
        unique = len(matches) == 1
        linked = matches.iloc[0] if unique else None
        guadalajara = date == "2025-11-30"
        verified = (specific and unique) or guadalajara
        candidate_status = "verified" if verified else "pending_evidence"
        source_file = linked["source_file"] if linked is not None else ""
        source_sha = linked["sha256"] if linked is not None else ""
        observed = float(linked["distance_km"]) if linked is not None else None
        session_date = linked["session_date"].isoformat() if linked is not None else ""
        distance_class = CLASS.get(label, "Other")
        nominal = NOMINAL.get(label)
        context = "official_competition" if guadalajara else "unknown"
        event_type = "race" if verified else "unknown"
        flags = [] if verified else ["insufficient_evidence"]
        note = (
            "Formally reincorporated by D3 contract; independent event evidence pending."
            if guadalajara else
            "Unique canonical session linked to a manually curated notebook race label."
            if verified else
            f"Notebook candidate label={label}; {len(matches)} canonical sessions on date; event evidence unresolved."
        )
        rows.append({
            "race_id": _race_id(date, label), "runner_id": RUNNER_ID,
            "source_file": source_file, "source_sha256": source_sha,
            "event_name": "Maratón Guadalajara 2025" if guadalajara else f"Notebook candidate {date}",
            "event_date": date, "session_date": session_date,
            "observed_distance_km": observed, "nominal_distance_km": nominal,
            "distance_class": distance_class, "event_type": event_type,
            "competition_context": context, "candidate_status": candidate_status,
            "verification_status": "verified_session_reported_event" if verified else "pending_evidence",
            "evidence_status": "reported", "evidence_type": "notebook_manual_registry",
            "evidence_reference": "notebooks/race_predictor_v2.ipynb",
            "context_flags": json.dumps(flags, separators=(",", ":")),
            "descriptive_eligible": True, "default_modeling_eligible": verified,
            "exclusion_reason": "" if verified else "insufficient_evidence",
            "registry_version": D3_CONTRACT_VERSION, "recorded_at": recorded_at,
            "recorded_by": "d3_registry_audit_v1", "notes": note,
        })
    return pd.DataFrame(rows, columns=RACE_REGISTRY_COLUMNS).sort_values("race_id").reset_index(drop=True)

def validate_registry(registry: pd.DataFrame, master: pd.DataFrame) -> None:
    missing = set(RACE_REGISTRY_COLUMNS) - set(registry.columns)
    if missing: raise ValueError(f"race registry missing columns: {sorted(missing)}")
    if len(registry) != len(NOTEBOOK_CANDIDATES): raise ValueError("candidate inventory is incomplete")
    if registry["race_id"].duplicated().any(): raise ValueError("duplicate race_id")
    if not set(registry["candidate_status"]).issubset(CANDIDATE_STATUSES): raise ValueError("invalid candidate_status")
    if not set(registry["distance_class"]).issubset(DISTANCE_CLASSES): raise ValueError("invalid distance_class")
    if not set(registry["event_type"]).issubset(EVENT_TYPES): raise ValueError("invalid event_type")
    if not set(registry["competition_context"]).issubset(COMPETITION_CONTEXTS): raise ValueError("invalid competition_context")
    if not set(registry["evidence_status"]).issubset(EVIDENCE_STATUSES): raise ValueError("invalid evidence_status")
    known = set(master["source_file"])
    linked = registry[registry["source_file"].astype(bool)]
    if not set(linked["source_file"]).issubset(known): raise ValueError("unknown source_file in registry")
    for flags in registry["context_flags"]:
        if not set(json.loads(flags)).issubset(CONTEXT_FLAGS): raise ValueError("invalid context flag")
    pending = registry["candidate_status"].eq("pending_evidence")
    if registry.loc[pending, "default_modeling_eligible"].astype(bool).any():
        raise ValueError("pending evidence cannot be modeling eligible")

def registry_manifest_hash(registry: pd.DataFrame) -> str:
    payload = registry[RACE_REGISTRY_COLUMNS].to_csv(index=False, lineterminator="\n")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
