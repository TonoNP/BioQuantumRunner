# scripts/current_form_status.py
from pathlib import Path
import pandas as pd

SESSIONS_CSV = Path("data/processed/sessions.csv")
OPTIMAL_CSV = Path("data/processed/training_blocks_6w.csv")

WINDOW_DAYS = 28

def pace_str(sec):
    sec = int(round(sec))
    m = sec // 60
    s = sec % 60
    return f"{m}:{s:02d}/km"

def main():
    df = pd.read_csv(SESSIONS_CSV)
    opt = pd.read_csv(OPTIMAL_CSV)

    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    df = df.dropna(subset=["date","distance_km","avg_hr","pace_sec_per_km"]).copy()

    df = df[
        (df["distance_km"] >= 8) &
        (df["avg_hr"] > 90) &
        (df["pace_sec_per_km"] < 600) &
        (df["distance_km"] < 50)
    ].copy()

    last_date = df["date"].max()
    start_date = last_date - pd.Timedelta(days=WINDOW_DAYS)

    current = df[(df["date"] > start_date) & (df["date"] <= last_date)].copy()

    peak = opt[opt["block_status"] == "peak_block"].copy()
    peak["km_per_week"] = peak["km_total"] / peak["weeks"]

    km_opt = peak["km_per_week"].mean()
    hr_opt = peak["avg_hr_mean"].mean()
    pace_opt = peak["pace_mean"].mean()

    km_current = current["distance_km"].sum() / 4
    hr_current = current["avg_hr"].mean()
    pace_current = current["pace_sec_per_km"].mean()

    if hr_current > hr_opt + 5:
        status = "fatigue_risk"
    elif hr_current < hr_opt - 2:
        status = "efficient"
    else:
        status = "normal"

    print("\n=== CURRENT FORM STATUS ===\n")

    print("Zona óptima histórica")
    print(f"km/semana óptimos: {km_opt:.1f}")
    print(f"HR óptima: {hr_opt:.1f}")
    print(f"ritmo óptimo: {pace_str(pace_opt)}\n")

    print("Últimas 4 semanas")
    print(f"km/semana actual: {km_current:.1f}")
    print(f"HR media actual: {hr_current:.1f}")
    print(f"ritmo actual: {pace_str(pace_current)}\n")

    print("Estado actual:", status)

if __name__ == "__main__":
    main()