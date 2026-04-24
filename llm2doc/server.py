import os

from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, APIRouter
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import create_async_engine

from llm2doc.entity import init_schema
from llm2doc.route.document import router as document
from llm2doc.route.font import router as font


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = create_async_engine("sqlite+aiosqlite://", echo=True)
    thread_pool = ThreadPoolExecutor(max_workers=1)

    try:
        await init_schema(db)

        yield {
            "db": db,
            "thread_pool": thread_pool,
        }
    finally:
        thread_pool.shutdown(cancel_futures=True)
        await db.dispose()


app = FastAPI(lifespan=lifespan)
api_router = APIRouter(prefix="/api")


@api_router.get("/health")
async def health():
    return {"health": "ok"}


@api_router.get("/rendered/{doc_id}")
async def rendered_document(doc_id: str):
    path = f"./rendered/{doc_id}.json"
    # if not os.path.exists(path):
    #     raise HTTPException(status_code=404)

    return FileResponse("debug_finish.json")


api_router.include_router(document)
api_router.include_router(font)
app.include_router(api_router)


@app.api_route("/{path_name:path}", methods=["GET"])
def catch_all(path_name: str):
    file_path = f"web_static/{path_name}"

    if os.path.isfile(file_path):
        return FileResponse(file_path)

    if os.path.isfile("web_static/index.html"):
        return FileResponse("web_static/index.html", status_code=404)

    return PlainTextResponse("Not Found", 404)
