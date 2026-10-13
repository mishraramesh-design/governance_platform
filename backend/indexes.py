"""MongoDB indexes for every filtered or sorted field. Idempotent; safe to run at every startup."""
import logging

import ledger as ledger_mod

logger = logging.getLogger(__name__)

INDEXES = {
    "findings": [[("project_id", 1), ("created_at", -1)], [("project_id", 1), ("control_id", 1)],
                 [("project_id", 1), ("severity", 1)], [("project_id", 1), ("status", 1), ("verdict", 1)],
                 [("project_id", 1), ("module", 1)], [("id", 1)], [("event_id", 1)], [("subject_ref", 1)]],
    "findings_archive": [[("project_id", 1), ("superseded_at", -1)], [("id", 1)]],
    "events": [[("project_id", 1), ("created_at", -1)], [("id", 1)]],
    "reports": [[("project_id", 1), ("created_at", -1)], [("id", 1)]],
    "adjudications": [[("project_id", 1), ("created_at", -1)], [("id", 1)], [("finding_id", 1)]],
    "artifacts": [[("project_id", 1), ("created_at", -1)], [("id", 1)]],
    "commits": [[("project_id", 1)], [("commit_id", 1)], [("author_user_id", 1)]],
    "requirements": [[("project_id", 1)]],
    "test_cases": [[("project_id", 1)]],
    "design_items": [[("project_id", 1)]],
    "projects": [[("id", 1)], [("repo_url", 1)]],
    "users": [[("id", 1)], [("email", 1)], [("teams", 1)]],
    "role_assignments": [[("user_id", 1), ("project_id", 1)]],
    "api_tokens": [[("token_hash", 1)], [("user_id", 1)]],
    "edge_bundles": [[("project_id", 1), ("created_at", -1)], [("id", 1)]],
    "llm_calls": [[("timestamp", -1)]],
    "triage_decisions": [[("finding_id", 1)]],
    "repo_audits": [[("project_id", 1), ("created_at", -1)]],
    "author_aliases": [[("alias_lc", 1)]],
}


async def ensure_indexes(db):
    n = 0
    for coll, specs in INDEXES.items():
        for spec in specs:
            try:
                await db[coll].create_index(spec)
                n += 1
            except Exception as e:
                logger.warning("index %s %s failed: %s", coll, spec, e)
    await ledger_mod.ensure_ledger_indexes(db)
    return n
