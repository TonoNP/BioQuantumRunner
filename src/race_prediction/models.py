"""Approved D3 candidate models; none is designated as the winner."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from src.analysis.d2_dataset import EFFICIENCY_PACE_HR, EFFICIENCY_SPEED_HR
from .contracts import ModelDeclaration

MODEL_VERSION = "1.0"

@dataclass(frozen=True)
class PredictionResult:
    status: str
    pace_sec_per_km: float | None
    training_race_ids: tuple[str, ...]
    detail: str = ""

class BaseModel:
    declaration: ModelDeclaration
    def predict(self, target: pd.Series, prior_sessions: pd.DataFrame, prior_races: pd.DataFrame) -> PredictionResult:
        raise NotImplementedError
    def insufficient(self, races=(), detail=""):
        return PredictionResult("insufficient_history", None, tuple(races), detail)

def _actual_races(prior_races: pd.DataFrame) -> pd.DataFrame:
    out=prior_races.copy()
    out["actual_total_time_s"]=pd.to_numeric(out["actual_total_time_s"],errors="coerce")
    out["nominal_distance_km"]=pd.to_numeric(out["nominal_distance_km"],errors="coerce")
    out=out.dropna(subset=["actual_total_time_s","nominal_distance_km"])
    out=out[(out["actual_total_time_s"]>0)&(out["nominal_distance_km"]>0)]
    out["actual_pace_sec_per_km"]=out["actual_total_time_s"]/out["nominal_distance_km"]
    return out

class LastRaceBaseline(BaseModel):
    declaration=ModelDeclaration("baseline_last_race_v1",MODEL_VERSION,"prior verified races","all prior races",{"minimum_same_class_races":1},"one prior race of same class","registry exclusions")
    def predict(self,target,prior_sessions,prior_races):
        r=_actual_races(prior_races); r=r[r["distance_class"].eq(target["distance_class"])]
        if len(r)<1:return self.insufficient(r.get("race_id",()),"requires one prior same-class race")
        row=r.sort_values("session_date").iloc[-1]
        return PredictionResult("predicted",float(row["actual_pace_sec_per_km"]),tuple(r["race_id"]))

class ClassMedianBaseline(BaseModel):
    declaration=ModelDeclaration("baseline_class_median_v1",MODEL_VERSION,"prior verified races","all prior races",{"minimum_same_class_races":2},"two prior races of same class","registry exclusions")
    def predict(self,target,prior_sessions,prior_races):
        r=_actual_races(prior_races); r=r[r["distance_class"].eq(target["distance_class"])]
        if len(r)<2:return self.insufficient(r.get("race_id",()),"requires two prior same-class races")
        return PredictionResult("predicted",float(r["actual_pace_sec_per_km"].median()),tuple(r["race_id"]))

class RecentPaceBaseline(BaseModel):
    declaration=ModelDeclaration("baseline_recent_pace_v1",MODEL_VERSION,"D2 pace","last 20 prior eligible sessions",{"minimum_sessions":5,"window_sessions":20},"five valid prior sessions","none")
    def predict(self,target,prior_sessions,prior_races):
        s=prior_sessions.dropna(subset=["pace_sec_per_km"]).tail(20)
        if len(s)<5:return self.insufficient(detail="requires five prior valid sessions")
        return PredictionResult("predicted",float(s["pace_sec_per_km"].median()),tuple(prior_races.get("race_id",())))

class RiegelBaseline(BaseModel):
    declaration=ModelDeclaration("baseline_distance_scaling_v1",MODEL_VERSION,"prior verified race time","latest prior verified race",{"exponent":1.06,"constant_source":"Riegel baseline"},"one prior verified race","registry exclusions")
    def predict(self,target,prior_sessions,prior_races):
        r=_actual_races(prior_races)
        if len(r)<1:return self.insufficient(detail="requires one prior verified race")
        row=r.sort_values("session_date").iloc[-1]; d2=float(target["nominal_distance_km"]); d1=float(row["nominal_distance_km"])
        time=float(row["actual_total_time_s"])*(d2/d1)**1.06
        return PredictionResult("predicted",time/d2,(row["race_id"],))

class PersonalizedScaling(BaseModel):
    declaration=ModelDeclaration("baseline_distance_scaling_personalized_v1",MODEL_VERSION,"prior verified race times","all prior races",{"minimum_races":3,"minimum_distinct_distances":2},"three races and two distances","registry exclusions")
    def predict(self,target,prior_sessions,prior_races):
        r=_actual_races(prior_races)
        if len(r)<3 or r["nominal_distance_km"].nunique()<2:return self.insufficient(r.get("race_id",()),"requires three races over two distances")
        x=np.log(r[["nominal_distance_km"]].to_numpy()); y=np.log(r["actual_total_time_s"].to_numpy())
        m=LinearRegression().fit(x,y); time=float(np.exp(m.predict(np.array([[np.log(float(target["nominal_distance_km"]))]]))[0]))
        return PredictionResult("predicted",time/float(target["nominal_distance_km"]),tuple(r["race_id"]))

class SessionLinearModel(BaseModel):
    feature: str
    model_id: str
    min_sessions=30
    def __init__(self,model_id,feature):
        self.feature=feature; self.declaration=ModelDeclaration(model_id,MODEL_VERSION,f"D2 {feature}","all prior eligible sessions",{"minimum_sessions":30},f"30 sessions with {feature}","none")
    def predict(self,target,prior_sessions,prior_races):
        s=prior_sessions.copy()
        s[self.feature]=pd.to_numeric(s[self.feature],errors="coerce").replace([np.inf,-np.inf],np.nan)
        s["pace_sec_per_km"]=pd.to_numeric(s["pace_sec_per_km"],errors="coerce").replace([np.inf,-np.inf],np.nan)
        s=s.dropna(subset=[self.feature,"pace_sec_per_km"])
        if len(s)<self.min_sessions:return self.insufficient(detail=f"requires {self.min_sessions} prior sessions")
        recent=s.tail(20); x_value=float(recent[self.feature].median())
        m=LinearRegression().fit(s[[self.feature]],s["pace_sec_per_km"])
        return PredictionResult("predicted",float(m.predict(pd.DataFrame({self.feature:[x_value]}))[0]),tuple(prior_races.get("race_id",())))

class DistanceProfileRegression(BaseModel):
    declaration=ModelDeclaration("distance_profile_regression_v1",MODEL_VERSION,"log distance and D2 pace","all prior eligible sessions",{"minimum_sessions":30},"30 valid prior sessions","none")
    def predict(self,target,prior_sessions,prior_races):
        s=prior_sessions.dropna(subset=["distance_km","pace_sec_per_km"]); s=s[(s["distance_km"]>0)&(s["pace_sec_per_km"]>0)]
        if len(s)<30:return self.insufficient(detail="requires 30 prior sessions")
        x=pd.DataFrame({"log_distance":np.log(s["distance_km"].to_numpy())}); m=LinearRegression().fit(x,s["pace_sec_per_km"])
        pace=float(m.predict(pd.DataFrame({"log_distance":[np.log(float(target["nominal_distance_km"]))]}))[0])
        return PredictionResult("predicted",pace,tuple(prior_races.get("race_id",())))

class RecentPeakBlend(BaseModel):
    declaration=ModelDeclaration("recent_vs_peak_blend_v1",MODEL_VERSION,"D2 efficiency_speed_hr_v2","all prior plus last 20",{"base_weight":0.7,"recent_weight":0.3,"recent_sessions":20,"minimum_sessions":30},"30 valid prior sessions","none")
    def predict(self,target,prior_sessions,prior_races):
        f=EFFICIENCY_SPEED_HR; s=prior_sessions.dropna(subset=[f,"pace_sec_per_km"])
        if len(s)<30:return self.insufficient(detail="requires 30 prior sessions")
        base=float(s[f].mean()); recent=float(s.tail(20)[f].mean()); blended=.7*base+.3*recent
        m=LinearRegression().fit(s[[f]],s["pace_sec_per_km"])
        return PredictionResult("predicted",float(m.predict(pd.DataFrame({f:[blended]}))[0]),tuple(prior_races.get("race_id",())))

class RaceSpecificHistory(BaseModel):
    declaration=ModelDeclaration("race_specific_history_v1",MODEL_VERSION,"log nominal distance and race time","all prior verified races",{"minimum_races":4,"minimum_distinct_distances":2},"four races over two distances","registry exclusions")
    def predict(self,target,prior_sessions,prior_races):
        r=_actual_races(prior_races)
        if len(r)<4 or r["nominal_distance_km"].nunique()<2:return self.insufficient(r.get("race_id",()),"requires four races over two distances")
        x=pd.DataFrame({"log_distance":np.log(r["nominal_distance_km"].to_numpy())})
        m=LinearRegression().fit(x,np.log(r["actual_total_time_s"]))
        time=float(np.exp(m.predict(pd.DataFrame({"log_distance":[np.log(float(target["nominal_distance_km"]))]}))[0]))
        return PredictionResult("predicted",time/float(target["nominal_distance_km"]),tuple(r["race_id"]))

def approved_models() -> list[BaseModel]:
    return [LastRaceBaseline(),ClassMedianBaseline(),RecentPaceBaseline(),RiegelBaseline(),
        SessionLinearModel("pace_hr_linear_v1","avg_hr"),
        SessionLinearModel("efficiency_pace_hr_linear_v1",EFFICIENCY_PACE_HR),
        SessionLinearModel("efficiency_speed_hr_linear_v2",EFFICIENCY_SPEED_HR),
        DistanceProfileRegression(),RecentPeakBlend(),RaceSpecificHistory()]

def supplemental_models() -> list[BaseModel]:
    return [PersonalizedScaling()]
