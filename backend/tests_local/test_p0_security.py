import pytest
from conftest import ADMIN

WRITE_ENDPOINTS = [
    ("PUT", "/api/harness/config", {"capability_profiles": {}, "zero_llm_mode": True}),
    ("POST", "/api/harness/sandbox", {"agent_id": "A02", "level": 1, "masked_input": "x"}),
    ("POST", "/api/mlops/registry/none/evaluate", None),
    ("POST", "/api/mlops/registry/none/promote", None),
    ("POST", "/api/mlops/registry/none/shadow", None),
    ("POST", "/api/mlops/registry/none/shadow-compare", None),
    ("POST", "/api/runtime/analyze", {"project_id": "p", "log_text": "x"}),
    ("POST", "/api/repo-audit/simulate", {"project_id": "p", "github_url": "https://github.com/a/b"}),
    ("POST", "/api/artifacts/generate", {"project_id": "p", "artifact_type": "metrics_summary"}),
    ("POST", "/api/events/simulate", {"project_id": "p", "event_type": "commit_pushed", "role": "Developer"}),
]


@pytest.mark.parametrize("method,path,body", WRITE_ENDPOINTS)
def test_writes_require_token(client, method, path, body):
    r = client.request(method, path, json=body)
    assert r.status_code == 401, (path, r.status_code, r.text[:200])


def test_reads_require_token_when_not_demo(client):
    assert client.get("/api/findings", params={"project_id": "x"}).status_code == 401
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/ledger").status_code == 401


def test_demo_login_disabled_by_default(client):
    r = client.post("/api/auth/demo-login", json={"user_id": "u-ramesh"})
    assert r.status_code == 403
    assert client.get("/api/auth/config").json() == {"demo_mode": False}


def test_demo_login_works_only_in_demo_mode(demo_client):
    assert demo_client.get("/api/auth/config").json() == {"demo_mode": True}
    r = demo_client.post("/api/auth/demo-login", json={"user_id": "u-ramesh"})
    assert r.status_code == 200 and r.json()["token"]


def test_no_deterministic_tokens(client):
    # the old guessable token must not work
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer gov-demo-u-ramesh-token-2026"})
    assert r.status_code == 401


def test_bootstrap_admin_token_works(client):
    r = client.get("/api/auth/me", headers=ADMIN)
    assert r.status_code == 200 and r.json()["user"]["id"] == "u-ramesh"


def test_governance_endpoints_forbidden_for_non_governance_user(demo_client):
    t = demo_client.post("/api/auth/demo-login", json={"user_id": "u-rohit"}).json()["token"]
    h = {"Authorization": f"Bearer {t}"}
    assert demo_client.put("/api/harness/config", headers=h, json={"capability_profiles": {}, "zero_llm_mode": True}).status_code == 403


def test_cors_not_wildcard(client):
    r = client.options("/api/", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") != "*"
    assert r.headers.get("access-control-allow-origin") != "https://evil.example"
