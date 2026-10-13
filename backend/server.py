import logging

from fastapi import FastAPI, APIRouter, Depends
from starlette.middleware.cors import CORSMiddleware
import os

from database import db
import auth as auth_mod
import seed_data
from routers import catalog, projects, events, reports, assurance, dashboard, harness, mlops
from routers import auth as auth_routes, admin as admin_routes, routing as routing_routes

app = FastAPI(title="SDLC Governance & Assurance Platform")
api_router = APIRouter(prefix="/api")


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
api_router.include_router(routing_routes.router, dependencies=[Depends(auth_mod.require_read_access)])

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()] or ["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def seed_on_startup():
    try:
        await seed_data.ensure_seeded(db)
        await seed_data.ensure_users_seeded(db)
        await seed_data.ensure_routing_seeded(db)
        await mlops.ensure_mlops_seeded(db)
    except Exception as e:
        logger.error(f"Seeding failed: {e}")
