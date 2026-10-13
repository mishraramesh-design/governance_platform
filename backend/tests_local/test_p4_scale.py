import asyncio
import pytest
from conftest import ADMIN, make_client


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_ledger_chains_per_project_and_verify(demo_client):
    import ledger, database
    c = demo_client
    h = ADMIN
    t = c.post("/api/auth/demo-login", json={"user_id": "u-ramesh"}).json()["token"]
    h = {"Authorization": f"Bearer {t}"}
    chains = c.get("/api/ledger/chains", headers=h).json()
    names = {x["chain"] for x in chains}
    assert "_global" in names and len(names) >= 2           # global plus at least one project
    assert c.get("/api/ledger/verify", headers=h).json()["valid"] is True
    pid = [n for n in names if n != "_global"][0]
    v = c.get("/api/ledger/verify", headers=h, params={"project_id": pid}).json()
    assert v["valid"] is True and v["chain"] == pid


def test_ledger_tamper_is_detected(demo_client):
    import database
    t = demo_client.post("/api/auth/demo-login", json={"user_id": "u-ramesh"}).json()["token"]
    h = {"Authorization": f"Bearer {t}"}
    chains = [x["chain"] for x in demo_client.get("/api/ledger/chains", headers=h).json() if x["chain"] != "_global"]
    pid = chains[0]
    loop = asyncio.new_event_loop()
    doc = loop.run_until_complete(database.db.ledger.find_one({"chain": pid, "seq": 2}))
    loop.run_until_complete(database.db.ledger.update_one({"_id": doc["_id"]}, {"$set": {"payload_summary": {"tampered": True}}}))
    v = demo_client.get("/api/ledger/verify", headers=h, params={"project_id": pid}).json()
    assert v["valid"] is False and v["broken_at_seq"] == 2


def test_concurrent_appends_do_not_fork(demo_client):
    import database, ledger
    loop = asyncio.new_event_loop()

    async def go():
        await asyncio.gather(*[ledger.append_to_ledger(database.db, "test", f"r{i}", {"project_id": "pX", "i": i}) for i in range(40)])
        return await ledger.verify_chain(database.db, "pX")

    res = loop.run_until_complete(go())
    assert res["valid"] and res["total_entries"] == 40


def test_findings_pagination_and_totals(demo_client):
    import database
    t = demo_client.post("/api/auth/demo-login", json={"user_id": "u-ramesh"}).json()["token"]
    h = {"Authorization": f"Bearer {t}"}
    pid = demo_client.get("/api/projects", headers=h).json()[0]["id"]
    loop = asyncio.new_event_loop()
    docs = [{"id": f"bulk-{i}", "project_id": pid, "control_id": "CTRL-06", "control_name": "Secrets Detection", "severity": "high",
             "verdict": "FAIL", "status": "open", "reason": f"bulk finding {i}", "subject_ref": f"f{i}.py",
             "created_at": f"2026-01-01T00:00:{i % 60:02d}Z"} for i in range(2500)]
    loop.run_until_complete(database.db.findings.insert_many(docs))
    r = demo_client.get("/api/findings", headers=h, params={"project_id": pid, "page_size": 1000})
    base = int(r.headers["X-Total-Count"])
    assert base >= 2500 and len(r.json()) == 1000
    r3 = demo_client.get("/api/findings", headers=h, params={"project_id": pid, "page_size": 1000, "page": 3})
    assert len(r3.json()) == min(1000, base - 2000)
    s = demo_client.get("/api/findings", headers=h, params={"project_id": pid, "search": "bulk finding 77"})
    assert int(s.headers["X-Total-Count"]) >= 1
    d = demo_client.get("/api/dashboard", headers=h, params={"project_id": pid}).json()
    assert d["total_findings"] == base and sum(d["severity_counts"].values()) == base
