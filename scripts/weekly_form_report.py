# scripts/weekly_form_report.py
from pathlib import Path
import pandas as pd
import numpy as np

IN_CSV = Path("data/processed/sessions.csv")
OUT_CSV = Path("data/processed/weekly_form_report.csv")

def classify_delta(delta):
    if delta > 10:
        return "strain"
    elif delta < -10:
        return "high_efficiency"
    else:
        return "normal"

def classify_week(row):
    if row["strain_count"] >= 2 or row["delta_hr_mean"] > 5:
        return "fatigue_risk"
    elif row["high_eff_count"] >= 1 and row["delta_hr_mean"] < -2:
        return "efficient"
    else:
        return "normal"

def main():
    df = pd.read_csv(IN_CSV)

    # Fechas
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if "start_time" in df.columns:
        df["start_time"] = pd.to_datetime(df["start_time"], errors="coerce")

    # Limpieza
    df = df.dropna(subset=["date", "pace_sec_per_km", "avg_hr", "distance_km"]).copy()

    # Filtros fisiológicos + sesiones >= 8 km
    df = df[
        (df["distance_km"] >= 8) &
        (df["avg_hr"] > 90) &
        (df["pace_sec_per_km"] < 600) &
        (df["distance_km"] < 50)
    ].copy()

    # Modelo lineal simple HR = a*pace + b
    pace = df["pace_sec_per_km"].values
    hr = df["avg_hr"].values
    a, b = np.polyfit(pace, hr, 1)

    # Predicción y delta
    df["hr_pred"] = a * df["pace_sec_per_km"] + b
    df["delta_hr"] = df["avg_hr"] - df["hr_pred"]
    df["status"] = df["delta_hr"].apply(classify_delta)

    # Semana ISO
    iso = df["date"].dt.isocalendar()
    df["year"] = iso.year
    df["week"] = iso.week

    weekly = (
        df.groupby(["year", "week"], as_index=False)
        .agg(
            sessions=("distance_km", "count"),
            km_total=("distance_km", "sum"),
            avg_hr_mean=("avg_hr", "mean"),
            pace_mean=("pace_sec_per_km", "mean"),
            delta_hr_mean=("delta_hr", "mean"),
            strain_count=("status", lambda s: (s == "strain").sum()),
            high_eff_count=("status", lambda s: (s == "high_efficiency").sum()),
        )
    )

    weekly["km_total"] = weekly["km_total"].round(1)
    weekly["avg_hr_mean"] = weekly["avg_hr_mean"].round(1)
    weekly["pace_mean"] = weekly["pace_mean"].round(1)
    weekly["delta_hr_mean"] = weekly["delta_hr_mean"].round(2)

    weekly["week_status"] = weekly.apply(classify_week, axis=1)

    weekly.to_csv(OUT_CSV, index=False)

    print(f"Saved: {OUT_CSV}")
    print("\nConteo por estado semanal:")
    print(weekly["week_status"].value_counts())

    print("\nTop 10 semanas con más riesgo de fatiga:")
    fatigue = weekly.sort_values(["strain_count", "delta_hr_mean"], ascending=False)
    print(fatigue.head(10).to_string(index=False))

    print("\nTop 10 semanas más eficientes:")
    efficient = weekly.sort_values(["high_eff_count", "delta_hr_mean"], ascending=[False, True])
    print(efficient.head(10).to_string(index=False))

if __name__ == "__main__":
    main()