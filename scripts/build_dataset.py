# scripts/build_dataset.py

from pathlib import Path
import sys

# Asegura que Python encuentre el paquete src/
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.polar_json import session_from_polar_json


def main():
    raw_dir = PROJECT_ROOT / "data" / "raw" / "polar"
    if not raw_dir.exists():
        print(f"Raw directory not found: {raw_dir}")
        return

    json_files = sorted(raw_dir.glob("*.json"))
    if not json_files:
        print("No JSON files found.")
        return

    sessions = []
    errors = 0

    for path in json_files:
        try:
            s = session_from_polar_json(path)
            sessions.append(s)
        except Exception as e:
            errors += 1
            print(f"[ERROR] {path.name}: {e}")

    print(f"\nLoaded sessions: {len(sessions)}")
    print(f"Errors: {errors}")

    if sessions:
        print("\nFirst 3 summaries:")
        for s in sessions[:3]:
            print("-", s.summary())

    # ====== ✅ DATASET EXPORT (DENTRO DE main) ======
    import pandas as pd
    from pathlib import Path

    rows = []
    for s in sessions:
        rows.append({
            "name": s.name,
            "distance_km": s.distance_km,
            "duration_s": s.duration_s,
            "pace_sec_per_km": s.pace_s_per_km,
            "avg_hr": s.avg_hr
        })

    df = pd.DataFrame(rows)

    Path("data/processed").mkdir(parents=True, exist_ok=True)
    Path("data/errors").mkdir(parents=True, exist_ok=True)

    df.to_csv("data/processed/sessions.csv", index=False)
    df.to_parquet("data/processed/sessions.parquet", index=False)

    print("\nSaved dataset:")
    print(" - data/processed/sessions.csv")
    print(" - data/processed/sessions.parquet")


if __name__ == "__main__":
    main()