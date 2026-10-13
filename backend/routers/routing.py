"""Read-only routing matrix (D decides, R receives, I informed, U urgent)."""
from fastapi import APIRouter

from database import db
from routers.admin import ALL_ROLES

router = APIRouter()

LEGEND = {"D": "Decides", "R": "Receives", "I": "Informed", "U": "Urgent"}


@router.get("/routing")
async def get_routing():
    rows = await db.routing_matrix.find({}, {"_id": 0}).sort("order", 1).to_list(500)
    return {"rows": rows, "roles": ALL_ROLES, "legend": LEGEND}
