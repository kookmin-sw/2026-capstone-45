from sqlalchemy import select, insert
from sqlalchemy.exc import OperationalError, NoResultFound
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection

from .artifact import Artifact
from .config import Config
from .document_image import DocumentImage
from .document_log import DocumentLog
from .document import Document, DocumentStatus
from .file import File


DB_SCHEMA_VERSION = 3


async def create_schema(conn: AsyncConnection):
    from .base import Base

    await conn.run_sync(Base.metadata.create_all)

    stmt = insert(Config).values(key="schema_version", value=str(DB_SCHEMA_VERSION))
    await conn.execute(stmt)

    await conn.commit()


async def init_schema(db: AsyncEngine):
    async with db.connect() as conn:
        stmt = select(Config.value).where(Config.key == "schema_version").limit(1)
        try:
            result = await conn.execute(stmt)
            version = result.scalar_one()
        except (NoResultFound, OperationalError):
            # Config table or value not found; create new DB
            await create_schema(conn)
            return

        version = int(version)
        if version != DB_SCHEMA_VERSION:
            raise RuntimeError(
                f"DB 스키마 버전이 다릅니다. DB 파일을 삭제해주세요.\nDB에 저장된 버전: {version}, 현 코드의 버전: {DB_SCHEMA_VERSION}"
            )


__all__ = ["Artifact", "Config", "DocumentImage", "DocumentLog", "Document", "DocumentStatus", "File", "init_schema"]
