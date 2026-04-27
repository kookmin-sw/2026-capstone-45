import asyncio

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncEngine
from pydantic import BaseModel

from llm2doc.context.pipeline import PipelineContext
from llm2doc.context.write import WriteContext
from llm2doc.dependency import WithDB, WithThreadPool
from llm2doc.util import validate_type


router = APIRouter(prefix="/chats")


class CreateChatRequest(BaseModel):
    target_doc: int
    source_docs: list[int]
    query: str


@router.post("")
async def create_chat(db: WithDB, thread_pool: WithThreadPool, body: CreateChatRequest):
    from llm2doc.create_document import create_document

    pipeline_ctx = PipelineContext(
        loop=asyncio.get_running_loop(),
        engine=validate_type(db.bind, AsyncEngine),
        thread_pool=thread_pool,
    )
    ctx = WriteContext(
        pipeline_ctx=pipeline_ctx,
        chat_id=-123,
        target_doc_id=body.target_doc,
        source_doc_ids=body.source_docs,
    )

    await create_document(ctx, body.query)
