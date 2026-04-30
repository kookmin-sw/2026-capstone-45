import asyncio

from dataclasses import dataclass
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from concurrent.futures import ThreadPoolExecutor


@dataclass(frozen=True)
class PipelineContext:
    loop: asyncio.AbstractEventLoop
    engine: AsyncEngine
    thread_pool: ThreadPoolExecutor

    @asynccontextmanager
    async def with_db(self):
        async with AsyncSession(self.engine) as sess:
            async with sess.begin():
                yield sess
