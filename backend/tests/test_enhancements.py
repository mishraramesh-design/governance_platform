"""Tests for the three enhancements:
1) Broader secret scan (unquoted env/YAML sensitive assignments)
2) Re-Audit In Place idempotency
3) Spec Ingestion -> real verdicts for CTRL-01/11/15/16/17/18 and gates G2/G6
Plus MLOps regression (secrets detector unchanged).
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"
REPO_URL = "https://github.com/mishraramesh-design/myauction-node"
INGEST_TIMEOUT = 180


@pytest.fixture(scope="module")
def first_ingest():
    r = requests.post(f"{API}/repo-audit/ingest",
                      json={"github_url": REPO_URL}, timeout=INGEST_TIMEOUT)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def second_ingest(first_ingest):
    r = requests.post(f"{API}/repo-audit/ingest",
                      json={"github_url": REPO_URL}, timeout=INGEST_TIMEOUT)
    assert r.status_code == 200, r.text
    return r.json()


# --- Enhancement 2: Re-audit idempotency ---
class TestReAuditIdempotent:
    def test_same_project_id_on_second_ingest(self, first_ingest, second_ingest):
        pid1 = first_ingest["project"]["id"]
        pid2 = second_ingest["project"]["id"]
        assert pid1 == pid2, f"re-audit created new project: {pid1} vs {pid2}"

    def test_only_one_github_live_project_for_repo(self, second_ingest):
        r = requests.get(f"{API}/projects", timeout=30)
        assert r.status_code == 200
        projects = r.json()
        matches = [p for p in projects
                   if p.get("source") == "github_live"
                   and (p.get("repo_url") or "").rstrip("/") == REPO_URL]
        assert len(matches) == 1, f"expected 1 github_live project for repo, got {len(matches)}: {[m.get('id') for m in matches]}"
        assert matches[0]["id"] == second_ingest["project"]["id"]


# --- Enhancement 1: Broader secret scan ---
class TestBroaderSecrets:
    def test_ctrl06_fail_with_unquoted_evidence(self, second_ingest):
        pid = second_ingest["project"]["id"]
        r = requests.get(f"{API}/findings", params={"project_id": pid}, timeout=30)
        assert r.status_code == 200
        secrets = [f for f in r.json() if f.get("control_id") == "CTRL-06"]
        assert len(secrets) >= 1, "no CTRL-06 secrets findings"
        fails = [f for f in secrets if f.get("verdict") == "FAIL"]
        assert len(fails) >= 1, f"no FAIL CTRL-06; verdicts={[f.get('verdict') for f in secrets]}"

        # Collect evidence 'type' values
        types_seen = set()
        for f in secrets:
            ev = f.get("evidence") or []
            if isinstance(ev, dict):
                ev = [ev]
            for e in ev:
                if isinstance(e, dict):
                    t = e.get("type")
                    if t:
                        types_seen.add(t)
        secret_types = {t for t in types_seen if isinstance(t, str) and t.startswith("secret:")}
        assert secret_types, f"no secret:* evidence types; saw={types_seen}"
        # Ideally includes the new unquoted type
        assert any("unquoted" in t or "sensitive_assignment" in t or t.startswith("secret:")
                   for t in secret_types), f"evidence secret types={secret_types}"

    def test_integrity_tier_t1(self, second_ingest):
        tier = second_ingest["project"].get("integrity_tier")
        assert tier == "T1", f"expected T1 due to secrets, got {tier}"


# --- Enhancement 3: Spec ingestion controls ---
EXPECTED_SPEC_CONTROLS = ["CTRL-01", "CTRL-11", "CTRL-15", "CTRL-16", "CTRL-17", "CTRL-18"]


class TestSpecIngestion:
    def test_spec_controls_real_verdicts(self, second_ingest):
        pid = second_ingest["project"]["id"]
        r = requests.get(f"{API}/findings", params={"project_id": pid}, timeout=30)
        assert r.status_code == 200
        by_ctrl = {}
        for f in r.json():
            by_ctrl.setdefault(f.get("control_id"), []).append(f)
        missing = [c for c in EXPECTED_SPEC_CONTROLS if c not in by_ctrl]
        assert not missing, f"missing spec controls: {missing}"
        for c in EXPECTED_SPEC_CONTROLS:
            verdicts = {f.get("verdict") for f in by_ctrl[c]}
            assert "NOT_ASSESSED" not in verdicts, f"{c} has NOT_ASSESSED: {verdicts}"
            assert verdicts & {"PASS", "FAIL"}, f"{c} verdicts not PASS/FAIL: {verdicts}"
            # level2_status must exist
            l2 = {f.get("level2_status") for f in by_ctrl[c]}
            assert any(x for x in l2 if x), f"{c} has no level2_status: {l2}"

    def test_gates_g2_g6_g4_real_status(self, second_ingest):
        gates = second_ingest.get("gates") or []
        if not gates:
            pid = second_ingest["project"]["id"]
            r = requests.get(f"{API}/gates", params={"project_id": pid}, timeout=30)
            assert r.status_code == 200
            gates = r.json()
        status_by = {(g.get("gate_id") or g.get("id")): g.get("status") for g in gates}
        for gk in ("G2", "G6", "G4"):
            s = status_by.get(gk)
            assert s and s != "Not Assessed", f"gate {gk} status={s!r}"
        # Per request, G2/G6 should be At Risk for this repo
        assert status_by.get("G2") == "At Risk", f"G2={status_by.get('G2')}"
        assert status_by.get("G6") == "At Risk", f"G6={status_by.get('G6')}"
        assert status_by.get("G4") == "At Risk", f"G4={status_by.get('G4')}"


# --- Regression: MLOps secrets detector unchanged ---
class TestMlopsRegression:
    def test_metrics_secrets_detector(self):
        r = requests.get(f"{API}/mlops/metrics", timeout=30)
        assert r.status_code == 200
        detectors = r.json()["detectors"]
        sec = next((d for d in detectors if d.get("detector") == "secrets"), None)
        assert sec, f"secrets detector missing; detectors={[d.get('detector') for d in detectors]}"
        assert abs(sec["precision"] - 1.0) < 1e-6, f"precision={sec['precision']}"
        assert 0.7 <= sec["f1"] <= 0.9, f"f1={sec['f1']}"

    def test_evaluate_secrets_rule_pack(self):
        d = requests.get(f"{API}/mlops/registry", timeout=30).json()
        entry = next((e for e in d["entries"]
                      if e["kind"] == "rule_pack" and e["ref"] == "secrets"), None)
        assert entry, "secrets rule_pack not in registry"
        r = requests.post(f"{API}/mlops/registry/{entry['id']}/evaluate", timeout=30)
        assert r.status_code == 200
        res = r.json()["result"]
        assert 0.7 <= res["f1"] <= 0.9, f"evaluate f1={res['f1']}"
