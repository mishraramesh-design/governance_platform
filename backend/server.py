import logging

from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware
import os

from database import db
import seed_data
from routers import catalog, projects, events, reports, assurance, dashboard

app = FastAPI(title="SDLC Governance & Assurance Platform")
api_router = APIRouter(prefix="/api")


@api_router.get("/")
async def root():
    return {"message": "SDLC Governance & Assurance Platform API - Observe, Collect Evidence, Advise."}


api_router.include_router(catalog.router)
api_router.include_router(projects.router)
api_router.include_router(events.router)
api_router.include_router(reports.router)
api_router.include_router(assurance.router)
api_router.include_router(dashboard.router)

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def seed_on_startup():
    try:
        await seed_data.ensure_seeded(db)
    except Exception as e:
        logger.error(f"Seeding failed: {e}")
