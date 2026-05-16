# scripts/race_predictor.py

from pathlib import Path
import pandas as pd
import numpy as np

SESSIONS = Path("data/processed/sessions.csv")
BLOCKS = Path("data/processed/training_blocks_6w.csv")

def pace_str(sec):
    sec=int(round(sec))
    m=sec//60
    s=sec%60
    return f"{m}:{s:02d}/km"

def time_str(seconds):
    seconds=int(round(seconds))
    h=seconds//3600
    m=(seconds%3600)//60
    s=seconds%60
    if h>0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def main():

    df=pd.read_csv(SESSIONS)
    blocks=pd.read_csv(BLOCKS)

    df["date"]=pd.to_datetime(df["date"],errors="coerce")

    df=df.dropna(subset=["distance_km","avg_hr","pace_sec_per_km"])

    df=df[
        (df["distance_km"]>=8)&
        (df["distance_km"]<50)&
        (df["avg_hr"]>90)&
        (df["pace_sec_per_km"]<600)
    ].copy()

    # modelo HR vs pace
    pace=df["pace_sec_per_km"].values
    hr=df["avg_hr"].values

    a,b=np.polyfit(pace,hr,1)

    # bloques pico
    peak=blocks[blocks["block_status"]=="peak_block"].copy()

    peak_pace=peak["pace_mean"].mean()

    # estado actual (4 semanas)
    last_date=df["date"].max()
    start=last_date-pd.Timedelta(days=28)

    current=df[(df["date"]>start)&(df["date"]<=last_date)]

    current_hr=current["avg_hr"].mean()

    # HR esperada para peak pace
    hr_pred=a*peak_pace+b

    # ajuste forma actual
    delta=current_hr-hr_pred

    # factor simple
    adjustment=delta*0.8

    predicted_pace=peak_pace+adjustment

    print("\n=== PERFORMANCE PREDICTOR ===\n")

    print("Peak pace histórico:",pace_str(peak_pace))
    print("HR actual promedio:",round(current_hr,1))

    print("\nRitmo estimado de carrera:",pace_str(predicted_pace))

    # distancias
    races={
        "10K":10,
        "Half Marathon":21.097,
        "Marathon":42.195
    }

    print("\nPredicciones:\n")

    for name,dist in races.items():

        time=predicted_pace*dist

        print(name)
        print("ritmo:",pace_str(predicted_pace))
        print("tiempo:",time_str(time))
        print()

if __name__=="__main__":
    main()