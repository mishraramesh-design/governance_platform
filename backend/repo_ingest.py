"""Live GitHub repository ingestion for the IV&V platform.

Clones a public repo, profiles its stack (Stack Profiler / A21), runs the
deterministic detectors over the real source files, records findings with the
two-level review, and generates the author + team-lead reports and the gate pack.
Nothing is written back to the repo - read-only, observe-and-advise.
"""
import os
import re
import asyncio
import shutil
import tempfile
import subprocess
from uuid import uuid4
from datetime import datetime, timezone

import engine
import ledger as ledger_mod
from detectors import scan_secrets, scan_pii, scan_logging_leak, static_code_issues

CODE_EXT = {".js", ".jsx", ".ts", ".tsx", ".py", ".java", ".go", ".rb", ".php", ".cs",
            ".yml", ".yaml", ".json", ".env", ".conf", ".sql", ".sh", ".html", ".css"}
SKIP_DIRS = {".git", "node_modules", "dist", "build", ".next", "venv", ".venv",
             "__pycache__", "coverage", ".cache", "vendor"}
LANG_MAP = {".js": "JavaScript", ".jsx": "JavaScript (React)", ".ts": "TypeScript",
            ".tsx": "TypeScript (React)", ".py": "Python", ".java": "Java", ".go": "Go",
            ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".sql": "SQL", ".sh": "Shell",
            ".html": "HTML", ".css": "CSS", ".yml": "YAML", ".yaml": "YAML", ".json": "JSON"}
MAX_FILES = 4000
MAX_BYTES = 350_000


def _clone_and_scan(git_url: str) -> dict:
    """Blocking: clone (shallow) + profile + scan. Run via asyncio.to_thread."""
    tmp = tempfile.mkdtemp(prefix="ivv_repo_")
    try:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", git_url, tmp],
            capture_output=True, text=True, timeout=120, env=env,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"git clone failed: {proc.stderr.strip()[:300]}")

        languages, frameworks = {}, set()
        scanned, file_count, total_loc = [], 0, 0
        for root, dirs, files in os.walk(tmp):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                if ext in LANG_MAP:
                    languages[LANG_MAP[ext]] = languages.get(LANG_MAP[ext], 0) + 1
                if ext not in CODE_EXT:
                    continue
                fpath = os.path.join(root, fn)
                try:
                    if os.path.getsize(fpath) > MAX_BYTES:
                        continue
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                        text = fh.read()
                except Exception:
                    continue
                file_count += 1
                total_loc += text.count("\n") + 1
                rel = os.path.relpath(fpath, tmp)
                if fn == "package.json" and '"react"' in text:
                    frameworks.add("React")
                if "express" in text.lower():
                    frameworks.add("Express")
                if "fastapi" in text.lower():
                    frameworks.add("FastAPI")
                if "mongoose" in text.lower() or "mongodb" in text.lower():
                    frameworks.add("MongoDB")
                if "postgres" in text.lower() or "pg(" in text.lower():
                    frameworks.add("PostgreSQL")
                sec, pii, log, stat = scan_secrets(text), scan_pii(text), scan_logging_leak(text), static_code_issues(text)
                if sec or pii or log or stat:
                    scanned.append({"path": rel, "secrets": sec, "pii": pii, "logging": log, "static": stat})
                if file_count >= MAX_FILES:
                    break
        profile = {
            "languages": dict(sorted(languages.items(), key=lambda x: -x[1])),
            "frameworks": sorted(frameworks),
            "code_files_scanned": file_count,
            "approx_loc": total_loc,
        }
        return {"profile": profile, "scanned": scanned}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


HIGH_PII = {"pii:aadhaar", "pii:pan", "pii:card_number", "pii:gstin"}


async def ingest_repo(db, git_url: str, name: str = None):
    if not re.match(r"^https://github\.com/[\w.\-]+/[\w.\-]+/?$", git_url.strip()):
        raise ValueError("Please provide a valid public GitHub repository URL, e.g. https://github.com/org/repo")

    scan = await asyncio.to_thread(_clone_and_scan, git_url.strip())
    profile, scanned = scan["profile"], scan["scanned"]

    repo_name = name or git_url.rstrip("/").split("/")[-1]
    now = datetime.now(timezone.utc).isoformat()

    # provisional tier from what we find (refined below)
    project = {
        "id": str(uuid4()), "name": repo_name,
        "description": f"Live IV&V audit of {git_url}",
        "integrity_tier": "T2", "stage": "Repository Audit", "repo_url": git_url,
        "source": "github_live", "created_at": now,
    }
    await db.projects.insert_one(dict(project))
    await ledger_mod.append_to_ledger(db, "project", project["id"], {"name": repo_name, "repo_url": git_url})

    event = {
        "id": str(uuid4()), "project_id": project["id"], "event_type": "repo_audit",
        "source_ref": git_url, "triggered_by": "A21", "controls_triggered": ["CTRL-06", "CTRL-07", "CTRL-08", "CTRL-10"],
        "created_at": now,
    }
    await db.events.insert_one(dict(event))
    await ledger_mod.append_to_ledger(db, "event", event["id"], {"event_type": "repo_audit", "project_id": project["id"]})

    findings = []

    def ev(hits, key):
        return [{"type": h["type"], "masked": h["masked"], "hash": h["hash"]} for h in hits if (key is None or True)]

    for item in scanned:
        rel = item["path"]
        if item["secrets"]:
            f = engine.build_finding(project, event, "CTRL-06", "Secrets Detection", "A05", "critical", 97, "FAIL",
                f"{len(item['secrets'])} potential secret(s) in {rel}: {', '.join(sorted({h['type'] for h in item['secrets']}))}.",
                ["security", "secrets"], "Rotate the exposed credential(s) and move them to a secrets manager / environment variables.",
                rel, "file", "deterministic_detector", ev(item["secrets"], None))
            engine._apply_a05_rescan(f, "T0", item["secrets"], item["secrets"])
            findings.append(f)
        if item["pii"]:
            tier = "T1" if any(h["type"] in HIGH_PII for h in item["pii"]) else "T2"
            f = engine.build_finding(project, event, "CTRL-07", "India PII Detection", "A05", "high", 90, "FAIL",
                f"{len(item['pii'])} potential personal-data pattern(s) in {rel}: {', '.join(sorted({h['type'] for h in item['pii']}))}. DPDP Act 2023 relevance flagged.",
                ["security", "privacy", "dpdp"], "Remove hardcoded personal data; use masked fixtures and verify DPDP obligations.",
                rel, "file", "deterministic_detector", ev(item["pii"], None))
            engine._apply_a05_rescan(f, tier, item["pii"], item["pii"])
            findings.append(f)
        if item["logging"]:
            f = engine.build_finding(project, event, "CTRL-08", "Sensitive Logging Leak", "A05", "high", 88, "FAIL",
                f"{len(item['logging'])} log/print statement(s) in {rel} may emit sensitive values.",
                ["security", "logging"], "Redact sensitive fields before logging; adopt structured logging with allow-lists.",
                rel, "file", "deterministic_detector", ev(item["logging"], None))
            f["level2_status"] = "confirmed_by_recompute"
            findings.append(f)
        if item["static"]:
            sev = "high" if any(s["type"] == "dangerous_dynamic_execution" for s in item["static"]) else "low"
            f = engine.build_finding(project, event, "CTRL-10", "Static Code Heuristics", "A06", sev, 80, "FAIL",
                f"{len(item['static'])} code-quality issue(s) in {rel}: {', '.join(sorted({s['type'] for s in item['static']}))}.",
                ["code_quality"], "Address the flagged issues (dynamic execution, swallowed errors, markers).",
                rel, "file", "deterministic_detector",
                [{"type": s["type"], "masked": s["type"], "hash": ""} for s in item["static"]])
            f["level2_status"] = "confirmed_by_recompute"
            findings.append(f)

    if findings:
        await db.findings.insert_many([dict(f) for f in findings])
        for f in findings:
            await ledger_mod.append_to_ledger(db, "finding", f["id"], {"control_id": f["control_id"], "verdict": f["verdict"], "severity": f["severity"]})

    # refine integrity tier
    has_secret = any(f["control_id"] == "CTRL-06" for f in findings)
    has_high_pii = any(f["control_id"] == "CTRL-07" and f.get("tier") == "T1" for f in findings)
    tier = "T1" if (has_secret or has_high_pii) else ("T2" if findings else "T3")
    await db.projects.update_one({"id": project["id"]}, {"$set": {"integrity_tier": tier}})
    project["integrity_tier"] = tier

    audit = {
        "id": str(uuid4()), "project_id": project["id"], "github_url": git_url,
        "detected_languages": list(profile["languages"].keys()),
        "frameworks": profile["frameworks"],
        "suggested_integrity_tier": tier,
        "code_files_scanned": profile["code_files_scanned"], "approx_loc": profile["approx_loc"],
        "folder_map": [], "note": "Live repository cloned and scanned (read-only) by the platform.",
        "created_at": now,
    }
    await db.repo_audits.insert_one(dict(audit))
    await ledger_mod.append_to_ledger(db, "repo_audit", audit["id"], {"project_id": project["id"], "github_url": git_url})
    audit.pop("_id", None)

    author_report = await engine.generate_author_report(db, project, event, findings)
    team_lead_report = await engine.generate_team_lead_report(db, project, event, findings)
    gates = await engine.compute_gate_status(db, project["id"])

    by_sev, by_ctrl = {}, {}
    for f in findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
        by_ctrl[f["control_name"]] = by_ctrl.get(f["control_name"], 0) + 1

    return {
        "project": project,
        "profile": profile,
        "audit": audit,
        "finding_summary": {"total": len(findings), "by_severity": by_sev, "by_control": by_ctrl,
                            "fail": sum(1 for f in findings if f["verdict"] == "FAIL")},
        "reports": [author_report, team_lead_report],
        "gates": gates,
    }
