"""People administration for real teams (Programme Manager only): create users, CSV bulk import,
teams, git-author aliases, bulk token issue, deactivation. Tokens are returned once; only hashes
are stored. Nothing here touches client systems."""
import csv
import io
import re
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import auth
from database import db
from routers.admin import ALL_ROLES, require_admin

router = APIRouter(prefix="/admin")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _split(v: str) -> List[str]:
    return [x.strip() for x in re.split(r"[;|]", v or "") if x.strip()]


async def _unique_user_id(email: str) -> str:
    base = "u-" + re.sub(r"[^a-z0-9]+", "-", email.split("@")[0].lower()).strip("-")
    uid, n = base, 1
    while await db.users.find_one({"id": uid}):
        n += 1
        uid = f"{base}-{n}"
    return uid


async def _ensure_team(name: str) -> dict:
    t = await db.teams.find_one({"name_lc": name.lower()}, {"_id": 0})
    if not t:
        t = {"id": str(uuid4()), "name": name, "name_lc": name.lower(), "created_at": _now()}
        await db.teams.insert_one(dict(t))
    return t


async def _assign(user_id: str, project_ids: List[str], roles: List[str]):
    for pid in project_ids:
        await db.role_assignments.update_one(
            {"user_id": user_id, "project_id": pid},
            {"$set": {"roles": roles, "updated_at": _now()},
             "$setOnInsert": {"id": str(uuid4()), "user_id": user_id, "project_id": pid, "created_at": _now()}},
            upsert=True)


async def _create_user(name, email, teams, roles, project_ids):
    uid = await _unique_user_id(email)
    for t in teams:
        await _ensure_team(t)
    doc = {"id": uid, "name": name, "email": email.lower(), "teams": teams, "active": True, "created_at": _now()}
    await db.users.insert_one(dict(doc))
    await _assign(uid, project_ids, roles)
    return doc


async def _target_projects(project_ids: Optional[List[str]]):
    if project_ids:
        return project_ids
    return [p["id"] async for p in db.projects.find({}, {"_id": 0, "id": 1})]


# ---------------------------------------------------------------- users
class NewUser(BaseModel):
    name: str
    email: str
    teams: List[str] = []
    roles: List[str] = []
    project_ids: Optional[List[str]] = None


def _validate_roles(roles):
    bad = [r for r in roles if r not in ALL_ROLES]
    if bad:
        raise HTTPException(422, f"unknown role(s): {', '.join(bad)}")


@router.post("/users", status_code=201)
async def create_user(body: NewUser, admin=Depends(require_admin)):
    if not body.name.strip():
        raise HTTPException(422, "name is required")
    if not EMAIL_RE.match(body.email.strip()):
        raise HTTPException(422, "invalid email")
    _validate_roles(body.roles)
    if await db.users.find_one({"email": body.email.strip().lower()}):
        raise HTTPException(409, "a user with this email already exists")
    pids = await _target_projects(body.project_ids)
    u = await _create_user(body.name.strip(), body.email.strip(), body.teams, body.roles, pids)
    return u


class CsvBody(BaseModel):
    csv_text: str
    project_ids: Optional[List[str]] = None
    skip_errors: bool = False


async def _parse_csv(text: str):
    """Columns: name,email,team,roles   (team and roles may hold several values separated by ; or |)."""
    rows, seen = [], set()
    reader = csv.DictReader(io.StringIO(text.strip()))
    fields = [f.strip().lower() for f in (reader.fieldnames or [])]
    if "name" not in fields or "email" not in fields:
        raise HTTPException(422, "CSV needs at least the columns: name,email (optional: team,roles)")
    for i, raw in enumerate(reader, start=2):
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        errs = []
        email = r.get("email", "").lower()
        if not r.get("name"):
            errs.append("name missing")
        if not EMAIL_RE.match(email):
            errs.append("invalid email")
        elif email in seen:
            errs.append("duplicate email in file")
        elif await db.users.find_one({"email": email}):
            errs.append("email already exists")
        seen.add(email)
        roles = _split(r.get("roles", ""))
        bad = [x for x in roles if x not in ALL_ROLES]
        if bad:
            errs.append("unknown role: " + ", ".join(bad))
        rows.append({"line": i, "name": r.get("name", ""), "email": email,
                     "teams": _split(r.get("team", "") or r.get("teams", "")), "roles": roles,
                     "status": "error" if errs else "ok", "errors": errs})
    return rows


@router.post("/users/import/preview")
async def import_preview(body: CsvBody, admin=Depends(require_admin)):
    rows = await _parse_csv(body.csv_text)
    return {"rows": rows, "ok": sum(r["status"] == "ok" for r in rows),
            "errors": sum(r["status"] == "error" for r in rows)}


@router.post("/users/import/commit")
async def import_commit(body: CsvBody, admin=Depends(require_admin)):
    rows = await _parse_csv(body.csv_text)
    errors = [r for r in rows if r["status"] == "error"]
    if errors and not body.skip_errors:
        raise HTTPException(422, {"message": "fix the rows with errors or set skip_errors", "rows": errors})
    pids = await _target_projects(body.project_ids)
    created = []
    for r in rows:
        if r["status"] != "ok":
            continue
        u = await _create_user(r["name"], r["email"], r["teams"], r["roles"], pids)
        created.append({"id": u["id"], "name": u["name"], "email": u["email"]})
    return {"created": created, "skipped": len(errors)}


class UserPatch(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    teams: Optional[List[str]] = None
    active: Optional[bool] = None


@router.patch("/users/{user_id}")
async def patch_user(user_id: str, body: UserPatch, admin=Depends(require_admin)):
    u = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not u:
        raise HTTPException(404, "user not found")
    upd = {}
    if body.name is not None:
        upd["name"] = body.name.strip()
    if body.email is not None:
        if not EMAIL_RE.match(body.email.strip()):
            raise HTTPException(422, "invalid email")
        other = await db.users.find_one({"email": body.email.strip().lower(), "id": {"$ne": user_id}})
        if other:
            raise HTTPException(409, "email in use")
        upd["email"] = body.email.strip().lower()
    if body.teams is not None:
        for t in body.teams:
            await _ensure_team(t)
        upd["teams"] = body.teams
    if body.active is not None:
        if user_id == admin["id"] and body.active is False:
            raise HTTPException(422, "you cannot deactivate yourself")
        upd["active"] = body.active
    if upd:
        await db.users.update_one({"id": user_id}, {"$set": upd})
    revoked = 0
    if body.active is False:
        res = await db.api_tokens.update_many({"user_id": user_id, "revoked": False},
                                              {"$set": {"revoked": True, "revoked_at": _now(), "revoked_by": admin["name"]}})
        revoked = res.modified_count
    out = await db.users.find_one({"id": user_id}, {"_id": 0})
    return {**out, "tokens_revoked": revoked}


@router.get("/people")
async def list_people(q: str = "", team: str = "", page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                      admin=Depends(require_admin)):
    flt = {}
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        flt["$or"] = [{"name": rx}, {"email": rx}]
    if team:
        flt["teams"] = team
    total = await db.users.count_documents(flt)
    users = await db.users.find(flt, {"_id": 0}).sort("name", 1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    for u in users:
        u["live_tokens"] = await db.api_tokens.count_documents({"user_id": u["id"], "revoked": False})
    return {"users": users, "total": total, "page": page, "page_size": page_size}


# ---------------------------------------------------------------- teams
class NewTeam(BaseModel):
    name: str


@router.get("/teams")
async def list_teams(admin=Depends(require_admin)):
    teams = await db.teams.find({}, {"_id": 0, "name_lc": 0}).sort("name", 1).to_list(500)
    for t in teams:
        t["members"] = await db.users.count_documents({"teams": t["name"]})
    return teams


@router.post("/teams", status_code=201)
async def create_team(body: NewTeam, admin=Depends(require_admin)):
    if not body.name.strip():
        raise HTTPException(422, "name is required")
    t = await _ensure_team(body.name.strip())
    t.pop("name_lc", None)
    return t


class TeamAssignment(BaseModel):
    team: str
    project_id: str
    roles: List[str]
    mode: str = "add"   # add | replace


@router.put("/team-assignments")
async def team_assignment(body: TeamAssignment, admin=Depends(require_admin)):
    _validate_roles(body.roles)
    if body.mode not in ("add", "replace"):
        raise HTTPException(422, "mode must be add or replace")
    if not await db.projects.find_one({"id": body.project_id}):
        raise HTTPException(404, "project not found")
    changed = 0
    async for u in db.users.find({"teams": body.team, "active": True}, {"_id": 0}):
        cur = await auth.roles_for(u["id"], body.project_id)
        roles = sorted(set(body.roles) | (set(cur) if body.mode == "add" else set()))
        await _assign(u["id"], [body.project_id], roles)
        changed += 1
    return {"team": body.team, "project_id": body.project_id, "users_updated": changed}


# ---------------------------------------------------------------- git author aliases
class Alias(BaseModel):
    alias: str          # git author name or email
    user_id: str


@router.get("/aliases")
async def list_aliases(admin=Depends(require_admin)):
    return await db.author_aliases.find({}, {"_id": 0}).sort("alias", 1).to_list(5000)


@router.post("/aliases", status_code=201)
async def add_alias(body: Alias, admin=Depends(require_admin)):
    if not await db.users.find_one({"id": body.user_id}):
        raise HTTPException(404, "user not found")
    key = body.alias.strip().lower()
    if not key:
        raise HTTPException(422, "alias is required")
    await db.author_aliases.update_one(
        {"alias_lc": key}, {"$set": {"alias": body.alias.strip(), "alias_lc": key, "user_id": body.user_id},
                            "$setOnInsert": {"id": str(uuid4()), "created_at": _now()}}, upsert=True)
    # backfill commits and findings by this author
    await db.commits.update_many({"$or": [{"author": body.alias.strip()}, {"author_email": key}]},
                                 {"$set": {"author_user_id": body.user_id}})
    return await db.author_aliases.find_one({"alias_lc": key}, {"_id": 0})


@router.delete("/aliases/{alias_id}")
async def delete_alias(alias_id: str, admin=Depends(require_admin)):
    res = await db.author_aliases.delete_one({"id": alias_id})
    if res.deleted_count != 1:
        raise HTTPException(404, "alias not found")
    return {"deleted": True}


@router.get("/unmapped-authors")
async def unmapped_authors(admin=Depends(require_admin)):
    """Commit authors that cannot be tied to a platform user (so segregation of duties and
    routing cannot work for them)."""
    names = {u["name"].lower() for u in await db.users.find({}, {"_id": 0, "name": 1}).to_list(100000)}
    emails = {u["email"].lower() for u in await db.users.find({}, {"_id": 0, "email": 1}).to_list(100000)}
    aliases = {a["alias_lc"] for a in await db.author_aliases.find({}, {"_id": 0}).to_list(100000)}
    out = {}
    async for c in db.commits.find({"author_user_id": {"$exists": False}}, {"_id": 0, "author": 1, "author_email": 1, "project_id": 1}):
        a = (c.get("author") or "").strip()
        e = (c.get("author_email") or "").strip().lower()
        if a.lower() in names | aliases or (e and e in emails | aliases):
            continue
        key = a or e
        if key:
            out.setdefault(key, {"author": key, "commits": 0})["commits"] += 1
    return sorted(out.values(), key=lambda x: -x["commits"])


# ---------------------------------------------------------------- bulk tokens
class BulkTokens(BaseModel):
    user_ids: Optional[List[str]] = None   # default: every active user with no live token


@router.post("/tokens/bulk")
async def bulk_tokens(body: BulkTokens, admin=Depends(require_admin)):
    flt = {"active": True}
    if body.user_ids:
        flt["id"] = {"$in": body.user_ids}
    issued = []
    async for u in db.users.find(flt, {"_id": 0}):
        if not body.user_ids and await db.api_tokens.find_one({"user_id": u["id"], "revoked": False}):
            continue
        token = auth.generate_token()
        await db.api_tokens.insert_one({
            "id": str(uuid4()), "token_hash": auth.hash_token(token), "user_id": u["id"],
            "created_by": admin["name"], "revoked": False, "created_at": _now()})
        issued.append({"user_id": u["id"], "name": u["name"], "email": u["email"], "token": token})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "email", "token"])
    for r in issued:
        w.writerow([r["name"], r["email"], r["token"]])
    return {"issued": len(issued), "csv": buf.getvalue(),
            "note": "Tokens are shown once. Only hashes are stored."}
