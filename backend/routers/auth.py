"""Authentication surface: demo user directory and in-memory 'sign in as' flow.

This is a prototype convenience: demo-login mints a fresh opaque token for a seeded
demo user (only the hash is stored). The frontend keeps the token in memory only.
Real token issuance/revocation is admin-gated under /admin.
"""
from uuid import uuid4
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from database import db
import auth

router = APIRouter()


class DemoLoginRequest(BaseModel):
    user_id: str


@router.get('/auth/status')
async def status():
    return {'demo_mode': auth.demo_enabled()}


@router.get("/auth/users")
async def list_users(project_id: Optional[str] = Query(None), user=Depends(auth.get_optional_user)):
    if not auth.demo_enabled():
        if not user:
            raise HTTPException(401, 'Valid bearer token required')
        await auth.require_platform_admin(user)
    users = await db.users.find({}, {"_id": 0}).sort("name", 1).to_list(200)
    for u in users:
        u["roles"] = await auth.roles_for(u["id"], project_id) if project_id else []
    return users


@router.post("/auth/demo-login")
async def demo_login(payload: DemoLoginRequest):
    if not auth.demo_enabled():
        raise HTTPException(404, 'Demo login is disabled. Sign in with your issued access token.')
    user = await db.users.find_one({"id": payload.user_id, "active": True}, {"_id": 0})
    if not user:
        raise HTTPException(404, "demo user not found or inactive")
    token = auth.generate_token()
    token_id = str(uuid4())
    await db.api_tokens.insert_one({
        "id": token_id, "token_hash": auth.hash_token(token), "user_id": user["id"],
        "created_by": "demo-login", "revoked": False, "created_at": auth.now_iso()})
    return {"token": token, "token_id": token_id, "user": user}


@router.get("/auth/me")
async def me(project_id: Optional[str] = Query(None), user=Depends(auth.get_current_user)):
    return {
        "user": auth.public_user(user),
        "roles": await auth.roles_for(user["id"], project_id) if project_id else [],
        "all_roles": sorted(await auth.all_roles(user["id"])),
        "is_admin": await auth.is_platform_admin(user),
    }
