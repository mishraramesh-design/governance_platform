"""Requirement 3: after a repo audit, NO raw detected value may appear anywhere in the
database (findings, reports, ledger, llm_calls, events, ...). Only masked fragments,
keyed (per-project) hashes, type, file and line are allowed to be persisted.

Runs the real `repo_ingest.ingest_repo` pipeline offline against a throwaway database:
the network clone is replaced by a crafted source blob that is scanned with the real
deterministic detectors (so masking/hashing is exercised exactly as in production).
"""
import os
import json
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

import detectors as D
import repo_ingest

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Source with known, checksum-valid sensitive values.
SRC = (
    'import boto3\n'
    'AWS_ACCESS_KEY = "AKIAABCDEFGHIJKLMNOP"\n'
    'password = "S3cr3tP@ssw0rd123"\n'
    'aadhaar = "234567890124"\n'
    'pan = "AAAPL1234C"\n'
    'card = "4111 1111 1111 1111"\n'
    'mobile = "9876543210"\n'
    'def login(user, pw):\n'
    '    logger.info("login user=%s password=%s", user, pw)\n'
)

# Every raw value (in each literal form) that MUST NOT be persisted anywhere.
RAW_VALUES = [
    "AKIAABCDEFGHIJKLMNOP",
    "S3cr3tP@ssw0rd123",
    "234567890124",
    "AAAPL1234C",
    "4111 1111 1111 1111",
    "4111111111111111",
    "9876543210",
]


def _fake_clone(git_url, token=None, key=None):
    """Offline stand-in for the git clone: scans SRC with the real detectors + project key."""
    sec = D.scan_secrets(SRC, key)
    pii = D.scan_pii(SRC, key)
    log = D.scan_logging_leak(SRC, key)
    stat = D.static_code_issues(SRC)
    profile = {
        "languages": {"Python": 1}, "frameworks": [],
        "code_files_scanned": 1, "approx_loc": SRC.count("\n") + 1,
        "spec": {"readme": {}, "openapi": {}, "tests_total": 0, "tests_by_category": {},
                 "source_files": 1, "ai_refs": False, "endpoints": [], "endpoint_count": 0,
                 "untested_endpoints": 0},
    }
    return {"profile": profile,
            "scanned": [{"path": "src/app.py", "secrets": sec, "pii": pii, "logging": log, "static": stat}]}


async def _run():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    dbname = os.environ["DB_NAME"] + "_rawleak_test"
    db = client[dbname]
    await client.drop_database(dbname)
    # Zero-LLM so report generation stays deterministic & offline (still writes llm_calls).
    await db.harness_config.update_one({"id": "default"},
                                       {"$set": {"id": "default", "zero_llm_mode": True}}, upsert=True)
    orig = repo_ingest._clone_and_scan
    repo_ingest._clone_and_scan = _fake_clone
    try:
        result = await repo_ingest.ingest_repo(db, "https://github.com/example/rawleak-demo")
        findings = await db.findings.find({}, {"_id": 0}).to_list(100000)

        leaks = []
        for cn in await db.list_collection_names():
            if cn == "project_keys":  # the key material itself is not a detected value
                continue
            docs = await db[cn].find({}, {"_id": 0}).to_list(100000)
            blob = json.dumps(docs, default=str)
            for raw in RAW_VALUES:
                if raw in blob:
                    leaks.append((cn, raw))
        return result, findings, leaks
    finally:
        repo_ingest._clone_and_scan = orig
        await client.drop_database(dbname)
        client.close()


def test_no_raw_detected_values_persisted():
    result, findings, leaks = asyncio.run(_run())

    # Sanity: the audit actually detected and stored something to scan.
    assert result["finding_summary"]["total"] > 0
    detector_findings = [f for f in findings if f.get("method") == "deterministic_detector"
                         and f.get("control_id") in ("CTRL-06", "CTRL-07", "CTRL-08")]
    assert detector_findings, "expected secret/PII/logging findings from the audit"

    # Every secret/PII/logging evidence item carries file + line (and no raw value / source line).
    for f in detector_findings:
        for item in f.get("evidence", []):
            assert "file" in item and item["file"], f"evidence missing file: {item}"
            assert item.get("line") is not None, f"evidence missing line: {item}"
            assert set(item.keys()) <= {"type", "masked", "hash", "severity", "file", "line", "col"}, \
                f"unexpected evidence field (possible raw leak): {item}"

    # The core invariant: no raw detected value anywhere in the database.
    assert leaks == [], f"RAW detected values leaked into DB: {leaks}"
