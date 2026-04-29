import asyncio
import json
import time

from typing import Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass

from llm2doc.context.pipeline import PipelineContext
from llm2doc.debug_trace import GenerationTracer
from llm2doc.entity.message import MessageDepth
from llm2doc.repository.chat import append_chat_message


@dataclass(frozen=True)
class WriteContext:
    """문서 작성시 주어지는 컨텍스트"""

    pipeline_ctx: PipelineContext
    chat_id: int
    target_doc_id: int
    source_doc_ids: Sequence[int]
    tracer: GenerationTracer | None = None

    async def append_message(self, depth: MessageDepth, message: str, is_markdown: bool = False):
        async with self.pipeline_ctx.with_db() as db:
            await append_chat_message(db, self.chat_id, depth, message, is_markdown=is_markdown)

    async def append_log(self, message: str, file: str | bytes | None = None):
        async with self.pipeline_ctx.with_db() as db:
            await append_chat_message(db, self.chat_id, MessageDepth.INTERNAL, message, file)

    def append_log_sync(self, message: str, file: str | bytes | None = None):
        asyncio.run_coroutine_threadsafe(self.append_log(message, file), loop=self.pipeline_ctx.loop)

    async def append_trace(self, message: object):
        msg = json.dumps(message, ensure_ascii=False)

        async with self.pipeline_ctx.with_db() as db:
            await append_chat_message(db, self.chat_id, MessageDepth.TRACE, msg, None)

        if self.tracer is not None:
            self.tracer.record_trace(message)

    def append_trace_sync(self, message: object):
        asyncio.run_coroutine_threadsafe(self.append_trace(message), loop=self.pipeline_ctx.loop)

    async def trace_event(
        self,
        component: str,
        event: str,
        payload: dict | None = None,
        *,
        duration_ms: float | int | None = None,
    ):
        message = {
            "type": event,
            "component": component,
            **(payload or {}),
        }
        if duration_ms is not None:
            message["duration_ms"] = duration_ms
        await self.append_trace(message)

    def trace_event_sync(
        self,
        component: str,
        event: str,
        payload: dict | None = None,
        *,
        duration_ms: float | int | None = None,
    ):
        asyncio.run_coroutine_threadsafe(
            self.trace_event(component, event, payload, duration_ms=duration_ms),
            loop=self.pipeline_ctx.loop,
        )

    def trace_file(self, relative_path: str, payload: object):
        if self.tracer is None:
            return
        if isinstance(payload, (dict, list)):
            self.tracer.write_json(relative_path, payload)
        else:
            self.tracer.write_text(relative_path, str(payload))

    @asynccontextmanager
    async def trace_step(self, component: str, event: str, payload: dict | None = None):
        started = time.perf_counter()
        await self.trace_event(component, f"{event}_started", payload)
        try:
            yield
        except Exception as exc:
            duration_ms = (time.perf_counter() - started) * 1000
            failed_payload = {
                **(payload or {}),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            if self.tracer is not None:
                self.tracer.update_summary(status="failed", error_type=type(exc).__name__, error=str(exc))
            await self.trace_event(component, f"{event}_failed", failed_payload, duration_ms=duration_ms)
            raise
        else:
            duration_ms = (time.perf_counter() - started) * 1000
            await self.trace_event(component, f"{event}_completed", payload, duration_ms=duration_ms)
