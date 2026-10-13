import csv
import io
from conftest import ADMIN

CSV_OK = """name,email,team,roles
Anil Kumar,anil@corp.test,Bidding,Developer
Sunita Rao,sunita@corp.test,Evaluation;Platform,Developer;Tech Lead
Mohan Das,mohan@corp.test,Tendering,Quality Lead
"""


def test_admin_required(client):
    assert client.post("/api/admin/users", json={"name": "x", "email": "x@y.zz"}).status_code == 401


def test_create_user_and_duplicate(client):
    r = client.post("/api/admin/users", headers=ADMIN, json={"name": "Anil", "email": "anil@corp.test", "teams": ["Bidding"], "roles": ["Developer"]})
    assert r.status_code == 201 and r.json()["id"].startswith("u-anil")
    assert client.post("/api/admin/users", headers=ADMIN, json={"name": "Anil2", "email": "ANIL@corp.test"}).status_code == 409
    assert client.post("/api/admin/users", headers=ADMIN, json={"name": "B", "email": "bad"}).status_code == 422
    assert client.post("/api/admin/users", headers=ADMIN, json={"name": "B", "email": "b@c.dd", "roles": ["God"]}).status_code == 422


def test_csv_preview_and_commit(client):
    p = client.post("/api/admin/users/import/preview", headers=ADMIN, json={"csv_text": CSV_OK}).json()
    assert p["ok"] == 3 and p["errors"] == 0
    assert p["rows"][1]["teams"] == ["Evaluation", "Platform"] and p["rows"][1]["roles"] == ["Developer", "Tech Lead"]
    c = client.post("/api/admin/users/import/commit", headers=ADMIN, json={"csv_text": CSV_OK}).json()
    assert len(c["created"]) == 3
    # importing again now fails on existing emails
    p2 = client.post("/api/admin/users/import/preview", headers=ADMIN, json={"csv_text": CSV_OK}).json()
    assert p2["errors"] == 3
    r = client.post("/api/admin/users/import/commit", headers=ADMIN, json={"csv_text": CSV_OK})
    assert r.status_code == 422
    teams = {t["name"]: t["members"] for t in client.get("/api/admin/teams", headers=ADMIN).json()}
    assert teams["Bidding"] == 1 and teams["Platform"] == 1


def test_csv_errors_and_skip(client):
    bad = "name,email,team,roles\nA,a@x.zz,T,Developer\nB,notanemail,T,Developer\nC,c@x.zz,T,Wizard\nD,a@x.zz,T,\n"
    p = client.post("/api/admin/users/import/preview", headers=ADMIN, json={"csv_text": bad}).json()
    assert p["ok"] == 1 and p["errors"] == 3
    c = client.post("/api/admin/users/import/commit", headers=ADMIN, json={"csv_text": bad, "skip_errors": True}).json()
    assert len(c["created"]) == 1 and c["skipped"] == 3
    assert client.post("/api/admin/users/import/preview", headers=ADMIN, json={"csv_text": "foo,bar\n1,2"}).status_code == 422


def test_thirty_users_pagination_search_and_bulk_tokens(client):
    lines = ["name,email,team,roles"] + [f"User {i:02d},user{i:02d}@corp.test,{'Bidding' if i%2 else 'Tendering'},Developer" for i in range(30)]
    c = client.post("/api/admin/users/import/commit", headers=ADMIN, json={"csv_text": "\n".join(lines)}).json()
    assert len(c["created"]) == 30
    page = client.get("/api/admin/people", headers=ADMIN, params={"page_size": 10, "page": 2}).json()
    assert page["total"] == 31 and len(page["users"]) == 10
    assert client.get("/api/admin/people", headers=ADMIN, params={"q": "user07"}).json()["total"] == 1
    assert client.get("/api/admin/people", headers=ADMIN, params={"team": "Bidding"}).json()["total"] == 15
    b = client.post("/api/admin/tokens/bulk", headers=ADMIN, json={}).json()
    assert b["issued"] == 30   # owner already has a token
    rows = list(csv.DictReader(io.StringIO(b["csv"])))
    tok = rows[0]["token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert me.status_code == 200
    assert client.post("/api/admin/tokens/bulk", headers=ADMIN, json={}).json()["issued"] == 0


def test_deactivate_revokes_tokens(client):
    u = client.post("/api/admin/users", headers=ADMIN, json={"name": "Z", "email": "z@corp.test", "roles": ["Developer"]}).json()
    tok = client.post("/api/admin/tokens", headers=ADMIN, json={"user_id": u["id"]}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/auth/me", headers=h).status_code == 200
    r = client.patch(f"/api/admin/users/{u['id']}", headers=ADMIN, json={"active": False})
    assert r.json()["tokens_revoked"] == 1
    assert client.get("/api/auth/me", headers=h).status_code == 401
    assert client.patch("/api/admin/users/u-ramesh", headers=ADMIN, json={"active": False}).status_code == 422


def test_non_admin_cannot_manage_people(demo_client):
    t = demo_client.post("/api/auth/demo-login", json={"user_id": "u-rohit"}).json()["token"]
    h = {"Authorization": f"Bearer {t}"}
    assert demo_client.post("/api/admin/users", headers=h, json={"name": "x", "email": "x@y.zz"}).status_code == 403
    assert demo_client.get("/api/admin/people", headers=h).status_code == 403


def test_team_assignment_and_alias_segregation(demo_client):
    t = demo_client.post("/api/auth/demo-login", json={"user_id": "u-ramesh"}).json()["token"]
    h = {"Authorization": f"Bearer {t}"}
    pid = demo_client.get("/api/projects", headers=h).json()[0]["id"]
    u = demo_client.post("/api/admin/users", headers=h, json={"name": "Anil", "email": "anil@corp.test", "teams": ["Bidding"], "roles": []}).json()
    r = demo_client.put("/api/admin/team-assignments", headers=h, json={"team": "Bidding", "project_id": pid, "roles": ["Developer"]})
    assert r.json()["users_updated"] == 1
    a = demo_client.post("/api/admin/aliases", headers=h, json={"alias": "anil.k", "user_id": u["id"]})
    assert a.status_code == 201
    assert any(x["alias"] == "anil.k" for x in demo_client.get("/api/admin/aliases", headers=h).json())
