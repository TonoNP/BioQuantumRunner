import pandas as pd


def training_session_to_row(session):

    duration_min = None
    if getattr(session, "duration_s", None) is not None:
        duration_min = session.duration_s / 60

    pace_min_km = None
    if duration_min and session.distance_km:
        pace_min_km = duration_min / session.distance_km

    return {
        "name": getattr(session, "name", None),
        "session_date": getattr(session, "session_date", None),
        "distance_km": getattr(session, "distance_km", None),
        "duration_s": getattr(session, "duration_s", None),
        "duration_min": duration_min,
        "pace_min_km": pace_min_km,
        "avg_hr": getattr(session, "avg_hr", None),
    }


def sessions_to_dataframe(sessions):

    rows = []

    for s in sessions:
        rows.append(training_session_to_row(s))

    df = pd.DataFrame(rows)

    return df