"""D3 evaluation metrics and coverage summaries."""

from __future__ import annotations
import numpy as np
import pandas as pd

def summarize_predictions(predictions: pd.DataFrame) -> list[dict]:
    rows=[]
    groups = []
    for model_id, group in predictions.groupby("model_id", dropna=False):
        groups.append((model_id, "ALL", group))
    for (model_id, distance_class), group in predictions.groupby(
        ["model_id", "distance_class"], dropna=False
    ):
        groups.append((model_id, distance_class, group))

    for model_id, distance_class, g in groups:
        predicted=g[g["prediction_status"].eq("predicted")].copy()
        err=pd.to_numeric(predicted["error_pace_sec_per_km"],errors="coerce").dropna()
        terr=pd.to_numeric(predicted["error_total_time_s"],errors="coerce").dropna()
        rows.append({"model_id":model_id,"distance_class":distance_class,"targets":len(g),
            "predictions":len(predicted),"coverage":len(predicted)/len(g) if len(g) else 0.0,
            "insufficient_history":int(g["prediction_status"].eq("insufficient_history").sum()),
            "mae_pace_s_per_km":float(err.abs().mean()) if len(err) else None,
            "median_abs_error_pace_s_per_km":float(err.abs().median()) if len(err) else None,
            "signed_bias_pace_s_per_km":float(err.mean()) if len(err) else None,
            "mae_total_time_s":float(terr.abs().mean()) if len(terr) else None,
            "signed_bias_total_time_s":float(terr.mean()) if len(terr) else None})
    return rows
