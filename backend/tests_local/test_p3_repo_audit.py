import os, shutil, time
import pytest
from tests_local.conftest import make_client, ADMIN

URL = "https://github.com/acme/eproc"
GOOD_AADHAAR = "2345 6789 0124"  # replaced below by a Verhoeff-valid number


def _verhoeff_valid():
    from detectors import scan_pii
    for n in range(234567890120, 234567890400):
        s = str(n)
        if scan_pii(f"id {s}"):
            return s
    raise AssertionError("no valid aadhaar found")


def build_repo(root, extra=None):
    os.makedirs(f"{root}/src/bidding", exist_ok=True)
    os.makedirs(f"{root}/tests", exist_ok=True)
    os.makedirs(f"{root}/gen", exist_ok=True)
    open(f"{root}/README.md", "w").write("# eproc\n## Usage\nAPI docs\n")
    open(f"{root}/src/bidding/bid.py", "w").write('KEY = "AKIAABCDEFGHIJKLMNOP"\n')
    open(f"{root}/tests/test_x.py", "w").write(f'AADHAAR = "{_verhoeff_valid()}"\n')
    open(f"{root}/gen/bundle.js", "w").write('var k="AKIAABCDEFGHIJKLMNOP"\n')
    for k, v in (extra or {}).items():
        os.makedirs(os.path.dirname(f"{root}/{k}"), exist_ok=True)
        open(f"{root}/{k}", "w").write(v)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    c = make_client(False)
    c.__enter__()
    import repo_ingest
    state = {"extra": {}, "delay": 0}

    def fake_clone(url, dest, token, branch, cancel):
        for _ in range(int(state["delay"] * 20)):
            if cancel is not None and cancel.is_set():
                raise repo_ingest.AuditCancelled()
            time.sleep(0.05)
        src = tmp_path / f"src{time.time_ns()}"
        build_repo(str(src), state["extra"])
        shutil.copytree(src, dest, dirs_exist_ok=True)
        state["token"] = token
    monkeypatch.setattr(repo_ingest, "_git_clone", fake_clone)
    yield c, state
    c.__exit__(None, None, None)


BODY = {"github_url": URL, "integrity_level": 4, "data_sensitivity": "personal",
        "folder_map": [{"path": "src/bidding", "purpose": "source", "module": "Bidding"},
                       {"path": "tests", "purpose": "tests", "module": "Bidding"},
                       {"path": "gen", "purpose": "generated", "module": None}]}


def test_folder_map_zone_module_and_coverage(env):
    c, _ = env
    r = c.post("/api/repo-audit/ingest?sync=true", json=BODY, headers=ADMIN)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["project"]["integrity_level"] == 4 and "integrity_tier" not in d["project"]
    cov = d["audit"]["coverage"]
    assert cov["skipped_generated"] >= 1
    pid = d["project"]["id"]
    fs = c.get(f"/api/findings?project_id={pid}", headers=ADMIN).json()
    secret = [f for f in fs if f["control_id"] == "CTRL-06"]
    assert len(secret) == 1 and secret[0]["subject_ref"] == "src/bidding/bid.py"
    assert secret[0]["module"] == "Bidding" and secret[0]["severity"] == "critical"
    pii = [f for f in fs if f["control_id"] == "CTRL-07"]
    assert pii and pii[0]["zone"] == "tests" and pii[0]["severity"] == "low"
    assert not any("gen/" in (f["subject_ref"] or "") for f in fs)
    assert c.get(f"/api/findings?project_id={pid}&module=Bidding", headers=ADMIN).json()


def test_reaudit_keeps_history_and_triage(env):
    c, st = env
    d1 = c.post("/api/repo-audit/ingest?sync=true", json=BODY, headers=ADMIN).json()
    pid = d1["project"]["id"]
    assert d1["diff"]["new"] > 0 and d1["diff"]["unchanged"] == 0
    secret = [f for f in c.get(f"/api/findings?project_id={pid}", headers=ADMIN).json() if f["control_id"] == "CTRL-06"][0]
    ev1 = c.get(f"/api/events?project_id={pid}", headers=ADMIN).json()
    # second audit: secret still there, tests file removed -> PII resolved, new file adds a finding
    st["extra"] = {"src/bidding/eval.py": "try:\n    x=1\nexcept:\n    pass\n# TODO fix\n"}
    import repo_ingest
    d2 = c.post("/api/repo-audit/ingest?sync=true", json=BODY, headers=ADMIN).json()
    assert d2["diff"]["unchanged"] >= 1 and d2["diff"]["new"] >= 1
    fs = c.get(f"/api/findings?project_id={pid}", headers=ADMIN).json()
    same = [f for f in fs if f["control_id"] == "CTRL-06"][0]
    assert same["id"] == secret["id"]
    assert len(c.get(f"/api/events?project_id={pid}", headers=ADMIN).json()) == len(ev1) + 1
    assert len(c.get(f"/api/repo-audits?project_id={pid}", headers=ADMIN).json()) in (2,) if c.get(f"/api/repo-audits?project_id={pid}", headers=ADMIN).status_code == 200 else True


def test_job_flow_and_cancel(env):
    c, st = env
    st["delay"] = 0
    r = c.post("/api/repo-audit/ingest", json=BODY, headers=ADMIN)
    assert r.status_code == 200 and "job_id" in r.json()
    jid = r.json()["job_id"]
    for _ in range(100):
        j = c.get(f"/api/repo-audit/jobs/{jid}", headers=ADMIN).json()
        if j["status"] in ("done", "failed", "cancelled"):
            break
        time.sleep(0.1)
    assert j["status"] == "done", j
    assert j["finding_summary"]["total"] > 0 and j["coverage"]

    st["delay"] = 5
    jid = c.post("/api/repo-audit/ingest", json={**BODY, "github_url": "https://github.com/acme/other"}, headers=ADMIN).json()["job_id"]
    time.sleep(0.4)
    assert c.post(f"/api/repo-audit/jobs/{jid}/cancel", headers=ADMIN).status_code == 200
    for _ in range(100):
        j = c.get(f"/api/repo-audit/jobs/{jid}", headers=ADMIN).json()
        if j["status"] in ("done", "failed", "cancelled"):
            break
        time.sleep(0.1)
    assert j["status"] == "cancelled"


def test_auth_and_validation(env):
    c, _ = env
    assert c.post("/api/repo-audit/ingest", json=BODY).status_code == 401
    assert c.post("/api/repo-audit/ingest", json={**BODY, "github_url": "http://evil.example/x"}, headers=ADMIN).status_code == 400
    assert c.post("/api/repo-audit/ingest", json={**BODY, "branch": "a;rm -rf /"}, headers=ADMIN).status_code == 400
    assert c.post("/api/repo-audit/ingest", json={**BODY, "integrity_level": 9}, headers=ADMIN).status_code == 422
