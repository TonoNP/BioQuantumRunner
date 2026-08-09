"""Leakage-safe pre-race feature construction."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from src.analysis.d2_dataset import EFFICIENCY_PACE_HR, EFFICIENCY_SPEED_HR

FEATURE_CONTRACT_VERSION = "d3-pre-race-features-1.0"
FORBIDDEN_PRE_RACE_COLUMNS = {
    "actual_pace_sec_per_km", "actual_total_time_s", "error_pace_sec_per_km",
    "error_total_time_s",
}

def sessions_before_cutoff(sessions: pd.DataFrame, training_cutoff: pd.Timestamp) -> pd.DataFrame:
    cutoff = pd.Timestamp(training_cutoff)
    out = sessions.copy()
    out["session_date"] = pd.to_datetime(
        out["session_date"], format="mixed", errors="coerce", utc=True
    ).dt.tz_localize(None)
    out = out[out["session_date"] < cutoff].copy()
    if not out.empty and not (out["session_date"] < cutoff).all():
        raise AssertionError("temporal leakage detected")
    return out.sort_values(["session_date", "source_file"], kind="stable").reset_index(drop=True)

def races_before_cutoff(registry: pd.DataFrame, training_cutoff: pd.Timestamp) -> pd.DataFrame:
    cutoff = pd.Timestamp(training_cutoff)
    out = registry.copy()
    out["session_date"] = pd.to_datetime(
        out["session_date"], format="mixed", errors="coerce", utc=True
    ).dt.tz_localize(None)
    eligible = out["default_modeling_eligible"].fillna(False).astype(bool)
    out = out[eligible & out["session_date"].notna() & (out["session_date"] < cutoff)].copy()
    return out.sort_values(["session_date", "race_id"], kind="stable").reset_index(drop=True)

def session_manifest_hash(sessions: pd.DataFrame) -> str:
    columns = [c for c in ("source_file", "sha256", "session_date") if c in sessions.columns]
    payload = sessions[columns].copy()
    if "session_date" in payload: payload["session_date"] = payload["session_date"].astype(str)
    text = payload.sort_values(columns, kind="stable").to_csv(index=False, lineterminator="\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def build_target_context(target: pd.Series, sessions: pd.DataFrame) -> dict:
    """Build only features knowable before the target event."""
    cutoff = pd.Timestamp(target["session_date"])
    prior = sessions_before_cutoff(sessions, cutoff)
    recent = prior.tail(20)
    result = {
        "target_race_id": target["race_id"], "training_cutoff": cutoff,
        "nominal_distance_km": float(target["nominal_distance_km"]),
        "distance_class": target["distance_class"], "n_prior_sessions": len(prior),
        "n_recent_sessions": len(recent), "training_session_manifest_hash": session_manifest_hash(prior),
        "recent_avg_hr": float(recent["avg_hr"].dropna().median()) if recent["avg_hr"].notna().any() else np.nan,
        "recent_pace_sec_per_km": float(recent["pace_sec_per_km"].dropna().median()) if recent["pace_sec_per_km"].notna().any() else np.nan,
        "recent_efficiency_pace_hr_v1": float(recent[EFFICIENCY_PACE_HR].dropna().mean()) if recent[EFFICIENCY_PACE_HR].notna().any() else np.nan,
        "recent_efficiency_speed_hr_v2": float(recent[EFFICIENCY_SPEED_HR].dropna().mean()) if recent[EFFICIENCY_SPEED_HR].notna().any() else np.nan,
    }
    if FORBIDDEN_PRE_RACE_COLUMNS.intersection(result):
        raise AssertionError("actual outcome leaked into feature contract")
    return result
