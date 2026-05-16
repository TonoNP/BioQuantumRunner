import streamlit as st
import pandas as pd

import json
import os
import numpy as np
from sklearn.linear_model import LinearRegression


def build_pipeline(n_files=200):

    folder = "data/raw/polar"
    files = os.listdir(folder)

    sessions = []

    for f in files[:n_files]:
        try:
            with open(os.path.join(folder, f), "r", encoding="utf-8") as file:
                sessions.append(json.load(file))
        except:
            continue

    rows = []

    for s in sessions:
        try:
            rows.append({
                "session_date": s.get("startTime", "")[:10],
                "duration_s": s.get("duration", 0),
                "distance_km": s.get("distance", 0) / 1000,
                "avg_hr": s.get("averageHeartRate", None),
            })
        except:
            continue

    df = pd.DataFrame(rows)

    def parse_duration(x):
        try:
            return float(x.replace("PT", "").replace("S", ""))
        except:
            return None

    df["duration_s"] = df["duration_s"].apply(parse_duration)

    df["duration_min"] = df["duration_s"] / 60

    df["pace_min_km"] = (
        df["duration_min"] / df["distance_km"]
    )

    df["efficiency"] = (
        (60 / df["pace_min_km"]) / df["avg_hr"]
    )

    df = df.replace([np.inf, -np.inf], np.nan)

    df = df.dropna(
        subset=[
            "efficiency",
            "pace_min_km",
            "distance_km",
            "avg_hr"
        ]
    )

    df_perf = df[
        (df["distance_km"] >= 8) &
        (df["pace_min_km"] <= 5.0) &
        (df["avg_hr"] >= 140)
    ]

    model = LinearRegression()

    model.fit(
        df_perf[["efficiency"]],
        df_perf["pace_min_km"]
    )

    eff_recent = df.tail(20)["efficiency"].mean()

    pace = model.predict(
        pd.DataFrame({
            "efficiency": [eff_recent]
        })
    )[0]

    return pace, df, df_perf


def runner_summary(df, pace_perf):

    eff_base = df["efficiency"].mean()

    eff_recent = df.tail(20)["efficiency"].mean()

    ratio = eff_recent / eff_base

    if ratio >= 1.02:
        state = "🔥 Pico de forma"

    elif ratio >= 0.98:
        state = "🟢 Buen estado"

    elif ratio >= 0.94:
        state = "🟡 Estado medio"

    else:
        state = "🔴 Fatiga"

    summary = {
        "eff_base": eff_base,
        "eff_recent": eff_recent,
        "ratio": ratio,
        "state": state,
        "predicted_pace": pace_perf
    }

    return summary

st.title("🏃 BioQuantumRunner")

# correr pipeline
pace, df_all, df_perf = build_pipeline()

summary = runner_summary(df_all, pace)

# ---- UI ----
st.header("Estado del corredor")

st.metric("Estado", summary["state"])
st.metric("Ratio", round(summary["ratio"], 3))

st.header("Predicción")

pace = summary["predicted_pace"]

m = int(pace)
s = int((pace - m) * 60)

st.write(f"🎯 Ritmo estimado: {m}:{s:02d} min/km")

st.header("Datos")

st.write(f"Sesiones totales: {len(df_all)}")
st.write(f"Sesiones de rendimiento: {len(df_perf)}")