"""Build and validate all reproducible D3 artifacts without touching D1/D2."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

import pandas as pd

from src.analysis.d2_dataset import load_analytical_sessions
from src.race_prediction.evaluation import circularity_ablation, walk_forward
from src.race_prediction.metrics import summarize_predictions
from src.race_prediction.models import approved_models, supplemental_models
from src.race_prediction.registry import build_registry, load_candidate_ranges, registry_manifest_hash, validate_registry

MASTER=ROOT/"data/processed/sessions_master.parquet"
REGISTRY=ROOT/"data/reference/race_registry.csv"
EXCLUSIONS=ROOT/"data/reference/race_model_exclusions.csv"
PREDICTIONS=ROOT/"reports/d3_walk_forward_predictions.csv"
SUMMARY=ROOT/"reports/d3_validation_summary.json"
DECLARATIONS=ROOT/"reports/d3_model_declarations.json"
BASELINE=ROOT/"reports/d3_frozen_baseline.json"

def sha(path: Path) -> str:
    h=hashlib.sha256();
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()

def verify_frozen() -> dict:
    expected=json.loads(BASELINE.read_text(encoding="utf-8"))["sha256"]
    current={name:sha(ROOT/name) for name in expected}
    mismatches={name:{"expected":expected[name],"actual":current[name]} for name in expected if current[name]!=expected[name]}
    if mismatches: raise RuntimeError(f"frozen D1/D2 inputs changed: {mismatches}")
    return current

def git_head() -> str:
    return subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()

def main() -> None:
    frozen_before=verify_frozen()
    ranges=load_candidate_ranges(ROOT/"config/race_candidate_ranges.yml")
    if ranges["purpose"]!="candidate_detection_only": raise ValueError("candidate ranges cannot classify races")
    sessions=load_analytical_sessions(MASTER,scenario="canonical")
    master_raw=pd.read_parquet(MASTER)
    registry=build_registry(master_raw)
    validate_registry(registry,master_raw)
    REGISTRY.parent.mkdir(parents=True,exist_ok=True)
    registry.to_csv(REGISTRY,index=False,lineterminator="\n")
    pd.DataFrame(columns=["race_id","model_id","evaluation_protocol_id","excluded","reason_code","reason_text","evidence_reference","decision_version"]).to_csv(EXCLUSIONS,index=False,lineterminator="\n")
    models=approved_models()+supplemental_models()
    predictions=walk_forward(sessions,registry,models,code_commit=git_head())
    PREDICTIONS.parent.mkdir(parents=True,exist_ok=True)
    predictions.to_csv(PREDICTIONS,index=False,lineterminator="\n")
    declarations=[]
    for m in models:
        d=m.declaration
        declarations.append({"model_id":d.model_id,"model_version":d.model_version,"feature_contract":d.feature_contract,"training_window":d.training_window,"hyperparameters":d.hyperparameters,"eligibility_rules":d.eligibility_rules,"exclusion_rules":d.exclusion_rules,"evaluation_protocol":d.evaluation_protocol,"code_version":git_head(),"data_manifest":registry_manifest_hash(registry)})
    DECLARATIONS.write_text(json.dumps(declarations,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    summary={
        "contract_version":"d3-1.0","protocol":"walk_forward_pre_race_v1",
        "candidate_audit":{"total":len(registry),"by_status":registry["candidate_status"].value_counts().sort_index().to_dict(),"unclassified":int((~registry["candidate_status"].isin(["verified","pending_evidence","discarded"])).sum())},
        "verified_targets":int(registry["candidate_status"].eq("verified").sum()),
        "models_executed":[m.declaration.model_id for m in models],
        "metrics":summarize_predictions(predictions),"circularity_ablation":circularity_ablation(predictions),
        "registry_manifest_hash":registry_manifest_hash(registry),"prediction_rows":len(predictions),
        "frozen_inputs_sha256":frozen_before,"frozen_inputs_unchanged_after":verify_frozen()==frozen_before,
        "limitations":["Event verification is based on the curated notebook registry plus canonical session linkage; independent event documents remain pending except formal D3 resolution for Guadalajara.","The 2024-12-06 3K candidate has three same-day sessions and remains pending evidence."],
    }
    SUMMARY.write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__=="__main__": main()
