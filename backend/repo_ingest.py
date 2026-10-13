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
from detectors import scan_secrets, scan_pii, scan_logging_leak, static_code_issues, get_project_key

CODE_EXT = {".js", ".jsx", ".ts", ".tsx", ".py", ".java", ".go", ".rb", ".php", ".cs",
            ".yml", ".yaml", ".json", ".env", ".conf", ".sql", ".sh", ".html", ".css"}
SKIP_DIRS = {".git", "node_modules", "dist", "build", ".next", "venv", ".venv",
             "__pycache__", "coverage", ".cache", "vendor"}
LANG_MAP = {".js": "JavaScript", ".jsx": "JavaScript (React)", ".ts": "TypeScript",
            ".tsx": "TypeScript (React)", ".py": "Python", ".java": "Java", ".go": "Go",
            ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".sql": "SQL", ".sh": "Shell",
            ".html": "HTML", ".css": "CSS", ".yml": "YAML", ".yaml": "YAML", ".json": "JSON"}
MAX_FILES = int(os.environ.get("REPO_MAX_FILES", "20000"))
MAX_BYTES = int(os.environ.get("REPO_MAX_BYTES", "350000"))
CLONE_TIMEOUT = int(os.environ.get("REPO_CLONE_TIMEOUT", "600"))
BRANCH_RE = re.compile(r"^[\w./\-]{1,100}$")

EP_JS = re.compile(r"\b(?:app|router|api|route)\.(get|post|put|delete|patch)\s*\(\s*[`'\"]([^`'\"]+)[`'\"]", re.I)
EP_PY = re.compile(r"@(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]", re.I)


class AuditCancelled(Exception):
    pass


def _norm_folder(p: str) -> str:
    return (p or "").strip().replace("\\", "/").strip("/").lower()


def make_classifier(folder_map):
    """Longest-prefix match of a repo-relative path to a folder-map entry."""
    entries = sorted(((_norm_folder(e["path"]), e) for e in folder_map or []), key=lambda x: -len(x[0]))

    def classify(rel: str):
        r = rel.replace("\\", "/").lower()
        for pref, e in entries:
            if pref == "" or r == pref or r.startswith(pref + "/"):
                return e
        return None
    return classify


def _git_clone(git_url, dest, token, branch, cancel):
    """Clone shallow. The token never appears on the command line or in the URL: git asks a
    throw-away askpass helper that reads it from the child's environment only."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    askdir = None
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        if not BRANCH_RE.match(branch):
            raise ValueError("invalid branch name")
        cmd += ["--branch", branch]
    cmd += [git_url, dest]
    try:
        if token:
            askdir = tempfile.mkdtemp(prefix="ivv_ask_")
            helper = os.path.join(askdir, "ask.sh")
            with open(helper, "w") as fh:
                fh.write('#!/bin/sh\ncase "$1" in Username*) echo x-access-token;; *) echo "$GOV_GIT_TOKEN";; esac\n')
            os.chmod(helper, 0o700)
            env.update({"GIT_ASKPASS": helper, "GOV_GIT_TOKEN": token})
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        waited = 0.0
        while True:
            try:
                _, err = proc.communicate(timeout=1)
                break
            except subprocess.TimeoutExpired:
                waited += 1
                if cancel is not None and cancel.is_set():
                    proc.kill()
                    raise AuditCancelled()
                if waited > CLONE_TIMEOUT:
                    proc.kill()
                    raise RuntimeError(f"git clone timed out after {CLONE_TIMEOUT}s")
        if proc.returncode != 0:
            msg = (err or "").strip()[:300]
            if token:
                msg = msg.replace(token, "***")
            raise RuntimeError(f"git clone failed: {msg}")
    finally:
        if askdir:
            shutil.rmtree(askdir, ignore_errors=True)


def _clone_and_scan(git_url: str, token: str = None, key=None, branch: str = None, folder_map=None,
                    cancel=None, progress=None) -> dict:
    """Blocking: clone (shallow) + profile + scan. Run via asyncio.to_thread."""
    progress = progress or (lambda **k: None)
    classify = make_classifier(folder_map)
    tmp = tempfile.mkdtemp(prefix="ivv_repo_")
    cov = {"files_seen": 0, "files_scanned": 0, "skipped_large": 0, "skipped_generated": 0,
           "skipped_unreadable": 0, "skipped_over_cap": 0, "max_bytes": MAX_BYTES, "max_files": MAX_FILES}
    try:
        progress(stage="cloning")
        _git_clone(git_url, tmp, token, branch, cancel)
        progress(stage="scanning")

        languages, frameworks = {}, set()
        scanned, file_count, total_loc = [], 0, 0
        readme = {"present": False, "sections": 0, "documents_api": False, "chars": 0}
        openapi = {"present": False, "endpoints": 0}
        tests, code_file_count, ai_refs = [], 0, False
        endpoints, test_blobs = [], []
        source_ext = {".js", ".jsx", ".ts", ".tsx", ".py", ".java", ".go", ".rb", ".php", ".cs"}
        capped = False
        for root, dirs, files in os.walk(tmp):
            if capped:
                break
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            if cancel is not None and cancel.is_set():
                raise AuditCancelled()
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
                cov["files_seen"] += 1
                rel0 = os.path.relpath(fpath, tmp).replace("\\", "/")
                fm = classify(rel0)
                if fm and fm.get("purpose") == "generated":
                    cov["skipped_generated"] += 1
                    continue
                if file_count >= MAX_FILES:
                    cov["skipped_over_cap"] += 1
                    capped = True
                    break
                try:
                    if os.path.getsize(fpath) > MAX_BYTES:
                        cov["skipped_large"] += 1
                        continue
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                        text = fh.read()
                except Exception:
                    cov["skipped_unreadable"] += 1
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
                    test_blobs.append((rel, tl))
                elif ext in source_ext:
                    code_file_count += 1
                    for rx in (EP_JS, EP_PY):
                        for mm in rx.finditer(text):
                            endpoints.append({"method": mm.group(1).upper(), "path": mm.group(2), "defined_in": rel})
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
                sec, pii, log, stat = scan_secrets(text, key), scan_pii(text, key), scan_logging_leak(text, key), static_code_issues(text)
                if sec or pii or log or stat:
                    zone = (fm or {}).get("purpose") or ("tests" if is_test else "source")
                    scanned.append({"path": rel, "secrets": sec, "pii": pii, "logging": log, "static": stat,
                                    "zone": zone, "module": (fm or {}).get("module")})
                cov["files_scanned"] = file_count
                if file_count % 200 == 0:
                    progress(stage="scanning", files=file_count)
        test_cats = {}
        for t in tests:
            test_cats[t["category"]] = test_cats.get(t["category"], 0) + 1
        uniq = {}
        for e in endpoints:
            uniq.setdefault((e["method"], e["path"]), e)
        endpoints = list(uniq.values())
        for e in endpoints:
            e["tested_by"] = sorted({rel for rel, tl in test_blobs if e["path"].lower() in tl})[:5]
        endpoints = endpoints[:300]
        profile = {
            "languages": dict(sorted(languages.items(), key=lambda x: -x[1])),
            "frameworks": sorted(frameworks),
            "code_files_scanned": file_count,
            "approx_loc": total_loc,
            "coverage": cov,
            "spec": {"readme": readme, "openapi": openapi, "tests_total": len(tests),
                     "tests_by_category": test_cats, "source_files": code_file_count, "ai_refs": ai_refs,
                     "endpoints": endpoints, "endpoint_count": len(endpoints),
                     "untested_endpoints": sum(1 for e in endpoints if not e["tested_by"])},
        }
        progress(stage="analysing", files=file_count)
        return {"profile": profile, "scanned": scanned}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


HIGH_PII = {"pii:aadhaar", "pii:pan", "pii:card_number", "pii:gstin"}


LEVEL_FROM_TIER = {"T1": 4, "T2": 3, "T3": 2, "T4": 1}

# Live job state (progress is written from the scan thread). Final state is persisted in repo_jobs.
JOB_STATE: dict = {}
JOB_CANCEL: dict = {}


def _fingerprint(f):
    return f"{f['control_id']}|{f.get('subject_ref')}"


async def ingest_repo(db, git_url: str, name: str = None, git_token: str = None, branch: str = None,
                      integrity_level: int = 3, data_sensitivity: str = "unknown", folder_map=None,
                      languages=None, cancel=None, progress=None, started_by: str = None):
    if not re.match(r"^https://github\.com/[\w.\-]+/[\w.\-]+/?$", git_url.strip()):
        raise ValueError("Please provide a valid GitHub repository URL, e.g. https://github.com/org/repo")
    if branch and not BRANCH_RE.match(branch):
        raise ValueError("Invalid branch name")
    folder_map = [dict(e) for e in (folder_map or [])]

    git_url_c = git_url.strip().rstrip("/")
    existing = await db.projects.find_one({"repo_url": git_url_c, "source": "github_live"}, {"_id": 0})
    pid = existing["id"] if existing else str(uuid4())
    pkey = await get_project_key(db, pid)

    scan = await asyncio.to_thread(_clone_and_scan, git_url_c, git_token, pkey, branch, folder_map, cancel, progress)
    profile, scanned = scan["profile"], scan["scanned"]

    repo_name = name or git_url_c.split("/")[-1]
    now = datetime.now(timezone.utc).isoformat()
    meta = {"branch": branch, "integrity_level": integrity_level, "data_sensitivity": data_sensitivity,
            "folder_map": folder_map, "languages": languages or []}

    if existing:
        project = existing
        await db.projects.update_one({"id": pid}, {"$set": {"stage": "Repository Audit", "last_audited_at": now, **meta}})
        project.update(meta)
        await ledger_mod.append_to_ledger(db, "project_reaudit", pid, {"name": repo_name, "repo_url": git_url_c}, project_id=pid)
    else:
        project = {
            "id": pid, "name": repo_name,
            "description": f"Live IV&V audit of {git_url_c}",
            "stage": "Repository Audit", "repo_url": git_url_c,
            "source": "github_live", "created_at": now, "last_audited_at": now, **meta,
        }
        await db.projects.insert_one(dict(project))
        await ledger_mod.append_to_ledger(db, "project", project["id"], {"name": repo_name, "repo_url": git_url_c}, project_id=pid)

    event = {
        "id": str(uuid4()), "project_id": project["id"], "event_type": "repo_audit",
        "source_ref": git_url_c, "triggered_by": started_by or "A21",
        "controls_triggered": ["CTRL-06", "CTRL-07", "CTRL-08", "CTRL-10"],
        "created_at": now,
    }
    await db.events.insert_one(dict(event))
    await ledger_mod.append_to_ledger(db, "event", event["id"], {"event_type": "repo_audit", "project_id": project["id"]}, project_id=pid)

    findings = []

    def ev(hits, rel):
        return [{"type": h["type"], "masked": h["masked"], "hash": h["hash"],
                 "file": rel, "line": h.get("line"), "col": h.get("col")} for h in hits]

    for item in scanned:
        rel = item["path"]
        _mark = len(findings)
        if item["secrets"]:
            f = engine.build_finding(project, event, "CTRL-06", "Secrets Detection", "A05", "critical", 97, "FAIL",
                f"{len(item['secrets'])} potential secret(s) in {rel}: {', '.join(sorted({h['type'] for h in item['secrets']}))}.",
                ["security", "secrets"], "Rotate the exposed credential(s) and move them to a secrets manager / environment variables.",
                rel, "file", "deterministic_detector", ev(item["secrets"], rel))
            engine._apply_a05_rescan(f, "T0", item["secrets"], item["secrets"])
            findings.append(f)
        if item["pii"]:
            tier = "T1" if any(h["type"] in HIGH_PII for h in item["pii"]) else "T2"
            f = engine.build_finding(project, event, "CTRL-07", "India PII Detection", "A05", "high", 90, "FAIL",
                f"{len(item['pii'])} potential personal-data pattern(s) in {rel}: {', '.join(sorted({h['type'] for h in item['pii']}))}. DPDP Act 2023 relevance flagged.",
                ["security", "privacy", "dpdp"], "Remove hardcoded personal data; use masked fixtures and verify DPDP obligations.",
                rel, "file", "deterministic_detector", ev(item["pii"], rel))
            engine._apply_a05_rescan(f, tier, item["pii"], item["pii"])
            findings.append(f)
        if item["logging"]:
            f = engine.build_finding(project, event, "CTRL-08", "Sensitive Logging Leak", "A05", "high", 88, "FAIL",
                f"{len(item['logging'])} log/print statement(s) in {rel} may emit sensitive values.",
                ["security", "logging"], "Redact sensitive fields before logging; adopt structured logging with allow-lists.",
                rel, "file", "deterministic_detector", ev(item["logging"], rel))
            f["level2_status"] = "confirmed_by_recompute"
            findings.append(f)
        if item["static"]:
            sev = "high" if any(s["type"] == "dangerous_dynamic_execution" for s in item["static"]) else "low"
            f = engine.build_finding(project, event, "CTRL-10", "Static Code Heuristics", "A06", sev, 80, "FAIL",
                f"{len(item['static'])} code-quality issue(s) in {rel}: {', '.join(sorted({s['type'] for s in item['static']}))}.",
                ["code_quality"], "Address the flagged issues (dynamic execution, swallowed errors, markers).",
                rel, "file", "deterministic_detector",
                [{"type": s["type"], "masked": s["type"], "hash": "", "file": rel, "line": s.get("line")} for s in item["static"]])
            f["level2_status"] = "confirmed_by_recompute"
            findings.append(f)

        for f in findings[_mark:]:
            f["module"] = item.get("module")
            f["zone"] = item.get("zone")
            if item.get("zone") == "tests" and f["control_id"] == "CTRL-07":
                f["severity"] = "low"
                f["reason"] += " (test fixture zone: severity reduced; secrets are never reduced)"

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

    # ---- Traceability from spec/routes: endpoints <-> tests (CTRL-03) ----
    eps = spec.get("endpoints", [])
    if eps:
        orphans = [e for e in eps if not e.get("tested_by")]
        verdict = "FAIL" if orphans else "PASS"
        findings.append(spec_finding("CTRL-03", "API Traceability", "A03", "medium", verdict,
            f"{len(eps)} API endpoint(s) discovered; {len(orphans)} have no referencing test (orphan)." if orphans
            else f"All {len(eps)} discovered API endpoints are referenced by at least one test.",
            "Add tests that exercise each untested endpoint to close the traceability gap." if orphans else "No action required.",
            ["traceability", "api"]))
        for e in orphans[:25]:
            findings[-1]["evidence"].append({"type": "untested_endpoint", "masked": f"{e['method']} {e['path']}", "hash": ""})

    # ---- Reconcile with earlier audits: never delete history ----
    for f in findings:
        f["fingerprint"] = _fingerprint(f)
        f["first_seen_at"] = now
        f["last_seen_at"] = now
    old = await db.findings.find({"project_id": project["id"]}, {"_id": 0}).to_list(None)
    old_by_fp = {}
    for o in old:
        old_by_fp.setdefault(o.get("fingerprint") or _fingerprint(o), o)
    new_fps = {f["fingerprint"] for f in findings}
    diff = {"new": 0, "unchanged": 0, "resolved": 0}
    to_insert, current = [], []
    for f in findings:
        o = old_by_fp.get(f["fingerprint"])
        if o:
            # same finding: keep its id and triage state, refresh the facts
            upd = {k: f[k] for k in ("reason", "evidence", "severity", "verdict", "module", "zone", "tier",
                                     "suggested_remedy", "confidence") if k in f}
            upd.update({"last_seen_at": now, "fingerprint": f["fingerprint"], "event_id": event["id"]})
            await db.findings.update_one({"id": o["id"]}, {"$set": upd})
            o.update(upd)
            current.append(o)
            diff["unchanged"] += 1
        else:
            to_insert.append(f)
            current.append(f)
            diff["new"] += 1
    resolved = [o for fp, o in old_by_fp.items() if fp not in new_fps]
    if resolved:
        for o in resolved:
            o["superseded_at"] = now
            o["superseded_by_event"] = event["id"]
        await db.findings_archive.insert_many([dict(o) for o in resolved])
        await db.findings.delete_many({"id": {"$in": [o["id"] for o in resolved]}})
        diff["resolved"] = len(resolved)
    if to_insert:
        await db.findings.insert_many([dict(f) for f in to_insert])
        for f in to_insert:
            await ledger_mod.append_to_ledger(db, "finding", f["id"], {"control_id": f["control_id"], "verdict": f["verdict"], "severity": f["severity"]}, project_id=pid)
    findings = current

    has_secret = any(f["control_id"] == "CTRL-06" and f["verdict"] == "FAIL" for f in findings)
    has_high_pii = any(f["control_id"] == "CTRL-07" and f.get("tier") == "T1" and f.get("zone") != "tests" for f in findings)
    suggested = 4 if (has_secret or has_high_pii) else (3 if any(f["verdict"] == "FAIL" for f in findings) else 2)

    cov = profile.get("coverage", {})
    audit = {
        "id": str(uuid4()), "project_id": project["id"], "github_url": git_url_c, "branch": branch,
        "detected_languages": list(profile["languages"].keys()),
        "frameworks": profile["frameworks"],
        "integrity_level": integrity_level, "suggested_integrity_level": suggested,
        "data_sensitivity": data_sensitivity,
        "code_files_scanned": profile["code_files_scanned"], "approx_loc": profile["approx_loc"],
        "folder_map": folder_map, "coverage": cov, "diff": diff,
        "note": "Repository cloned and scanned read-only by the platform. Coverage counters show what was not scanned.",
        "endpoints": profile.get("spec", {}).get("endpoints", []),
        "endpoint_count": profile.get("spec", {}).get("endpoint_count", 0),
        "created_at": now,
    }
    await db.repo_audits.insert_one(dict(audit))
    await ledger_mod.append_to_ledger(db, "repo_audit", audit["id"], {"project_id": project["id"], "github_url": git_url_c, "diff": diff}, project_id=pid)
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
        "diff": diff,
        "finding_summary": {"total": len(findings), "by_severity": by_sev, "by_control": by_ctrl,
                            "fail": sum(1 for f in findings if f["verdict"] == "FAIL")},
        "reports": [author_report, team_lead_report],
        "gates": gates,
    }


async def run_job(db, job_id: str, params: dict, started_by: str):
    """Background wrapper: tracks status/progress in repo_jobs; cancellable."""
    import threading
    cancel = threading.Event()
    JOB_CANCEL[job_id] = cancel
    JOB_STATE[job_id] = {"status": "queued", "stage": "queued"}

    def progress(**k):
        JOB_STATE.setdefault(job_id, {}).update(k)
        if "stage" in k:
            JOB_STATE[job_id]["status"] = k["stage"]

    await db.repo_jobs.update_one({"id": job_id}, {"$set": {"status": "cloning", "started_at": datetime.now(timezone.utc).isoformat()}})
    try:
        result = await ingest_repo(db, cancel=cancel, progress=progress, started_by=started_by, **params)
        pid = result["project"]["id"]
        await db.repo_jobs.update_one({"id": job_id}, {"$set": {
            "status": "done", "project_id": pid, "diff": result["diff"],
            "finding_summary": result["finding_summary"], "coverage": result["profile"].get("coverage"),
            "finished_at": datetime.now(timezone.utc).isoformat()}})
        return result
    except AuditCancelled:
        await db.repo_jobs.update_one({"id": job_id}, {"$set": {"status": "cancelled", "finished_at": datetime.now(timezone.utc).isoformat()}})
    except Exception as e:  # noqa: BLE001 - job must record any failure
        await db.repo_jobs.update_one({"id": job_id}, {"$set": {"status": "failed", "error": str(e)[:500], "finished_at": datetime.now(timezone.utc).isoformat()}})
    finally:
        JOB_STATE.pop(job_id, None)
        JOB_CANCEL.pop(job_id, None)
