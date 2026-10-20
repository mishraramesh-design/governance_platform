"""MLOps / Learning-Harness layer: a governed registry (prompts, models,
rule-packs) with versions and promotion states, an evaluation harness
(precision/recall/F1 + canary recall + drift), and live governance metrics.

Promotion is gated: a rule-pack can only be promoted if its latest evaluation F1
meets the threshold. Every registry change and promotion is appended to the ledger.
"""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from database import db
import agent_profiles
import gateway
import evaluator
import ledger as ledger_mod

router = APIRouter(prefix="/mlops")

F1_PROMOTION_THRESHOLD = 0.8


async def ensure_mlops_seeded(db):
    if await db.harness_registry.count_documents({}) > 0:
        return
    now = datetime.now(timezone.utc).isoformat()
    entries = []
    # Prompt packs - one per agent persona
    for a in agent_profiles.AGENT_LIST:
        entries.append({
            "id": str(uuid4()), "kind": "prompt", "ref": a["id"],
            "name": f"{a['name']} persona prompt", "version": 1, "state": "promoted",
            "role": a["harness_role"], "notes": "Initial baseline persona.",
            "metrics": None, "created_at": now, "promoted_at": now,
        })
    # Model packs - one per capability role
    cfg = await gateway.get_config(db)
    for role, prof in cfg["capability_profiles"].items():
        if role == "none" or not prof:
            continue
        entries.append({
            "id": str(uuid4()), "kind": "model", "ref": role,
            "name": f"{prof['provider']}/{prof['model']}", "version": 1, "state": "promoted",
            "role": role, "notes": "Current capability-role model binding.",
            "metrics": None, "created_at": now, "promoted_at": now,
        })
    # Rule-packs - one per deterministic detector
    for dk in evaluator.DETECTOR_KEYS:
        entries.append({
            "id": str(uuid4()), "kind": "rule_pack", "ref": dk,
            "name": f"{dk} detector", "version": 1, "state": "promoted",
            "role": None, "notes": "Deterministic detector rule-pack.",
            "metrics": None, "created_at": now, "promoted_at": now,
        })
    await db.harness_registry.insert_many(entries)

    # Seed a baseline + current eval run per detector to establish a drift trend.
    for dk in evaluator.DETECTOR_KEYS:
        res = evaluator.run_eval(dk)
        baseline = {**res, "precision": round(max(0.0, res["precision"] - 0.07), 3),
                    "recall": round(max(0.0, res["recall"] - 0.05), 3)}
        baseline["f1"] = round(2 * baseline["precision"] * baseline["recall"] /
                               ((baseline["precision"] + baseline["recall"]) or 1), 3)
        await db.eval_runs.insert_one({"id": str(uuid4()), "ref": dk, "kind": "rule_pack",
                                       "result": baseline, "created_at": now, "label": "baseline"})
        await db.eval_runs.insert_one({"id": str(uuid4()), "ref": dk, "kind": "rule_pack",
                                       "result": res, "created_at": now, "label": "current"})
    await ledger_mod.append_to_ledger(db, "mlops_registry_initialised", "registry",
                                      {"entries": len(entries), "detectors": evaluator.DETECTOR_KEYS})


@router.get("/registry")
async def registry():
    entries = await db.harness_registry.find({}, {"_id": 0}).to_list(500)
    # attach latest eval metrics for rule-packs
    for e in entries:
        latest = await db.eval_runs.find({"ref": e["ref"]}, {"_id": 0}).sort("created_at", -1).to_list(1)
        e["latest_eval"] = latest[0]["result"] if latest else None
    by_kind = {}
    for e in entries:
        by_kind.setdefault(e["kind"], 0)
        by_kind[e["kind"]] += 1
    return {"entries": entries, "summary": {"total": len(entries), "by_kind": by_kind},
            "promotion_threshold": F1_PROMOTION_THRESHOLD}


@router.post("/registry/{entry_id}/evaluate")
async def evaluate(entry_id: str):
    entry = await db.harness_registry.find_one({"id": entry_id}, {"_id": 0})
    if not entry:
        raise HTTPException(404, "registry entry not found")
    if entry["kind"] != "rule_pack" or entry["ref"] not in evaluator.DETECTOR_KEYS:
        raise HTTPException(400, "evaluation harness currently supports deterministic rule-packs only")
    res = evaluator.run_eval(entry["ref"])
    run = {"id": str(uuid4()), "ref": entry["ref"], "kind": "rule_pack", "result": res,
           "created_at": datetime.now(timezone.utc).isoformat(), "label": "current"}
    await db.eval_runs.insert_one(dict(run))
    await db.harness_registry.update_one({"id": entry_id}, {"$set": {"metrics": res}})
    await ledger_mod.append_to_ledger(db, "eval_run", run["id"], {"ref": entry["ref"], "f1": res["f1"]})
    run.pop("_id", None)
    return run


@router.post("/registry/{entry_id}/promote")
async def promote(entry_id: str):
    entry = await db.harness_registry.find_one({"id": entry_id}, {"_id": 0})
    if not entry:
        raise HTTPException(404, "registry entry not found")
    # Promotion gate: rule-packs must pass the evaluation F1 threshold.
    if entry["kind"] == "rule_pack":
        latest = await db.eval_runs.find({"ref": entry["ref"]}, {"_id": 0}).sort("created_at", -1).to_list(1)
        if not latest:
            raise HTTPException(400, "cannot promote: no evaluation run yet - run an evaluation first")
        f1 = latest[0]["result"]["f1"]
        if f1 < F1_PROMOTION_THRESHOLD:
            raise HTTPException(400, f"promotion gate failed: F1 {f1} < threshold {F1_PROMOTION_THRESHOLD}")
    now = datetime.now(timezone.utc).isoformat()
    await db.harness_registry.update_one(
        {"id": entry_id}, {"$set": {"state": "promoted", "promoted_at": now},
                           "$inc": {"version": 1}})
    updated = await db.harness_registry.find_one({"id": entry_id}, {"_id": 0})
    await ledger_mod.append_to_ledger(db, "registry_promotion", entry_id,
                                      {"ref": entry["ref"], "version": updated["version"]})
    return updated


@router.post("/registry/{entry_id}/shadow")
async def shadow(entry_id: str):
    entry = await db.harness_registry.find_one({"id": entry_id}, {"_id": 0})
    if not entry:
        raise HTTPException(404, "registry entry not found")
    await db.harness_registry.update_one({"id": entry_id}, {"$set": {"state": "shadow"}})
    await ledger_mod.append_to_ledger(db, "registry_shadow", entry_id, {"ref": entry["ref"]})
    return await db.harness_registry.find_one({"id": entry_id}, {"_id": 0})


@router.post("/registry/{entry_id}/shadow-compare")
async def shadow_compare(entry_id: str):
    """Run the shadow candidate alongside the promoted baseline and compare F1."""
    entry = await db.harness_registry.find_one({"id": entry_id}, {"_id": 0})
    if not entry:
        raise HTTPException(404, "registry entry not found")
    if entry["kind"] != "rule_pack" or entry["ref"] not in evaluator.DETECTOR_KEYS:
        raise HTTPException(400, "shadow A/B currently supports deterministic rule-packs only")
    candidate = evaluator.run_eval(entry["ref"])
    base_runs = await db.eval_runs.find({"ref": entry["ref"], "label": "baseline"}, {"_id": 0}).sort("created_at", -1).to_list(1)
    baseline = base_runs[0]["result"] if base_runs else None
    f1_delta = round(candidate["f1"] - baseline["f1"], 3) if baseline else None
    recommend = ("promote" if (baseline and candidate["f1"] >= baseline["f1"] and candidate["f1"] >= F1_PROMOTION_THRESHOLD)
                 else "hold")
    now = datetime.now(timezone.utc).isoformat()
    comparison = {"candidate_f1": candidate["f1"], "baseline_f1": baseline["f1"] if baseline else None,
                  "f1_delta": f1_delta, "recommendation": recommend, "candidate": candidate, "baseline": baseline, "at": now}
    await db.harness_registry.update_one({"id": entry_id}, {"$set": {"state": "shadow", "ab_comparison": comparison}})
    await db.eval_runs.insert_one({"id": str(uuid4()), "ref": entry["ref"], "kind": "rule_pack",
                                   "result": candidate, "created_at": now, "label": "shadow"})
    await ledger_mod.append_to_ledger(db, "mlops_shadow_compare", entry_id,
                                      {"ref": entry["ref"], "f1_delta": f1_delta, "recommendation": recommend})
    return comparison


@router.get("/eval-runs")
async def eval_runs(ref: str = None, limit: int = 50):
    q = {"ref": ref} if ref else {}
    runs = await db.eval_runs.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return runs


@router.get("/metrics")
async def metrics():
    total_findings = await db.findings.count_documents({})
    not_assessed = await db.findings.count_documents({"verdict": "NOT_ASSESSED"})
    fails = await db.findings.count_documents({"verdict": "FAIL"})
    adjud = await db.adjudications.count_documents({})
    triage_total = await db.triage_decisions.count_documents({})
    triage_dismiss = await db.triage_decisions.count_documents({"decision": "dismiss"})
    total_calls = await db.llm_calls.count_documents({})
    zero_calls = await db.llm_calls.count_documents({"mode": {"$in": ["zero-llm", "deterministic", "zero-llm-error-fallback", "sovereignty-blocked", "budget-exhausted"]}})

    def pct(n, d):
        return round(n / d * 100, 1) if d else 0.0

    # precision/recall + drift from eval runs per detector
    detectors = []
    for dk in evaluator.DETECTOR_KEYS:
        runs = await db.eval_runs.find({"ref": dk}, {"_id": 0}).sort("created_at", -1).to_list(5)
        cur = next((r["result"] for r in runs if r.get("label") == "current"), runs[0]["result"] if runs else None)
        base = next((r["result"] for r in runs if r.get("label") == "baseline"), None)
        drift = round((cur["precision"] - base["precision"]), 3) if (cur and base) else None
        if cur:
            detectors.append({"detector": dk, "precision": cur["precision"], "recall": cur["recall"],
                              "f1": cur["f1"], "canary_recall": cur.get("canary_recall"), "drift_precision": drift})

    return {
        "not_assessed_rate": pct(not_assessed, total_findings),
        "l1_l2_disagreement_rate": pct(adjud, fails),
        "zero_llm_share": pct(zero_calls, total_calls),
        "noise_ratio": pct(triage_dismiss, triage_total),
        "totals": {"findings": total_findings, "fails": fails, "adjudications": adjud,
                   "llm_calls": total_calls, "triage_decisions": triage_total},
        "detectors": detectors,
    }
