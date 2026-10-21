"""Admin surface (Programme Manager only): manage role assignments and issue/revoke API tokens.

Tokens are returned in plaintext exactly once at issuance; only the SHA-256 hash is stored.
"""
from uuid import uuid4
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from database import db
import auth

router = APIRouter(prefix="/admin")

ALL_ROLES = [
    "Developer", "BA Lead", "Tech Lead", "Quality Lead", "Project Manager",
    "Architect", "Programme Manager", "Security/DPO",
]


async def require_admin(user=Depends(auth.get_current_user)):
    await auth.require_platform_admin(user)
    return user


class AssignmentUpdate(BaseModel):
    user_id: str
    project_id: str
    roles: List[str]


class IssueTokenRequest(BaseModel):
    user_id: str


@router.get("/roles")
async def roles():
    return ALL_ROLES


@router.get("/users")
async def admin_users(admin=Depends(require_admin)):
    users = await db.users.find({}, {"_id": 0}).sort("name", 1).to_list(200)
    projects = await db.projects.find({}, {"_id": 0}).to_list(200)
    out = []
    for u in users:
        assignments = await db.role_assignments.find({"user_id": u["id"]}, {"_id": 0}).to_list(200)
        tokens = await db.api_tokens.find(
            {"user_id": u["id"]}, {"_id": 0, "token_hash": 0}).sort("created_at", -1).to_list(200)
        out.append({**u, "assignments": assignments, "tokens": tokens})
    return {"users": out, "projects": projects, "roles": ALL_ROLES}


@router.put("/assignments")
async def set_assignment(payload: AssignmentUpdate, admin=Depends(require_admin)):
    invalid = [r for r in payload.roles if r not in ALL_ROLES]
    if invalid:
        raise HTTPException(422, f"unknown role(s): {', '.join(invalid)}")
    if not await db.users.find_one({"id": payload.user_id}):
        raise HTTPException(404, "user not found")
    if not await db.projects.find_one({"id": payload.project_id}):
        raise HTTPException(404, "project not found")
    await db.role_assignments.update_one(
        {"user_id": payload.user_id, "project_id": payload.project_id},
        {"$set": {"roles": payload.roles, "updated_at": auth.now_iso()},
         "$setOnInsert": {"id": str(uuid4()), "user_id": payload.user_id,
                          "project_id": payload.project_id, "created_at": auth.now_iso()}},
        upsert=True)
    return await db.role_assignments.find_one(
        {"user_id": payload.user_id, "project_id": payload.project_id}, {"_id": 0})


@router.post("/tokens")
async def issue_token(payload: IssueTokenRequest, admin=Depends(require_admin)):
    user = await db.users.find_one({"id": payload.user_id, "active": True}, {"_id": 0})
    if not user:
        raise HTTPException(404, "user not found or inactive")
    token = auth.generate_token()
    token_id = str(uuid4())
    await db.api_tokens.insert_one({
        "id": token_id, "token_hash": auth.hash_token(token), "user_id": user["id"],
        "created_by": admin["name"], "revoked": False, "created_at": auth.now_iso()})
    # Plaintext returned exactly once; never retrievable again.
    return {"token": token, "token_id": token_id, "user_id": user["id"]}


@router.get("/tokens")
async def list_tokens(user_id: Optional[str] = Query(None), admin=Depends(require_admin)):
    q = {"user_id": user_id} if user_id else {}
    return await db.api_tokens.find(q, {"_id": 0, "token_hash": 0}).sort("created_at", -1).to_list(500)


@router.post("/tokens/{token_id}/revoke")
async def revoke_token(token_id: str, admin=Depends(require_admin)):
    res = await db.api_tokens.update_one(
        {"id": token_id}, {"$set": {"revoked": True, "revoked_at": auth.now_iso(),
                                    "revoked_by": admin["name"]}})
    if res.matched_count != 1:
        raise HTTPException(404, "token not found")
    return {"revoked": True, "token_id": token_id}
