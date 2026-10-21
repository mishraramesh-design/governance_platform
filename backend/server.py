import logging
from safe_logging import configure_safe_logging

configure_safe_logging()

from fastapi import FastAPI, APIRouter, Depends
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
import os

from database import db
import seed_data
import ledger
from access_policy import protect_api
from routers import catalog, projects, events, reports, assurance, dashboard, harness, mlops
from routers import auth as auth_routes, admin as admin_routes, routing as routing_routes
from routers import studio as studio_routes
from routers import testing_workspace as testing_workspace_routes

app = FastAPI(title="SDLC Governance & Assurance Platform")


@app.exception_handler(ledger.LedgerWriteError)
async def ledger_write_unavailable(request, exc):
    return JSONResponse(status_code=503, content={
        'detail': 'Audit storage could not record this operation. Retry after administrator review.',
        'error_code': 'ledger_write_unavailable', 'reference': exc.reference}, headers={'Retry-After': '5'})


api_router = APIRouter(prefix="/api", dependencies=[Depends(protect_api)])


@api_router.get("/")
async def root():
    return {"message": "SDLC Governance & Assurance Platform API - Observe, Collect Evidence, Advise."}


api_router.include_router(catalog.router)
api_router.include_router(projects.router)
api_router.include_router(events.router)
api_router.include_router(reports.router)
api_router.include_router(assurance.router)
api_router.include_router(dashboard.router)
api_router.include_router(harness.router)
api_router.include_router(mlops.router)
api_router.include_router(auth_routes.router)
api_router.include_router(admin_routes.router)
api_router.include_router(routing_routes.router)
api_router.include_router(studio_routes.router)
api_router.include_router(testing_workspace_routes.router)

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)


@app.on_event("startup")
async def seed_on_startup():
    await ledger.initialize(db)
    await testing_workspace_routes.recover_sessions()
    try:
        await studio_routes.recover_scanner()
    except Exception:
        logger.error("ZAP orphan recovery failed; new web scans are blocked until backend restart.")
    try:
        await db.studio_runs.update_many(
            {"web_security_scan.status": {"$in": ["queued", "running"]}},
            {"$set": {"web_security_scan.status": "interrupted",
                      "web_security_scan.error": "Backend restarted during scan; review scanner status before retrying."}},
        )
        await db.studio_runs.update_many(
            {"framework_assessment.status": {"$in": ["queued", "running"]}},
            {"$set": {"framework_assessment.status": "interrupted",
                      "framework_assessment.error": "Backend restarted during assessment; the test may have stopped early."}},
        )
        await seed_data.ensure_seeded(db)
        await seed_data.ensure_users_seeded(db)
        await seed_data.ensure_routing_seeded(db)
        await mlops.ensure_mlops_seeded(db)
    except Exception as e:
        logger.error(f"Seeding failed: {e}")
        raise
