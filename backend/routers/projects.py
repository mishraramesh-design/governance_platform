from fastapi import APIRouter, HTTPException, Query, Response

from database import db
from pagination import paged

router = APIRouter()


@router.get("/projects")
async def list_projects():
    return await db.projects.find({}, {"_id": 0}).sort("created_at", -1).to_list(5000)


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    project = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not project:
        raise HTTPException(404, "project not found")
    return project


@router.get("/requirements")
async def list_requirements(response: Response, project_id: str = Query(...), page: int = 1, page_size: int = 500):
    return await paged(db.requirements, {"project_id": project_id}, None, response, page, page_size)


@router.get("/commits")
async def list_commits(response: Response, project_id: str = Query(...), page: int = 1, page_size: int = 500):
    return await paged(db.commits, {"project_id": project_id}, None, response, page, page_size)


@router.get("/test-cases")
async def list_test_cases(response: Response, project_id: str = Query(...), page: int = 1, page_size: int = 500):
    return await paged(db.test_cases, {"project_id": project_id}, None, response, page, page_size)


@router.get("/design-items")
async def list_design_items(response: Response, project_id: str = Query(...), page: int = 1, page_size: int = 500):
    return await paged(db.design_items, {"project_id": project_id}, None, response, page, page_size)
