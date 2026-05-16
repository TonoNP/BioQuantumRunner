# scripts/best_form_blocks.py
from pathlib import Path
import pandas as pd

IN_CSV = Path("data/processed/sessions.csv")
WINDOW_DAYS = 28
MIN_KM = 10.0

def main():
    df = pd.read_csv(IN_CSV)

    # Parse fechas
    if "date" not in df.columns:
        raise ValueError("Falta columna 'date' en el CSV")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if "start_time" in df.columns:
        df["start_time"] = pd.to_datetime(df["start_time"], errors="coerce")

    # Eficiencia simple
    df = df.dropna(subset=["pace_sec_per_km", "avg_hr", "distance_km", "duration_s", "date"])
    df["eff"] = df["pace_sec_per_km"] / df["avg_hr"]

    # Filtros fisiológicos (como en largas)
    df = df[
        (df["pace_sec_per_km"] < 600) &   # más rápido que 10:00/km
        (df["avg_hr"] > 90) &             # HR razonable
        (df["distance_km"] < 50)          # evitar outliers raros
    ].copy()

    # Solo sesiones >= 10 km
    df = df[df["distance_km"] >= MIN_KM].copy()
    df = df.sort_values("date")

    results = []
    dates = df["date"].sort_values().unique()

    for start in dates:
        end = start + pd.Timedelta(days=WINDOW_DAYS)
        block = df[(df["date"] >= start) & (df["date"] < end)]
        if len(block) < 3:
            continue

        total_km = block["distance_km"].sum()
        eff_med = block["eff"].median()
        eff_std = block["eff"].std()
        n = len(block)

        results.append({
            "start": start.date(),
            "end": (end - pd.Timedelta(days=1)).date(),
            "sessions": n,
            "km_total": round(total_km, 1),
            "eff_median": round(eff_med, 3),
            "eff_std": round(eff_std, 3)
        })

    res = pd.DataFrame(results)

    # Orden: mejor eficiencia (más baja) y estable (std baja)
    res = res.sort_values(["eff_median", "eff_std"]).reset_index(drop=True)

    OUT = Path("data/processed/best_form_blocks_4w.csv")
    res.to_csv(OUT, index=False)

    print(f"Blocks analyzed: {len(res)}")
    print(f"Saved: {OUT}")
    print("\nTop 5 blocks:")
    print(res.head(5).to_string(index=False))

if __name__ == "__main__":
    main()