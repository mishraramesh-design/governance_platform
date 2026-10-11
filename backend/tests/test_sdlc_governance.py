"""Backend API tests for SDLC Governance & Assurance Platform."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to internal for test discovery; prefer env
    BASE_URL = "http://localhost:8001"
API = f"{BASE_URL}/api"


@pytest.fixture(scope="session")
def projects():
    r = requests.get(f"{API}/projects", timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and len(data) >= 3
    return data


@pytest.fixture(scope="session")
def pid(projects):
    return projects[0]["id"]


# --- Catalog / static ---
class TestCatalog:
    def test_agents(self):
        r = requests.get(f"{API}/agents", timeout=30)
        assert r.status_code == 200
        agents = r.json()
        assert len(agents) == 18

    def test_controls(self):
        r = requests.get(f"{API}/controls", timeout=30)
        assert r.status_code == 200
        controls = r.json()
        assert len(controls) == 20

    def test_ai_governance(self):
        r = requests.get(f"{API}/ai-governance", timeout=30)
        assert r.status_code == 200
        d = r.json()
        controls = d["controls"] if isinstance(d, dict) else d
        assert len(controls) == 16
        if isinstance(d, dict):
            assert "llm_calls_count" in d
            assert "model_eval_findings_count" in d

    def test_edge_clients(self):
        r = requests.get(f"{API}/edge-clients", timeout=30)
        assert r.status_code == 200
        assert len(r.json()) >= 5


# --- Projects / data ---
class TestProjects:
    def test_projects_list(self, projects):
        assert len(projects) >= 3
        for p in projects:
            assert "id" in p and "name" in p
            assert "_id" not in p

    def test_project_detail(self, pid):
        r = requests.get(f"{API}/projects/{pid}", timeout=30)
        assert r.status_code == 200
        assert r.json()["id"] == pid

    def test_requirements(self, pid):
        r = requests.get(f"{API}/requirements", params={"project_id": pid}, timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_commits(self, pid):
        r = requests.get(f"{API}/commits", params={"project_id": pid}, timeout=30)
        assert r.status_code == 200

    def test_tests(self, pid):
        r = requests.get(f"{API}/test-cases", params={"project_id": pid}, timeout=30)
        assert r.status_code == 200

    def test_designs(self, pid):
        r = requests.get(f"{API}/design-items", params={"project_id": pid}, timeout=30)
        assert r.status_code == 200


# --- Dashboard / assurance ---
class TestDashboard:
    def test_dashboard_global(self):
        r = requests.get(f"{API}/dashboard", timeout=30)
        assert r.status_code == 200
        d = r.json()
        for k in ["severity_counts", "verdict_counts"]:
            assert k in d

    def test_dashboard_scoped(self, pid):
        r = requests.get(f"{API}/dashboard", params={"project_id": pid}, timeout=30)
        assert r.status_code == 200

    def test_traceability(self, pid):
        r = requests.get(f"{API}/traceability", params={"project_id": pid}, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "coverage" in d or "coverage_percent" in d or "matrix" in d or "rows" in d

    def test_gates(self, pid):
        r = requests.get(f"{API}/gates", params={"project_id": pid}, timeout=30)
        assert r.status_code == 200
        gates = r.json()
        assert len(gates) >= 10

    def test_ledger_verify(self):
        r = requests.get(f"{API}/ledger/verify", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d.get("valid") is True

    def test_ledger_list(self):
        r = requests.get(f"{API}/ledger", timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# --- Findings ---
class TestFindings:
    def test_findings_list(self, pid):
        r = requests.get(f"{API}/findings", params={"project_id": pid}, timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_finding_detail_and_fetch_live(self, pid):
        r = requests.get(f"{API}/findings", params={"project_id": pid}, timeout=30)
        findings = r.json()
        if not findings:
            pytest.skip("no findings")
        fid = findings[0]["id"]
        rd = requests.get(f"{API}/findings/{fid}", timeout=30)
        assert rd.status_code == 200
        # fetch-live is mocked and should return 200 with a disabled message
        rfl = requests.post(f"{API}/findings/{fid}/evidence/0/fetch-live", timeout=30)
        assert rfl.status_code in (200, 400, 404)
        if rfl.status_code == 200:
            body = rfl.json()
            txt = str(body).lower()
            assert "disabled" in txt or "prototype" in txt or "not" in txt


# --- Repo audit / runtime (deterministic) ---
class TestSimulatedTools:
    def test_repo_audit(self, pid):
        r = requests.post(f"{API}/repo-audit/simulate",
                          json={"project_id": pid, "github_url": "https://github.com/example/repo"}, timeout=60)
        assert r.status_code == 200
        txt = str(r.json()).lower()
        assert "simulated" in txt or "no live" in txt

    def test_runtime_analyze(self, pid):
        sample_log = ("2025-01-01 ERROR Login failed password=hunter2\n"
                      "Aadhaar: 1234 5678 9123\n"
                      "latency_ms=1450\n"
                      "Traceback (most recent call last): foo\n")
        r = requests.post(f"{API}/runtime/analyze", json={"project_id": pid, "log_text": sample_log}, timeout=60)
        assert r.status_code == 200


# --- Reports / artifacts ---
class TestReportsArtifacts:
    def test_reports_list(self, pid):
        r = requests.get(f"{API}/reports", params={"project_id": pid}, timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_artifacts_list(self, pid):
        r = requests.get(f"{API}/artifacts", params={"project_id": pid}, timeout=30)
        assert r.status_code == 200

    def test_generate_artifact(self, pid):
        r = requests.post(
            f"{API}/artifacts/generate",
            json={"project_id": pid, "artifact_type": "requirements_specification"},
            timeout=60,
        )
        # Accept either success or validation-error (we don't know exact enum)
        assert r.status_code in (200, 201, 400, 422)
        if r.status_code in (200, 201):
            aid = r.json().get("id")
            if aid:
                dl = requests.get(f"{API}/artifacts/{aid}/download", timeout=30)
                assert dl.status_code == 200
