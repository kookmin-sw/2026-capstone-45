import asyncio
import json

from typing import Sequence
from dataclasses import dataclass

from llm2doc.context.pipeline import PipelineContext
from llm2doc.entity.message import MessageDepth
from llm2doc.repository.chat import append_chat_message


@dataclass(frozen=True)
class WriteContext:
    """문서 작성시 주어지는 컨텍스트"""

    pipeline_ctx: PipelineContext
    chat_id: int
    target_doc_id: int
    source_doc_ids: Sequence[int]

    async def append_log(self, message: str, file: str | bytes | None = None):
        async with self.pipeline_ctx.with_db() as db:
            await append_chat_message(db, self.chat_id, MessageDepth.INTERNAL, message, file)

    def append_log_sync(self, message: str, file: str | bytes | None = None):
        asyncio.run_coroutine_threadsafe(self.append_log(message, file), loop=self.pipeline_ctx.loop)

    async def append_trace(self, message: object):
        msg = json.dumps(message)

        async with self.pipeline_ctx.with_db() as db:
            await append_chat_message(db, self.chat_id, MessageDepth.TRACE, msg, None)

    def append_trace_sync(self, message: object):
        asyncio.run_coroutine_threadsafe(self.append_trace(message), loop=self.pipeline_ctx.loop)
