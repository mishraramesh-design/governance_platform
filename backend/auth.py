"""Opaque Bearer-token authentication and project-scoped authorization.

Design:
- Tokens are random (secrets.token_urlsafe); ONLY their SHA-256 hash is stored.
- Every request re-checks the DB: token exists, not revoked, user active.
- Authentication (who you are) is separate from authorization (what role you may act as).
- Missing/invalid/revoked token -> 401. Valid token but wrong role -> 403.
"""
import hashlib
import os
import secrets
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from database import db

bearer_scheme = HTTPBearer(auto_error=False)

# Roles that may perform platform-wide (non project-scoped) governance actions.
GOVERNANCE_ROLES = {"Programme Manager", "Quality Lead"}
ADMIN_ROLE = "Programme Manager"


def demo_mode() -> bool:
    """DEMO_MODE=true enables the unauthenticated demo sign-in and open reads. Default: off."""
    return os.environ.get("DEMO_MODE", "false").strip().lower() == "true"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _resolve(credentials):
    if not credentials or (credentials.scheme or "").lower() != "bearer":
        return None
    token_doc = await db.api_tokens.find_one(
        {"token_hash": hash_token(credentials.credentials), "revoked": False}, {"_id": 0})
    if not token_doc:
        return None
    user = await db.users.find_one({"id": token_doc["user_id"], "active": True}, {"_id": 0})
    if not user:
        return None
    user["_token_id"] = token_doc["id"]
    return user


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    user = await _resolve(credentials)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Valid bearer token required",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


async def get_optional_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    """Returns the user if a valid token is present, else None (never raises 401).
    Used by ingest endpoints that accept anonymous input as 'unattributed'."""
    return await _resolve(credentials)


async def require_read_access(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    """Applied to every data route. Open only in DEMO_MODE; otherwise a valid token is required."""
    if demo_mode():
        return await _resolve(credentials)
    return await get_current_user(credentials)


async def require_governance(user=Depends(get_current_user)):
    """Platform-wide governance actions: Programme Manager or Quality Lead."""
    await require_any_global_role(user, GOVERNANCE_ROLES)
    return user


async def require_member(user: dict, project_id: str):
    """User must hold at least one role on the project."""
    if not await roles_for(user["id"], project_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You hold no role on this project.")
    return user


def public_user(user: dict) -> dict:
    return {k: v for k, v in user.items() if not k.startswith("_")}


async def roles_for(user_id: str, project_id: str):
    ra = await db.role_assignments.find_one({"user_id": user_id, "project_id": project_id}, {"_id": 0})
    return ra.get("roles", []) if ra else []


async def all_roles(user_id: str):
    s = set()
    async for ra in db.role_assignments.find({"user_id": user_id}, {"_id": 0}):
        s.update(ra.get("roles", []))
    return s


async def require_project_role(user: dict, project_id: str, role: str):
    assigned = await roles_for(user["id"], project_id)
    if role not in assigned:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Role '{role}' is not assigned to {user['name']} for this project "
            f"(assigned: {', '.join(assigned) or 'none'}).")
    return role


async def require_any_global_role(user: dict, roles=GOVERNANCE_ROLES):
    have = await all_roles(user["id"])
    if not (have & set(roles)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"This action requires one of: {', '.join(sorted(roles))}.")


async def finding_author_user_id(finding: dict):
    """Resolve the user who authored the code/subject behind a finding, for
    segregation-of-duties checks. Author = commit author mapped to a user by name,
    or an explicit author_user_id / submitted_by_user_id stored on the finding."""
    for key in ("author_user_id", "submitted_by_user_id"):
        if finding.get(key):
            return finding[key]
    if finding.get("subject_type") == "commit" and finding.get("subject_ref"):
        commit = await db.commits.find_one(
            {"commit_id": finding["subject_ref"], "project_id": finding.get("project_id")}, {"_id": 0})
        if commit:
            if commit.get("author_user_id"):
                return commit["author_user_id"]
            if commit.get("author"):
                u = await db.users.find_one({"name": commit["author"]}, {"_id": 0})
                if u:
                    return u["id"]
    return None


async def enforce_segregation(user: dict, finding: dict):
    author_uid = await finding_author_user_id(finding)
    if author_uid and author_uid == user["id"]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Segregation of duties: you authored the code behind this finding, so you "
            "cannot triage, accept or close it. Another reviewer must decide.")


async def ensure_project_assignments(project_id: str):
    """Give every demo user their standing role set on a newly created project so the
    project is immediately usable for triage/adjudication."""
    async for u in db.users.find({}, {"_id": 0}):
        if await db.role_assignments.find_one({"user_id": u["id"], "project_id": project_id}):
            continue
        roles = sorted(await all_roles(u["id"]))
        await db.role_assignments.insert_one({
            "id": generate_token()[:12], "user_id": u["id"], "project_id": project_id,
            "roles": roles, "created_at": now_iso()})
