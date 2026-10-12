"""Tests for the live GitHub repository audit feature (A21 Stack Profiler).

Clones a public repo, profiles the stack, runs detectors, generates reports
and the gate pack. Validation errors and persistence are also covered.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

TEST_REPO = "https://github.com/mishraramesh-design/myauction-node"
# Long timeout: clone + scan + 2 real LLM report calls
INGEST_TIMEOUT = 180


@pytest.fixture(scope="module")
def audit_result():
    r = requests.post(f"{API}/repo-audit/ingest",
                      json={"github_url": TEST_REPO}, timeout=INGEST_TIMEOUT)
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:400]}"
    return r.json()


# --- Validation (fast) ---
class TestRepoAuditValidation:
    def test_malformed_url_returns_400(self):
        r = requests.post(f"{API}/repo-audit/ingest",
                          json={"github_url": "not-a-url"}, timeout=30)
        assert r.status_code == 400
        assert "detail" in r.json()

    def test_non_github_url_returns_400(self):
        r = requests.post(f"{API}/repo-audit/ingest",
                          json={"github_url": "https://gitlab.com/foo/bar"}, timeout=30)
        assert r.status_code == 400

    def test_nonexistent_repo_returns_502(self):
        r = requests.post(f"{API}/repo-audit/ingest",
                          json={"github_url": "https://github.com/mishraramesh-design/this-does-not-exist-xyz"},
                          timeout=INGEST_TIMEOUT)
        assert r.status_code == 502


# --- Live ingest (slow) ---
class TestRepoAuditIngest:
    def test_project_shape(self, audit_result):
        proj = audit_result["project"]
        assert proj["name"] == "myauction-node"
        assert proj["integrity_tier"] in ("T0", "T1", "T2", "T3", "T4")
        assert isinstance(proj.get("id"), str) and len(proj["id"]) > 0

    def test_profile_shape(self, audit_result):
        prof = audit_result["profile"]
        assert isinstance(prof["languages"], dict) and len(prof["languages"]) > 0
        assert isinstance(prof["frameworks"], list)
        assert prof["code_files_scanned"] > 0
        assert prof["approx_loc"] > 0

    def test_finding_summary(self, audit_result):
        fs = audit_result["finding_summary"]
        assert fs["total"] > 0
        assert isinstance(fs["by_severity"], dict)
        assert isinstance(fs["by_control"], dict)
        assert fs["fail"] > 0

    def test_reports_two(self, audit_result):
        reports = audit_result["reports"]
        assert len(reports) == 2
        types = {r["type"] for r in reports}
        assert types == {"author", "team_lead"}
        for r in reports:
            assert isinstance(r.get("narrative"), str) and len(r["narrative"]) > 20
            assert r.get("ledger_hash")

    def test_gates_ten(self, audit_result):
        gates = audit_result["gates"]
        assert len(gates) == 10
        for g in gates:
            assert "id" in g and "name" in g and "status" in g


# --- Persistence ---
class TestRepoAuditPersistence:
    def test_project_listed(self, audit_result):
        pid = audit_result["project"]["id"]
        r = requests.get(f"{API}/projects", timeout=30)
        assert r.status_code == 200
        ids = {p["id"] for p in r.json()}
        assert pid in ids

    def test_findings_persisted(self, audit_result):
        pid = audit_result["project"]["id"]
        r = requests.get(f"{API}/findings", params={"project_id": pid}, timeout=30)
        assert r.status_code == 200
        fs = r.json()
        assert len(fs) > 0
        ctrls = {f["control_id"] for f in fs}
        assert ctrls & {"CTRL-06", "CTRL-07", "CTRL-08", "CTRL-10"}
        for f in fs:
            assert f.get("subject_type") == "file"
            assert f.get("verdict") in ("PASS", "FAIL")
            assert f.get("level2_status")

    def test_ledger_entries(self, audit_result):
        pid = audit_result["project"]["id"]
        r = requests.get(f"{API}/ledger", timeout=60)
        assert r.status_code == 200
        rows = r.json()
        types = [row.get("payload_type") or row.get("type") for row in rows]
        assert "repo_audit" in types
        # finding/report entries present somewhere in ledger
        assert "finding" in types
        assert "report" in types
