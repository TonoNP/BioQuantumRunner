# scripts/optimal_training_zone.py
from pathlib import Path
import pandas as pd

IN_CSV = Path("data/processed/training_blocks_6w.csv")

def pace_str(sec):
    sec = int(round(sec))
    m = sec // 60
    s = sec % 60
    return f"{m}:{s:02d}/km"

def main():
    df = pd.read_csv(IN_CSV)

    peak = df[df["block_status"] == "peak_block"].copy()
    if peak.empty:
        print("No peak blocks found.")
        return

    peak["km_per_week"] = peak["km_total"] / peak["weeks"]

    print("Peak blocks found:", len(peak))
    print("\nResumen de zona óptima:\n")

    km_week_mean = peak["km_per_week"].mean()
    km_week_q25 = peak["km_per_week"].quantile(0.25)
    km_week_q75 = peak["km_per_week"].quantile(0.75)

    hr_mean = peak["avg_hr_mean"].mean()
    hr_q25 = peak["avg_hr_mean"].quantile(0.25)
    hr_q75 = peak["avg_hr_mean"].quantile(0.75)

    pace_mean = peak["pace_mean"].mean()
    pace_q25 = peak["pace_mean"].quantile(0.25)
    pace_q75 = peak["pace_mean"].quantile(0.75)

    print(f"Km/semana óptimos (media): {km_week_mean:.1f}")
    print(f"Rango intercuartil km/semana: {km_week_q25:.1f}  a  {km_week_q75:.1f}")

    print(f"\nHR promedio óptima (media): {hr_mean:.1f}")
    print(f"Rango intercuartil HR: {hr_q25:.1f}  a  {hr_q75:.1f}")

    print(f"\nRitmo promedio óptimo (media): {pace_str(pace_mean)}")
    print(f"Rango intercuartil ritmo: {pace_str(pace_q25)}  a  {pace_str(pace_q75)}")

    print("\nTop peak blocks usados:")
    cols = [
        "start", "end", "weeks", "sessions_total", "km_total",
        "km_per_week", "avg_hr_mean", "pace_mean", "delta_hr_mean"
    ]
    print(peak[cols].sort_values("delta_hr_mean").to_string(index=False))

if __name__ == "__main__":
    main()