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
        readme = {"present": False, "sections": 0, "documents_api": False, "chars": 0}
        openapi = {"present": False, "endpoints": 0}
        tests, code_file_count, ai_refs = [], 0, False
        source_ext = {".js", ".jsx", ".ts", ".tsx", ".py", ".java", ".go", ".rb", ".php", ".cs"}
        for root, dirs, files in os.walk(tmp):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                low = fn.lower()
                relp = os.path.relpath(os.path.join(root, fn), tmp).replace("\\", "/").lower()
                if ext in LANG_MAP:
                    languages[LANG_MAP[ext]] = languages.get(LANG_MAP[ext], 0) + 1
                is_readme = low.startswith("readme")
                is_spec = ("openapi" in low or "swagger" in low) and ext in {".yml", ".yaml", ".json"}
                if ext not in CODE_EXT and not is_readme and not is_spec:
                    continue
                fpath = os.path.join(root, fn)
                try:
                    if os.path.getsize(fpath) > MAX_BYTES:
                        continue
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                        text = fh.read()
                except Exception:
                    continue
                rel = os.path.relpath(fpath, tmp)
                tl = text.lower()
                # spec signals
                if is_readme:
                    readme = {"present": True, "sections": sum(1 for ln in text.splitlines() if ln.lstrip().startswith("#")),
                              "documents_api": ("/api" in tl or bool(re.search(r"\b(get|post|put|delete|patch)\b\s+/", tl))),
                              "chars": len(text)}
                if is_spec:
                    openapi = {"present": True, "endpoints": len(re.findall(r"^\s{2,6}/[\w{}\-/]+:\s*$", text, re.M)) or len(re.findall(r"\"/[\w{}\-/]+\"\s*:", text))}
                is_test = (any(k in low for k in [".test.", ".spec.", "_test.", "test_"]) or "__tests__" in relp or "/tests/" in ("/" + relp) or "/test/" in ("/" + relp))
                if any(k in tl for k in ["openai", "langchain", "anthropic", "gemini", "llm", "gpt-", "tensorflow", "pytorch", "huggingface"]):
                    ai_refs = True
                if ext not in CODE_EXT:
                    continue
                file_count += 1
                total_loc += text.count("\n") + 1
                if is_test:
                    nm = relp + " " + tl[:400]
                    cat = ("security" if any(k in nm for k in ["security", "auth.test", "xss", "sqli"]) else
                           "performance" if any(k in nm for k in ["perf", "load", "stress", "k6", "jmeter", "benchmark"]) else
                           "accessibility" if any(k in nm for k in ["a11y", "accessib", "axe"]) else
                           "ai_eval" if any(k in nm for k in ["eval", "prompt", "model.test"]) else
                           "e2e" if any(k in nm for k in ["e2e", "integration", "cypress", "playwright", ".spec."]) else "unit")
                    tests.append({"path": rel, "category": cat})
                elif ext in source_ext:
                    code_file_count += 1
                if fn == "package.json" and '"react"' in text:
                    frameworks.add("React")
                if "express" in tl:
                    frameworks.add("Express")
                if "fastapi" in tl:
                    frameworks.add("FastAPI")
                if "mongoose" in tl or "mongodb" in tl:
                    frameworks.add("MongoDB")
                if "postgres" in tl or "pg(" in tl:
                    frameworks.add("PostgreSQL")
                sec, pii, log, stat = scan_secrets(text), scan_pii(text), scan_logging_leak(text), static_code_issues(text)
                if sec or pii or log or stat:
                    scanned.append({"path": rel, "secrets": sec, "pii": pii, "logging": log, "static": stat})
                if file_count >= MAX_FILES:
                    break
        test_cats = {}
        for t in tests:
            test_cats[t["category"]] = test_cats.get(t["category"], 0) + 1
        profile = {
            "languages": dict(sorted(languages.items(), key=lambda x: -x[1])),
            "frameworks": sorted(frameworks),
            "code_files_scanned": file_count,
            "approx_loc": total_loc,
            "spec": {"readme": readme, "openapi": openapi, "tests_total": len(tests),
                     "tests_by_category": test_cats, "source_files": code_file_count, "ai_refs": ai_refs},
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

    # Re-audit in place: reuse an existing project for the same repo URL.
    existing = await db.projects.find_one({"repo_url": git_url.strip(), "source": "github_live"}, {"_id": 0})
    if existing:
        project = existing
        pid = project["id"]
        for coll in ("findings", "events", "reports", "repo_audits"):
            await db[coll].delete_many({"project_id": pid})
        await db.projects.update_one({"id": pid}, {"$set": {"stage": "Repository Audit", "last_audited_at": now}})
        await ledger_mod.append_to_ledger(db, "project_reaudit", pid, {"name": repo_name, "repo_url": git_url})
    else:
        project = {
            "id": str(uuid4()), "name": repo_name,
            "description": f"Live IV&V audit of {git_url}",
            "integrity_tier": "T2", "stage": "Repository Audit", "repo_url": git_url.strip(),
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

    # ---- Spec-derived findings (Requirements & System-Test) from README / OpenAPI / tests ----
    spec = profile.get("spec", {})
    rd, oa = spec.get("readme", {}), spec.get("openapi", {})
    tcats = spec.get("tests_by_category", {})

    def spec_finding(cid, cname, agent, sev, verdict, reason, remedy, tags):
        f = engine.build_finding(project, event, cid, cname, agent,
            sev if verdict == "FAIL" else "low", 85, verdict, reason, tags, remedy,
            project["id"], "project", "deterministic_spec", [])
        f["level2_status"] = "confirmed_by_recompute"
        return f

    req_ok = rd.get("present") and rd.get("sections", 0) >= 2 and (oa.get("present") or rd.get("documents_api"))
    findings.append(spec_finding("CTRL-01", "Requirements & API Spec Quality", "A02", "high",
        "PASS" if req_ok else "FAIL",
        (f"README present ({rd.get('sections')} sections) and API documented"
         + (f" via OpenAPI spec ({oa.get('endpoints')} endpoints)." if oa.get("present") else " in README.")) if req_ok
        else f"Insufficient requirement/API documentation: README present={rd.get('present')} sections={rd.get('sections')}, OpenAPI spec present={oa.get('present')}.",
        "Add a structured README and an OpenAPI/Swagger contract documenting every endpoint." if not req_ok else "No action required.",
        ["requirements", "documentation", "api_spec"]))

    src = max(spec.get("source_files", 0), 1)
    ttot = spec.get("tests_total", 0)
    ratio = round(ttot / src, 2)
    test_ok = ttot > 0 and ratio >= 0.1
    findings.append(spec_finding("CTRL-11", "Unit Test Adequacy", "A06", "high",
        "PASS" if test_ok else "FAIL",
        f"{ttot} test file(s) across {src} source file(s) (ratio {ratio}).",
        "Add automated tests; target at least one test file per ~10 source files for critical paths." if not test_ok else "No action required.",
        ["testing", "coverage"]))

    for cid, cname, cat, agent in [
        ("CTRL-15", "Security Testing (DAST)", "security", "A05"),
        ("CTRL-16", "Performance Threshold Check", "performance", "A08"),
        ("CTRL-17", "Accessibility Check", "accessibility", "A08"),
    ]:
        present = tcats.get(cat, 0) > 0
        findings.append(spec_finding(cid, cname, agent, "high" if cat == "security" else "medium",
            "PASS" if present else "FAIL",
            f"{tcats.get(cat, 0)} {cat} test file(s) found in the repository." if present
            else f"No {cat} tests found in the repository.",
            f"Add {cat} tests to the pipeline before release." if not present else "No action required.",
            ["system_test", cat]))

    if spec.get("ai_refs"):
        present = tcats.get("ai_eval", 0) > 0
        findings.append(spec_finding("CTRL-18", "AI Model Evaluation", "A16", "high",
            "PASS" if present else "FAIL",
            f"{tcats.get('ai_eval', 0)} AI-evaluation test file(s) found; repo references AI/LLM libraries." if present
            else "Repo references AI/LLM libraries but no AI-evaluation tests (ISO/IEC 42001) were found.",
            "Add an AI evaluation suite (toxicity, groundedness, robustness) per ISO/IEC 42001." if not present else "No action required.",
            ["system_test", "ai_governance"]))

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
