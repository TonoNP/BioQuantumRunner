# scripts/pace_hr_model.py
from pathlib import Path
import pandas as pd
import numpy as np

IN_CSV = Path("data/processed/sessions.csv")

def pace_str(sec):
    sec = int(round(sec))
    m = sec // 60
    s = sec % 60
    return f"{m}:{s:02d}/km"

def main():
    df = pd.read_csv(IN_CSV)

    # Parse fechas (por si luego queremos filtrar por periodos)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # Limpieza básica
    df = df.dropna(subset=["pace_sec_per_km", "avg_hr", "distance_km"])

    # Filtros fisiológicos
    df = df[
        (df["distance_km"] >= 10) &      # sesiones relevantes
        (df["avg_hr"] >= 140) &          # esfuerzo medio/alto
        (df["pace_sec_per_km"] < 600) &  # evitar datos raros
        (df["distance_km"] < 50)
    ].copy()

    # Variables del modelo
    pace = df["pace_sec_per_km"].values
    hr = df["avg_hr"].values

    # Regresión lineal simple: HR = a * pace + b
    a, b = np.polyfit(pace, hr, 1)

    print("Modelo HR ≈ a * pace_sec_per_km + b")
    print(f"a = {a:.4f}")
    print(f"b = {b:.2f}\n")

    # Predicciones para ritmos típicos
    paces = [300, 270, 255, 240, 230]  # 5:00, 4:30, 4:15, 4:00, 3:50
    rows = []
    for p in paces:
        hr_pred = a * p + b
        rows.append({
            "pace": pace_str(p),
            "pace_sec_per_km": p,
            "predicted_hr": round(hr_pred, 1)
        })

    out = pd.DataFrame(rows)
    print("Predicción HR por ritmo:")
    print(out.to_string(index=False))

    OUT = Path("data/processed/pace_hr_model_predictions.csv")
    out.to_csv(OUT, index=False)
    print(f"\nSaved: {OUT}")

if __name__ == "__main__":
    main()