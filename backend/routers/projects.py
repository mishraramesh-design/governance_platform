from fastapi import APIRouter, HTTPException, Query

from database import db

router = APIRouter()


@router.get("/projects")
async def list_projects():
    return await db.projects.find({}, {"_id": 0}).to_list(1000)


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    project = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not project:
        raise HTTPException(404, "project not found")
    return project


@router.get("/requirements")
async def list_requirements(project_id: str = Query(...)):
    return await db.requirements.find({"project_id": project_id}, {"_id": 0}).to_list(1000)


@router.get("/commits")
async def list_commits(project_id: str = Query(...)):
    return await db.commits.find({"project_id": project_id}, {"_id": 0}).to_list(1000)


@router.get("/test-cases")
async def list_test_cases(project_id: str = Query(...)):
    return await db.test_cases.find({"project_id": project_id}, {"_id": 0}).to_list(1000)


@router.get("/design-items")
async def list_design_items(project_id: str = Query(...)):
    return await db.design_items.find({"project_id": project_id}, {"_id": 0}).to_list(1000)
