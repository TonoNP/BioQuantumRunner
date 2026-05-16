# scripts/training_blocks_6w.py
from pathlib import Path
import pandas as pd

IN_CSV = Path("data/processed/weekly_form_report.csv")
OUT_CSV = Path("data/processed/training_blocks_6w.csv")

WINDOW_WEEKS = 6

def classify_block(row):
    if row["fatigue_weeks"] >= 2 or row["delta_hr_mean"] > 4:
        return "fatigue_block"
    elif row["efficient_weeks"] >= 2 and row["delta_hr_mean"] < -2:
        return "peak_block"
    else:
        return "normal_block"

def main():
    df = pd.read_csv(IN_CSV)

    # Crear una fecha aproximada del inicio de semana ISO
    df["week_start"] = pd.to_datetime(
        df["year"].astype(str) + "-W" + df["week"].astype(str).str.zfill(2) + "-1",
        format="%G-W%V-%u",
        errors="coerce"
    )

    df = df.sort_values("week_start").reset_index(drop=True)

    results = []

    for i in range(len(df) - WINDOW_WEEKS + 1):
        block = df.iloc[i:i+WINDOW_WEEKS].copy()

        start = block["week_start"].iloc[0]
        end = block["week_start"].iloc[-1] + pd.Timedelta(days=6)

        fatigue_weeks = (block["week_status"] == "fatigue_risk").sum()
        efficient_weeks = (block["week_status"] == "efficient").sum()

        row = {
            "start": start.date(),
            "end": end.date(),
            "weeks": WINDOW_WEEKS,
            "sessions_total": int(block["sessions"].sum()),
            "km_total": round(block["km_total"].sum(), 1),
            "avg_hr_mean": round(block["avg_hr_mean"].mean(), 1),
            "pace_mean": round(block["pace_mean"].mean(), 1),
            "delta_hr_mean": round(block["delta_hr_mean"].mean(), 2),
            "fatigue_weeks": int(fatigue_weeks),
            "efficient_weeks": int(efficient_weeks),
        }

        row["block_status"] = classify_block(row)
        results.append(row)

    res = pd.DataFrame(results)
    res.to_csv(OUT_CSV, index=False)

    print(f"Saved: {OUT_CSV}")
    print("\nConteo por tipo de bloque:")
    print(res["block_status"].value_counts())

    print("\nTop 10 bloques pico:")
    peak = res.sort_values(["efficient_weeks", "delta_hr_mean"], ascending=[False, True])
    print(peak.head(10).to_string(index=False))

    print("\nTop 10 bloques de fatiga:")
    fatigue = res.sort_values(["fatigue_weeks", "delta_hr_mean"], ascending=[False, False])
    print(fatigue.head(10).to_string(index=False))

if __name__ == "__main__":
    main()