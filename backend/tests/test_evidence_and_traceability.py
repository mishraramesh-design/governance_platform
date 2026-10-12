"""Tests for new features: Evidence Pack export, Private repo token redaction, API Traceability (CTRL-03)."""
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"
REPO = "https://github.com/mishraramesh-design/myauction-node"


@pytest.fixture(scope="module")
def ingest():
    r = requests.post(f"{API}/repo-audit/ingest", json={"github_url": REPO}, timeout=180)
    assert r.status_code == 200, r.text[:500]
    return r.json()


@pytest.fixture(scope="module")
def pid(ingest):
    return ingest["project"]["id"]


class TestEvidencePack:
    def test_pdf(self, pid):
        r = requests.get(f"{API}/repo-audit/{pid}/evidence-pack", params={"format": "pdf"}, timeout=120)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert len(r.content) > 3000
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd.lower() and ".pdf" in cd.lower()

    def test_docx(self, pid):
        r = requests.get(f"{API}/repo-audit/{pid}/evidence-pack", params={"format": "docx"}, timeout=120)
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "wordprocessingml.document" in ct
        assert len(r.content) > 10000
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd.lower() and ".docx" in cd.lower()

    def test_404(self):
        r = requests.get(f"{API}/repo-audit/does-not-exist/evidence-pack", params={"format": "pdf"}, timeout=30)
        assert r.status_code == 404


class TestTraceability:
    def test_profile_spec(self, ingest):
        spec = ingest["project"].get("profile", {}).get("spec") or ingest.get("profile", {}).get("spec", {})
        assert spec, f"no spec in profile: {list(ingest.get('project',{}).get('profile',{}).keys())}"
        assert spec.get("endpoint_count", 0) > 0
        assert spec.get("untested_endpoints", -1) >= 0

    def test_audit_has_endpoints(self, ingest):
        audit = ingest.get("audit") or {}
        assert audit.get("endpoint_count", 0) > 0
        eps = audit.get("endpoints") or []
        assert len(eps) > 0
        ep = eps[0]
        for k in ("method", "path", "defined_in"):
            assert k in ep
        assert "tested_by" in ep

    def test_ctrl03_finding(self, pid):
        r = requests.get(f"{API}/findings", params={"project_id": pid}, timeout=30)
        assert r.status_code == 200
        fs = r.json()
        ctrl03 = [f for f in fs if f.get("control_id") == "CTRL-03"]
        assert ctrl03, "no CTRL-03 finding"
        for f in ctrl03:
            assert f.get("verdict") in ("PASS", "FAIL")


class TestPrivateTokenRedaction:
    def test_bad_token_redacted(self):
        token = "ghp_FAKE123"
        r = requests.post(f"{API}/repo-audit/ingest",
                          json={"github_url": "https://github.com/mishraramesh-design/some-private-or-missing-xyz",
                                "git_token": token}, timeout=120)
        assert r.status_code == 502, f"expected 502 got {r.status_code}"
        assert token not in r.text, "token leaked in response body!"


class TestRegression:
    def test_findings_count_and_controls(self, pid):
        r = requests.get(f"{API}/findings", params={"project_id": pid}, timeout=30)
        assert r.status_code == 200
        fs = r.json()
        assert len(fs) >= 70
        controls = {f.get("control_id") for f in fs}
        for c in ("CTRL-01", "CTRL-03", "CTRL-06", "CTRL-07", "CTRL-10", "CTRL-11", "CTRL-15", "CTRL-16", "CTRL-17", "CTRL-18"):
            assert c in controls, f"missing {c}; got {sorted(controls)}"

    def test_reaudit_same_project_id(self, pid):
        r = requests.post(f"{API}/repo-audit/ingest", json={"github_url": REPO}, timeout=180)
        assert r.status_code == 200
        assert r.json()["project"]["id"] == pid
        # single project for repo
        p = requests.get(f"{API}/projects", timeout=30).json()
        matches = [x for x in p if x.get("source") == "github_live" and REPO in (x.get("repo_url") or "")]
        assert len(matches) == 1

    def test_mlops_secrets_f1(self):
        r = requests.get(f"{API}/mlops/metrics", timeout=30)
        assert r.status_code == 200
        d = r.json()
        secrets = [x for x in d["detectors"] if x.get("detector") == "secrets"]
        assert secrets
        assert abs(secrets[0]["f1"] - 0.8) < 0.05
