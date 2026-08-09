"""Leakage-safe walk-forward pre-race evaluation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pandas as pd

from .contracts import PREDICTION_COLUMNS, RUNNER_ID
from .features import FEATURE_CONTRACT_VERSION, races_before_cutoff, sessions_before_cutoff, session_manifest_hash
from .models import BaseModel

PROTOCOL_ID = "walk_forward_pre_race_v1"

def attach_observed_outcomes(registry: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    """Attach results for evaluation; these columns are never passed as target features."""
    source = sessions.set_index("source_file", drop=False)
    out=registry.copy(); totals=[]; paces=[]
    for _,row in out.iterrows():
        if row["source_file"] and row["source_file"] in source.index and pd.notna(row["nominal_distance_km"]):
            total=float(source.loc[row["source_file"],"duration_s"]); nominal=float(row["nominal_distance_km"])
            totals.append(total); paces.append(total/nominal)
        else: totals.append(None); paces.append(None)
    out["actual_total_time_s"]=totals; out["actual_pace_sec_per_km"]=paces
    return out

def _prediction_id(target_race_id: str, model_id: str, cutoff: pd.Timestamp) -> str:
    key=f"{target_race_id}|{model_id}|{cutoff.isoformat()}"
    return hashlib.sha256(key.encode()).hexdigest()[:24]

def walk_forward(
    sessions: pd.DataFrame, registry: pd.DataFrame, models: list[BaseModel], *, code_commit: str,
    generated_at: str = "2026-08-03T00:00:00+00:00",
) -> pd.DataFrame:
    races=attach_observed_outcomes(registry,sessions)
    targets=races[
        races["candidate_status"].eq("verified")
        & races["default_modeling_eligible"].fillna(False).astype(bool)
        & races["session_date"].astype(bool)
        & races["actual_total_time_s"].notna()
    ].copy()
    targets["session_date"]=pd.to_datetime(
        targets["session_date"],format="mixed",errors="raise",utc=True
    ).dt.tz_localize(None)
    targets=targets.sort_values(["session_date","race_id"],kind="stable")
    output=[]
    for _,target in targets.iterrows():
        cutoff=pd.Timestamp(target["session_date"])
        prior_sessions=sessions_before_cutoff(sessions,cutoff)
        prior_races=races_before_cutoff(races,cutoff)
        manifest=session_manifest_hash(prior_sessions)
        model_target=target.drop(
            labels=["actual_pace_sec_per_km","actual_total_time_s"], errors="ignore"
        )
        for model in models:
            result=model.predict(model_target,prior_sessions,prior_races)
            pred_pace=result.pace_sec_per_km
            pred_total=pred_pace*float(target["nominal_distance_km"]) if pred_pace is not None else None
            output.append({
                "prediction_id":_prediction_id(target["race_id"],model.declaration.model_id,cutoff),
                "runner_id":RUNNER_ID,"target_race_id":target["race_id"],
                "model_id":model.declaration.model_id,"model_version":model.declaration.model_version,
                "evaluation_protocol_id":PROTOCOL_ID,"prediction_generated_at":generated_at,
                "training_cutoff":cutoff.isoformat(),"training_race_ids":json.dumps(result.training_race_ids,separators=(",",":")),
                "training_session_manifest_hash":manifest,"feature_contract_version":FEATURE_CONTRACT_VERSION,
                "predicted_pace_sec_per_km":pred_pace,"predicted_total_time_s":pred_total,
                "prediction_status":result.status,"actual_pace_sec_per_km":None,
                "actual_total_time_s":None,"error_pace_sec_per_km":None,
                "error_total_time_s":None,
                "coverage_status":"covered" if result.status=="predicted" else "not_covered",
                "code_commit":code_commit,"distance_class":target["distance_class"],
                "model_detail":result.detail,
            })
    frozen_pre_race=pd.DataFrame(output)
    return attach_post_race_evaluation(frozen_pre_race,races)

def attach_post_race_evaluation(predictions: pd.DataFrame, races: pd.DataFrame) -> pd.DataFrame:
    """Add actual outcomes only after the pre-race prediction records exist."""
    result=predictions.copy()
    actual=races.set_index("race_id")[["actual_pace_sec_per_km","actual_total_time_s"]]
    for idx,row in result.iterrows():
        outcome=actual.loc[row["target_race_id"]]
        actual_pace=float(outcome["actual_pace_sec_per_km"])
        actual_total=float(outcome["actual_total_time_s"])
        result.at[idx,"actual_pace_sec_per_km"]=actual_pace
        result.at[idx,"actual_total_time_s"]=actual_total
        if row["prediction_status"]=="predicted":
            result.at[idx,"error_pace_sec_per_km"]=float(row["predicted_pace_sec_per_km"])-actual_pace
            result.at[idx,"error_total_time_s"]=float(row["predicted_total_time_s"])-actual_total
    return result

def circularity_ablation(predictions: pd.DataFrame) -> dict:
    """Compare the speed/HR candidate with its approved HR-only matched ablation."""
    speed=predictions[predictions["model_id"].eq("efficiency_speed_hr_linear_v2")]
    ablation=predictions[predictions["model_id"].eq("pace_hr_linear_v1")]
    merged=speed.merge(ablation,on="target_race_id",suffixes=("_speed","_ablation"))
    both=merged[
        merged["prediction_status_speed"].eq("predicted")
        & merged["prediction_status_ablation"].eq("predicted")
    ].copy()
    def mae(col):
        return float(pd.to_numeric(both[col],errors="coerce").abs().mean()) if len(both) else None
    return {
        "audit_id":"efficiency_speed_hr_v2_circularity_ablation_v1",
        "candidate_model":"efficiency_speed_hr_linear_v2",
        "ablation_model":"pace_hr_linear_v1",
        "ablation_removes":"efficiency_speed_hr_v2",
        "shared_targets":len(both),
        "candidate_mae_pace_s_per_km":mae("error_pace_sec_per_km_speed"),
        "ablation_mae_pace_s_per_km":mae("error_pace_sec_per_km_ablation"),
        "interpretation_rule":"In-sample correlation is not predictive evidence; compare only shared out-of-sample targets.",
    }
