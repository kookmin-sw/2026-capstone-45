from sqlalchemy.ext.asyncio import AsyncEngine

from .document_image import DocumentImage
from .document_log import DocumentLog
from .document import Document, DocumentStatus
from .file import File


async def init_schema(db: AsyncEngine):
    from .base import Base

    async with db.connect() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.commit()


__all__ = ["DocumentImage", "DocumentLog", "Document", "DocumentStatus", "File", "init_schema"]
