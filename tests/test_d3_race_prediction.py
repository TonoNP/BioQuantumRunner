import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from src.race_prediction.evaluation import attach_observed_outcomes, walk_forward
from src.race_prediction.features import FORBIDDEN_PRE_RACE_COLUMNS, build_target_context, sessions_before_cutoff
from src.race_prediction.models import ClassMedianBaseline, approved_models, supplemental_models
from src.race_prediction.registry import NOTEBOOK_CANDIDATES, build_registry, load_candidate_ranges, validate_registry


def _master_for_candidates():
    rows=[]
    for i,(date,label) in enumerate(NOTEBOOK_CANDIDATES):
        count=3 if date=="2024-12-06" else 1
        for j in range(count):
            rows.append({"source_file":f"{date}-{j}.json","sha256":f"{i:064x}"[-64:],"session_date":f"{date}T06:{j:02d}:00","distance_km":3.0 if label=="3k" else 10.0,"duration_s":2400.0,"avg_hr":150.0})
    return pd.DataFrame(rows)


def _sessions():
    rows=[]
    for i in range(40):
        pace=300+i*.2; hr=145+i%8
        rows.append({"source_file":f"s{i}.json","sha256":f"{i:064x}"[-64:],"session_date":pd.Timestamp("2020-01-01")+pd.Timedelta(days=i),"distance_km":10.0,"duration_s":pace*10,"avg_hr":hr,"pace_sec_per_km":pace,"efficiency_pace_hr_v1":pace/hr,"efficiency_speed_hr_v2":3600/pace/hr})
    return pd.DataFrame(rows)


def test_registry_accounts_for_every_notebook_candidate():
    master=_master_for_candidates(); registry=build_registry(master)
    validate_registry(registry,master)
    assert len(registry)==24
    assert registry["candidate_status"].isin(["verified","pending_evidence","discarded"]).all()
    assert registry["race_id"].nunique()==24


def test_guadalajara_is_reincorporated_and_not_excluded():
    master=_master_for_candidates(); registry=build_registry(master)
    row=registry[registry["event_date"].eq("2025-11-30")].iloc[0]
    assert row["candidate_status"]=="verified"
    assert row["event_type"]=="race"
    assert row["distance_class"]=="Marathon"
    assert row["default_modeling_eligible"]
    assert row["exclusion_reason"]==""


def test_ambiguous_three_session_3k_remains_pending():
    registry=build_registry(_master_for_candidates())
    row=registry[registry["event_date"].eq("2024-12-06")].iloc[0]
    assert row["candidate_status"]=="pending_evidence"
    assert not row["default_modeling_eligible"]
    assert row["source_file"]==""


def test_registry_links_modern_timestamp_after_legacy_rows():
    master=_master_for_candidates()
    mask=master["session_date"].str.startswith("2026-02-22")
    master.loc[mask,"session_date"]="2026-02-22T06:40:21"
    registry=build_registry(master)
    row=registry[registry["event_date"].eq("2026-02-22")].iloc[0]
    assert row["candidate_status"]=="verified"
    assert row["source_file"]


def test_candidate_ranges_are_detection_only():
    config=load_candidate_ranges("config/race_candidate_ranges.yml")
    assert config["purpose"]=="candidate_detection_only"
    assert "never establishes" in config["normative_rule"]


def test_strict_cutoff_excludes_equal_and_future_sessions():
    df=pd.DataFrame({"session_date":["2025-01-01T09:59:59","2025-01-01T10:00:00","2025-01-02"],"source_file":["before","equal","future"]})
    result=sessions_before_cutoff(df,pd.Timestamp("2025-01-01T10:00:00"))
    assert result["source_file"].tolist()==["before"]


def test_feature_contract_never_contains_actual_outcomes():
    sessions=_sessions(); target=pd.Series({"race_id":"r","session_date":"2020-03-01","nominal_distance_km":10.0,"distance_class":"10K","actual_total_time_s":999})
    features=build_target_context(target,sessions)
    assert not FORBIDDEN_PRE_RACE_COLUMNS.intersection(features)
    assert pd.Timestamp(features["training_cutoff"])==pd.Timestamp("2020-03-01")


def test_actual_outcomes_are_attached_only_for_evaluation():
    sessions=_sessions().head(1); sessions.loc[0,"source_file"]="race.json"; sessions.loc[0,"duration_s"]=1800
    registry=pd.DataFrame([{"source_file":"race.json","nominal_distance_km":10.0}])
    result=attach_observed_outcomes(registry,sessions)
    assert result.loc[0,"actual_total_time_s"]==1800
    assert result.loc[0,"actual_pace_sec_per_km"]==180


def test_model_reports_insufficient_history_instead_of_fabricating_prediction():
    target=pd.Series({"distance_class":"10K","nominal_distance_km":10.0})
    result=ClassMedianBaseline().predict(target,pd.DataFrame(),pd.DataFrame(columns=["actual_total_time_s","nominal_distance_km","distance_class","race_id"]))
    assert result.status=="insufficient_history"
    assert result.pace_sec_per_km is None


def test_all_approved_models_declare_contract_and_no_winner():
    models=approved_models(); ids=[m.declaration.model_id for m in models]
    assert len(ids)==10 and len(set(ids))==10
    assert "efficiency_speed_hr_linear_v2" in ids
    for model in models+supplemental_models():
        assert model.declaration.feature_contract
        assert model.declaration.eligibility_rules
        assert model.declaration.evaluation_protocol=="walk_forward_pre_race_v1"


def test_walk_forward_does_not_pass_actual_outcome_to_model():
    class Spy:
        class Declaration:
            model_id="spy"; model_version="1"; feature_contract="none"; training_window="none"; hyperparameters={}; eligibility_rules="none"; exclusion_rules="none"; evaluation_protocol="walk_forward_pre_race_v1"
        declaration=Declaration()
        def predict(self,target,prior_sessions,prior_races):
            assert "actual_total_time_s" not in target.index
            assert "actual_pace_sec_per_km" not in target.index
            from src.race_prediction.models import PredictionResult
            return PredictionResult("predicted",300.0,tuple())
    sessions=_sessions(); sessions.loc[len(sessions)]={"source_file":"race.json","sha256":"f"*64,"session_date":pd.Timestamp("2020-03-01"),"distance_km":10.0,"duration_s":2400.0,"avg_hr":160.0,"pace_sec_per_km":240.0,"efficiency_pace_hr_v1":1.5,"efficiency_speed_hr_v2":0.09375}
    registry=pd.DataFrame([{"race_id":"race","runner_id":"bqr_runner_001","source_file":"race.json","source_sha256":"f"*64,"event_name":"Race","event_date":"2020-03-01","session_date":"2020-03-01T00:00:00","observed_distance_km":10.0,"nominal_distance_km":10.0,"distance_class":"10K","event_type":"race","competition_context":"official_competition","candidate_status":"verified","verification_status":"verified_session_reported_event","evidence_status":"reported","evidence_type":"test","evidence_reference":"test","context_flags":"[]","descriptive_eligible":True,"default_modeling_eligible":True,"exclusion_reason":"","registry_version":"d3-1.0","recorded_at":"2026-08-03","recorded_by":"test","notes":""}])
    result=walk_forward(sessions,registry,[Spy()],code_commit="abc")
    assert result.loc[0,"actual_total_time_s"]==2400.0
    assert result.loc[0,"error_total_time_s"]==600.0


def test_frozen_artifacts_match_d3_baseline():
    baseline=json.loads(Path("reports/d3_frozen_baseline.json").read_text(encoding="utf-8"))["sha256"]
    for name,expected in baseline.items():
        actual=hashlib.sha256(Path(name).read_bytes()).hexdigest()
        assert actual==expected, name
