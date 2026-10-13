"""Backend tests: auth bearer tokens, segregation, admin gating, ledger integrity,
   evidence pack downloads. Covers iteration_5 review request.
"""
import os
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")

ADMIN_TOKEN = "gov-demo-u-ramesh-token-2026"
NON_ADMIN_TOKEN = "gov-demo-u-rohit-token-2026"
PRIYA_TOKEN = "gov-demo-u-priya-token-2026"
NEHA_TOKEN = "gov-demo-u-neha-token-2026"


def H(tok, role=None):
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    if role:
        h["X-Acting-Role"] = role
    return h


# ----- users / auth -----
class TestAuthUsers:
    def test_eight_seeded_users(self):
        r = requests.get(f"{BASE}/api/auth/users")
        assert r.status_code == 200
        users = r.json()
        assert len(users) == 8
        emails = {u["email"] for u in users}
        assert "mishraramesh@gmail.com" in emails
        ids = {u["id"] for u in users}
        assert "u-ramesh" in ids

    def test_me_with_admin_token(self):
        r = requests.get(f"{BASE}/api/auth/me", headers=H(ADMIN_TOKEN))
        assert r.status_code == 200
        d = r.json()
        assert d["user"]["id"] == "u-ramesh"


# ----- admin gating -----
class TestAdmin:
    def test_admin_users_forbidden_for_non_admin(self):
        r = requests.get(f"{BASE}/api/admin/users", headers=H(NON_ADMIN_TOKEN))
        assert r.status_code == 403

    def test_admin_users_ok_for_admin(self):
        r = requests.get(f"{BASE}/api/admin/users", headers=H(ADMIN_TOKEN))
        assert r.status_code == 200
        d = r.json()
        assert "users" in d and isinstance(d["users"], list)
        assert len(d["users"]) == 8

    def test_token_issue_me_revoke_cycle(self):
        # issue
        payload = {"user_id": "u-neha", "label": "TEST_pytest_token"}
        r = requests.post(f"{BASE}/api/admin/tokens", headers=H(ADMIN_TOKEN), json=payload)
        assert r.status_code in (200, 201), r.text
        d = r.json()
        tok = d.get("token") or d.get("plain_token") or d.get("value")
        tok_id = d.get("id") or d.get("token_id")
        assert tok and tok_id, d
        # authenticate with it
        r2 = requests.get(f"{BASE}/api/auth/me", headers=H(tok))
        assert r2.status_code == 200
        assert r2.json()["user"]["id"] == "u-neha"
        # revoke
        r3 = requests.post(f"{BASE}/api/admin/tokens/{tok_id}/revoke", headers=H(ADMIN_TOKEN))
        assert r3.status_code in (200, 204)
        # should now 401
        r4 = requests.get(f"{BASE}/api/auth/me", headers=H(tok))
        assert r4.status_code == 401

    def test_rebuild_requires_admin(self):
        r = requests.post(f"{BASE}/api/ledger/rebuild", headers=H(NON_ADMIN_TOKEN))
        assert r.status_code == 403


# ----- ledger -----
class TestLedger:
    def test_verify_valid(self):
        r = requests.get(f"{BASE}/api/ledger/verify")
        assert r.status_code == 200
        assert r.json()["valid"] is True


# ----- helpers for findings/segregation -----
def _get_projects():
    return requests.get(f"{BASE}/api/projects").json()


def _findings(pid, control_id=None):
    r = requests.get(f"{BASE}/api/findings", params={"project_id": pid})
    r.raise_for_status()
    items = r.json()
    if control_id:
        items = [f for f in items if f.get("control_id") == control_id]
    return items


# ----- segregation / triage auth -----
class TestTriageAuth:
    @classmethod
    def setup_class(cls):
        projects = _get_projects()
        cls.pid = projects[0]["id"]
        # CTRL-08 is Security & Privacy — Priya's role
        cls.ctrl08 = [f for f in _findings(cls.pid, "CTRL-08") if f.get("status") == "open"]
        # CTRL-06 handled by another role (Dev), used for wrong-role test with Priya
        cls.ctrl06 = [f for f in _findings(cls.pid, "CTRL-06") if f.get("status") == "open"]
        assert cls.ctrl08 and cls.ctrl06

    def test_401_without_token(self):
        fid = self.ctrl08[0]["id"]
        r = requests.post(f"{BASE}/api/findings/{fid}/triage",
                          json={"decision": "accept", "role": "Security & Privacy Lead"})
        assert r.status_code == 401

    def test_403_wrong_role(self):
        # Rohit (only Developer) acts as Security & Privacy Lead → 403 role-not-assigned
        fid = self.ctrl08[0]["id"]
        r = requests.post(f"{BASE}/api/findings/{fid}/triage",
                          headers=H(NON_ADMIN_TOKEN),
                          json={"decision": "accept", "role": "Security & Privacy Lead",
                                "reason": "TEST wrong role"})
        assert r.status_code == 403, r.text

    def test_segregation_and_success(self):
        seg_hits, ok_hits = 0, 0
        last_err = None
        for f in self.ctrl08[:20]:
            r = requests.post(f"{BASE}/api/findings/{f['id']}/triage",
                              headers=H(PRIYA_TOKEN),
                              json={"decision": "dismiss", "role": "Security & Privacy Lead",
                                    "reason": "TEST_pytest segregation probe"})
            if r.status_code == 200:
                ok_hits += 1
            elif r.status_code == 403:
                seg_hits += 1
                last_err = r.text
            else:
                last_err = f"{r.status_code} {r.text}"
        assert ok_hits >= 1, f"No successful triage; last={last_err}"
        print(f"triage results: ok={ok_hits} segregation_403={seg_hits}")

    def test_dismiss_requires_reason(self):
        f = self.ctrl08[0]
        r = requests.post(f"{BASE}/api/findings/{f['id']}/triage",
                          headers=H(PRIYA_TOKEN),
                          json={"decision": "dismiss", "role": "Security & Privacy Lead"})
        assert r.status_code in (400, 422, 403), r.text

    def test_ledger_still_valid_after_writes(self):
        r = requests.get(f"{BASE}/api/ledger/verify")
        assert r.status_code == 200
        assert r.json()["valid"] is True


# ----- evidence pack -----
class TestEvidencePack:
    @classmethod
    def setup_class(cls):
        cls.pid = _get_projects()[0]["id"]

    def test_pdf(self):
        r = requests.get(f"{BASE}/api/repo-audit/{self.pid}/evidence-pack",
                         params={"format": "pdf"})
        assert r.status_code == 200, r.text[:200]
        assert "application/pdf" in r.headers.get("content-type", "")
        assert r.content[:4] == b"%PDF"
        assert "attachment" in r.headers.get("content-disposition", "").lower()

    def test_docx(self):
        r = requests.get(f"{BASE}/api/repo-audit/{self.pid}/evidence-pack",
                         params={"format": "docx"})
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "officedocument" in ct or "docx" in ct
        # DOCX is a zip
        assert r.content[:2] == b"PK"
        assert "attachment" in r.headers.get("content-disposition", "").lower()


# ----- assignments update -----
class TestAssignments:
    def test_put_assignments(self):
        projects = _get_projects()
        pid = projects[0]["id"]
        payload = {"user_id": "u-neha", "project_id": pid, "roles": ["IV&V Lead"]}
        r = requests.put(f"{BASE}/api/admin/assignments",
                         headers=H(ADMIN_TOKEN), json=payload)
        assert r.status_code in (200, 204), r.text
