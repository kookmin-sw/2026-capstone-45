import os

from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, APIRouter
from fastapi.responses import FileResponse, PlainTextResponse
from dotenv import load_dotenv
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine

from llm2doc.entity import init_schema
from llm2doc.route.chat import router as chat
from llm2doc.route.document import router as document
from llm2doc.route.font import router as font


def create_db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///db.sqlite3", echo=True)

    def prepare_connection(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA cache_size = -20000")
        cursor.execute("PRAGMA temp_store = MEMORY")
        cursor.execute("PRAGMA busy_timeout = 5000")
        cursor.close()

    event.listen(engine.sync_engine, "connect", prepare_connection)
    return engine


load_dotenv(override=True)


@asynccontextmanager
async def lifespan(app: FastAPI | None = None):
    db = create_db_engine()
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


api_router.include_router(document)
api_router.include_router(font)
api_router.include_router(chat)
app.include_router(api_router)


@app.api_route("/{path_name:path}", methods=["GET"])
def catch_all(path_name: str):
    file_path = f"web_static/{path_name}"

    if os.path.isfile(file_path):
        return FileResponse(file_path)

    if os.path.isfile("web_static/index.html"):
        return FileResponse("web_static/index.html", status_code=404)

    return PlainTextResponse("Not Found", 404)
