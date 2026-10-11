"""Tests for the four most recent feature areas:
Agent Harness/Sovereignty, Model Gateway (four roles+custom), MLOps Learning Harness,
and regression on Design/System-Test detectors + Gates + Ledger linkage.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def pid():
    r = requests.get(f"{API}/projects", timeout=30)
    assert r.status_code == 200
    return r.json()[0]["id"]


# --- Harness: 22 agents and sandbox + sovereignty ---
class TestHarness:
    def test_harness_agents_22(self):
        r = requests.get(f"{API}/harness/agents", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["summary"]["total"] == 22
        ids = {a["id"] for a in d["agents"]}
        for i in range(1, 23):
            assert f"A{i:02d}" in ids

    def test_agent_prompt_present(self):
        r = requests.get(f"{API}/harness/agents/A02", timeout=30)
        assert r.status_code == 200
        a = r.json()
        assert a["id"] == "A02"
        # persona prompt should be non-empty
        prompt = a.get("system_prompt") or a.get("prompt") or a.get("persona_prompt") or ""
        assert isinstance(prompt, str) and len(prompt) > 20

    def test_sovereignty_block_a05_t1(self):
        r = requests.post(f"{API}/harness/sandbox",
                          json={"agent_id": "A05", "level": 1, "tier": "T1",
                                "masked_input": "masked aadhaar 23****23"}, timeout=30)
        assert r.status_code == 200
        assert r.json()["mode"] == "sovereignty-blocked"

    def test_sovereignty_allowed_a05_t2(self):
        r = requests.post(f"{API}/harness/sandbox",
                          json={"agent_id": "A05", "level": 1, "tier": "T2",
                                "masked_input": "masked aadhaar 23****23"}, timeout=60)
        assert r.status_code == 200
        assert r.json()["mode"] == "llm"


# --- Model Gateway Settings (four roles + custom validation) ---
class TestGatewayConfig:
    def test_get_config_has_four_roles_and_sovereignty(self):
        r = requests.get(f"{API}/harness/config", timeout=30)
        assert r.status_code == 200
        d = r.json()
        profiles = d["capability_profiles"]
        for role in ("maker", "checker", "security", "verifier"):
            assert role in profiles and profiles[role] is not None
        assert "sovereignty" in d and isinstance(d["sovereignty"], dict)
        for t in ("T0", "T1", "T2", "T3", "T4"):
            assert t in d["sovereignty"]

    def test_custom_provider_requires_base_url(self):
        r = requests.get(f"{API}/harness/config", timeout=30).json()
        profiles = r["capability_profiles"]
        payload_profiles = {k: ({"provider": v["provider"], "model": v["model"],
                                 "api_key": "", "base_url": v.get("base_url", ""),
                                 "local_only": v.get("local_only", False)}
                                if v else None)
                            for k, v in profiles.items()}
        # break maker to custom with no base_url
        payload_profiles["maker"] = {"provider": "custom", "model": "foo-model",
                                     "api_key": "", "base_url": "", "local_only": True}
        resp = requests.put(f"{API}/harness/config",
                            json={"capability_profiles": payload_profiles,
                                  "zero_llm_mode": r["zero_llm_mode"],
                                  "sovereignty": r["sovereignty"]}, timeout=30)
        assert resp.status_code == 400
        assert "base_url" in resp.text


# --- MLOps Learning Harness ---
class TestMlops:
    def test_registry_30_entries(self):
        r = requests.get(f"{API}/mlops/registry", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["summary"]["total"] == 30
        assert d["summary"]["by_kind"].get("rule_pack") == 4
        assert d["promotion_threshold"] == 0.8

    def test_metrics_fields_and_detectors(self):
        r = requests.get(f"{API}/mlops/metrics", timeout=30)
        assert r.status_code == 200
        d = r.json()
        for k in ("not_assessed_rate", "l1_l2_disagreement_rate",
                  "zero_llm_share", "noise_ratio", "detectors"):
            assert k in d
        assert len(d["detectors"]) == 4
        for det in d["detectors"]:
            assert 0 <= det["precision"] <= 1
            assert 0 <= det["f1"] <= 1

    def _get_rule_pack(self, ref):
        d = requests.get(f"{API}/mlops/registry", timeout=30).json()
        for e in d["entries"]:
            if e["kind"] == "rule_pack" and e["ref"] == ref:
                return e
        pytest.skip(f"rule_pack {ref} not found")

    def test_evaluate_rule_pack(self):
        entry = self._get_rule_pack("secrets")
        r = requests.post(f"{API}/mlops/registry/{entry['id']}/evaluate", timeout=30)
        assert r.status_code == 200
        res = r.json()["result"]
        assert "f1" in res and 0 <= res["f1"] <= 1

    def test_shadow_compare_recommends(self):
        entry = self._get_rule_pack("secrets")
        r = requests.post(f"{API}/mlops/registry/{entry['id']}/shadow-compare", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["recommendation"] in ("promote", "hold")
        assert "candidate_f1" in d and "baseline_f1" in d

    def test_promote_rule_pack(self):
        entry = self._get_rule_pack("secrets")
        # ensure recent eval first
        requests.post(f"{API}/mlops/registry/{entry['id']}/evaluate", timeout=30)
        r = requests.post(f"{API}/mlops/registry/{entry['id']}/promote", timeout=30)
        # should pass since synthetic eval f1 is high
        assert r.status_code in (200, 400)
        if r.status_code == 400:
            assert "threshold" in r.text.lower()


# --- Regression: Design + System-Test detectors ---
class TestDetectorsRegression:
    def test_findings_have_new_controls_not_assessed_free(self, pid):
        r = requests.get(f"{API}/findings", params={"project_id": pid}, timeout=30)
        assert r.status_code == 200
        fs = r.json()
        wanted = {"CTRL-04", "CTRL-05", "CTRL-15", "CTRL-16", "CTRL-17", "CTRL-18"}
        found = {}
        for f in fs:
            c = f.get("control_id")
            if c in wanted:
                found.setdefault(c, []).append(f.get("verdict"))
        missing = wanted - set(found.keys())
        assert not missing, f"missing controls: {missing}"
        for c, verdicts in found.items():
            assert "NOT_ASSESSED" not in verdicts, f"{c} still NOT_ASSESSED"

    def test_gates_g3_g6_real_status(self, pid):
        r = requests.get(f"{API}/gates", params={"project_id": pid}, timeout=30)
        assert r.status_code == 200
        gates = r.json()
        status_by_id = {(g.get("gate_id") or g.get("id")): g.get("status") for g in gates}
        for gk in ("G3", "G6"):
            s = status_by_id.get(gk)
            assert s and s != "Not Assessed", f"gate {gk} status={s}"


# --- Ledger linkage ---
class TestLedger:
    def test_ledger_has_mlops_types(self):
        r = requests.get(f"{API}/ledger", timeout=30)
        assert r.status_code == 200
        rows = r.json()
        mlops_types = {"mlops_registry_initialised", "mlops_shadow_compare",
                       "registry_promotion", "eval_run"}
        types = {row.get("payload_type") or row.get("type") or row.get("event_type") for row in rows}
        assert mlops_types & types, f"no mlops ledger types found; sample={list(types)[:10]}"

    def test_ledger_verify(self):
        r = requests.get(f"{API}/ledger/verify", timeout=30)
        assert r.status_code == 200
        assert r.json().get("valid") is True
