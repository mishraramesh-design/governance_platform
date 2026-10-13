"""Shared pagination for list endpoints. Totals travel in the X-Total-Count header so the JSON body
stays an array (backward compatible) and nothing is silently truncated."""
from fastapi import Response

DEFAULT_PAGE_SIZE = 200
MAX_PAGE_SIZE = 1000


async def paged(coll, query, sort, response: Response, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE):
    page = max(1, page)
    page_size = min(max(1, page_size), MAX_PAGE_SIZE)
    response.headers["X-Total-Count"] = str(await coll.count_documents(query))
    response.headers["X-Page"] = str(page)
    response.headers["X-Page-Size"] = str(page_size)
    cur = coll.find(query, {"_id": 0})
    if sort:
        cur = cur.sort(sort)
    return await cur.skip((page - 1) * page_size).limit(page_size).to_list(page_size)
