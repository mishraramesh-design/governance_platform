import logging

from fastapi import FastAPI, APIRouter, Depends, HTTPException
from starlette.middleware.cors import CORSMiddleware
import os

from database import db
import auth as auth_mod
import seed_data
import indexes
from routers import catalog, projects, events, reports, assurance, dashboard, harness, mlops
from routers import auth as auth_routes, admin as admin_routes, routing as routing_routes, people as people_routes

app = FastAPI(title="SDLC Governance & Assurance Platform")
api_router = APIRouter(prefix="/api")


@api_router.get("/health")
async def health():
    """Public liveness/readiness probe (no data returned)."""
    try:
        await db.command("ping")
    except Exception:
        raise HTTPException(503, "database unavailable")
    return {"status": "ok"}


@api_router.get("/")
async def root():
    return {"message": "SDLC Governance & Assurance Platform API - Observe, Collect Evidence, Advise."}


api_router.include_router(catalog.router, dependencies=[Depends(auth_mod.require_read_access)])
api_router.include_router(projects.router, dependencies=[Depends(auth_mod.require_read_access)])
api_router.include_router(events.router, dependencies=[Depends(auth_mod.require_read_access)])
api_router.include_router(reports.router, dependencies=[Depends(auth_mod.require_read_access)])
api_router.include_router(assurance.router, dependencies=[Depends(auth_mod.require_read_access)])
api_router.include_router(dashboard.router, dependencies=[Depends(auth_mod.require_read_access)])
api_router.include_router(harness.router, dependencies=[Depends(auth_mod.require_read_access)])
api_router.include_router(mlops.router, dependencies=[Depends(auth_mod.require_read_access)])
api_router.include_router(auth_routes.router)
api_router.include_router(admin_routes.router)
api_router.include_router(people_routes.router)
api_router.include_router(routing_routes.router, dependencies=[Depends(auth_mod.require_read_access)])

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    expose_headers=["X-Total-Count", "X-Page", "X-Page-Size"],
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()] or ["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def migrate_integrity_level():
    """Data tiers (T0-T4) and IEEE 1012 integrity levels (1-4) are different things. Convert old project field."""
    m = {"T1": 4, "T2": 3, "T3": 2, "T4": 1}
    async for p in db.projects.find({"integrity_tier": {"$exists": True}}, {"_id": 0, "id": 1, "integrity_tier": 1}):
        await db.projects.update_one({"id": p["id"]}, {"$set": {"integrity_level": m.get(p["integrity_tier"], 3)},
                                                      "$unset": {"integrity_tier": ""}})


@app.on_event("startup")
async def seed_on_startup():
    try:
        await indexes.ensure_indexes(db)
        await seed_data.ensure_seeded(db)
        await seed_data.ensure_users_seeded(db)
        await migrate_integrity_level()
        await db.repo_jobs.update_many({"status": {"$in": ["queued", "cloning", "scanning", "analysing"]}},
                                       {"$set": {"status": "failed", "error": "Interrupted by server restart"}})
        await seed_data.ensure_routing_seeded(db)
        await mlops.ensure_mlops_seeded(db)
    except Exception as e:
        logger.error(f"Seeding failed: {e}")
