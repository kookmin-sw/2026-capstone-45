from typing import TypeAlias, Annotated
from fastapi import Request, Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from llm2doc.util import validate_type


async def with_db(request: Request):
    db = validate_type(request.state.db, AsyncEngine)

    async with AsyncSession(db) as sess:
        yield sess


WithDB: TypeAlias = Annotated[AsyncSession, Depends(with_db)]
