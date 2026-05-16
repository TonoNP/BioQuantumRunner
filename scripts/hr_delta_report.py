# scripts/hr_delta_report.py
from pathlib import Path
import pandas as pd
import numpy as np

IN_CSV = Path("data/processed/sessions.csv")
OUT_CSV = Path("data/processed/hr_delta_report.csv")

def classify_delta(delta):
    if delta > 10:
        return "strain"
    elif delta < -10:
        return "high_efficiency"
    else:
        return "normal"

def main():
    df = pd.read_csv(IN_CSV)

    # Parse fechas
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if "start_time" in df.columns:
        df["start_time"] = pd.to_datetime(df["start_time"], errors="coerce")

    # Limpieza básica
    df = df.dropna(subset=["pace_sec_per_km", "avg_hr", "distance_km"]).copy()

    # Mismos filtros del modelo
    model_df = df[
        (df["distance_km"] >= 10) &
        (df["avg_hr"] >= 140) &
        (df["pace_sec_per_km"] < 600) &
        (df["distance_km"] < 50)
    ].copy()

    # Modelo lineal: HR = a*pace + b
    pace = model_df["pace_sec_per_km"].values
    hr = model_df["avg_hr"].values
    a, b = np.polyfit(pace, hr, 1)

    # Predicción y delta para todas las sesiones del conjunto filtrado
    model_df["hr_pred"] = a * model_df["pace_sec_per_km"] + b
    model_df["delta_hr"] = model_df["avg_hr"] - model_df["hr_pred"]
    model_df["status"] = model_df["delta_hr"].apply(classify_delta)
    # Orden útil
    cols = [c for c in [
    "date", "start_time", "name", "distance_km",
    "pace_sec_per_km", "avg_hr", "hr_pred", "delta_hr", "status"
    ] if c in model_df.columns]

    model_df = model_df.sort_values(["date", "start_time"], na_position="last")
    model_df[cols].to_csv(OUT_CSV, index=False)

    print(f"Saved: {OUT_CSV}")
    print("\nDelta HR stats:")
    print(model_df["delta_hr"].describe())
    print("\nConteo por estado:")
    print(model_df["status"].value_counts())
    print("\nTop 5 sesiones con HR más alta de lo esperado:")
    print(model_df.sort_values("delta_hr", ascending=False)[cols].head(5).to_string(index=False))

    print("\nTop 5 sesiones con HR más baja de lo esperado:")
    print(model_df.sort_values("delta_hr", ascending=True)[cols].head(5).to_string(index=False))

if __name__ == "__main__":
    main()