# scripts/long_runs_report.py
from pathlib import Path
import pandas as pd

IN_CSV = Path("data/processed/sessions.csv")
OUT_DIR = Path("data/processed")
MIN_KM = 16.0

def pace_str_from_seconds(sec_per_km: float) -> str:
    if pd.isna(sec_per_km):
        return ""
    sec = int(round(float(sec_per_km)))
    m = sec // 60
    s = sec % 60
    return f"{m}:{s:02d} /km"

def main():
    if not IN_CSV.exists():
        raise FileNotFoundError(f"No existe: {IN_CSV.resolve()}")

    df = pd.read_csv(IN_CSV)

    # Asegura columnas esperadas
    required = {"distance_km", "duration_s", "pace_sec_per_km", "avg_hr"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Faltan columnas en CSV: {missing}")

    # Filtra tiradas largas
    long_df = df[df["distance_km"] >= MIN_KM].copy()

    # Quita casos donde no hay HR o pace (no se puede calcular eficiencia)
    long_df = long_df.dropna(subset=["avg_hr", "pace_sec_per_km"])

    # Eficiencia simple
    long_df["eff"] = long_df["pace_sec_per_km"] / long_df["avg_hr"]

    # --- filtro anti-basura ---
    long_df = long_df[
        (long_df["pace_sec_per_km"] < 600) &   # más rápido que 10:00 /km
        (long_df["avg_hr"] > 90) &             # HR razonable
        (long_df["distance_km"] < 50)          # evitar cosas absurdas
    ].copy()
   
    # Opcional: formato de ritmo
    long_df["pace"] = long_df["pace_sec_per_km"].apply(pace_str_from_seconds)

    # Orden por fecha si existe (si no, lo deja como está)
    if "date" in long_df.columns:
        long_df = long_df.sort_values(["date", "start_time"], na_position="last")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    out_all = OUT_DIR / "long_runs_16km.csv"
    out_best = OUT_DIR / "long_runs_16km_best10.csv"
    out_worst = OUT_DIR / "long_runs_16km_worst10.csv"

    cols_order = [c for c in ["date", "start_time", "name", "distance_km", "duration_s", "pace", "pace_sec_per_km", "avg_hr", "eff"] if c in long_df.columns]
    long_df[cols_order].to_csv(out_all, index=False)

    best10 = long_df.sort_values("eff").head(10)
    worst10 = long_df.sort_values("eff", ascending=False).head(10)

    best10[cols_order].to_csv(out_best, index=False)
    worst10[cols_order].to_csv(out_worst, index=False)

    print(f"Long runs (>= {MIN_KM} km): {len(long_df)}")
    print(f"Saved:\n - {out_all}\n - {out_best}\n - {out_worst}")
    print("\nBest 3 (más eficientes):")
    print(best10[cols_order].head(3).to_string(index=False))
    print("\nWorst 3 (menos eficientes):")
    print(worst10[cols_order].head(3).to_string(index=False))

if __name__ == "__main__":
    main()