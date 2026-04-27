import asyncio

from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine
from pydantic import BaseModel

from llm2doc.context.pipeline import PipelineContext
from llm2doc.context.write import WriteContext
from llm2doc.dependency import WithDB, WithThreadPool
from llm2doc.repository.chat import create_chat
from llm2doc.repository.document import check_document_exists
from llm2doc.util import validate_type


router = APIRouter(prefix="/chats")


class CreateChatRequest(BaseModel):
    target_doc: int
    source_docs: list[int]
    query: str


@router.post("")
async def create_chat_route(db: WithDB, thread_pool: WithThreadPool, body: CreateChatRequest):
    from llm2doc.create_document import create_document

    all_exists = await check_document_exists(db, [body.target_doc, *body.source_docs])
    if not all_exists:
        raise HTTPException(404, "document not found")

    display_name = body.query.strip()[:32].strip()

    chat_id = await create_chat(db, display_name, target_doc=body.target_doc, source_docs=body.source_docs)

    pipeline_ctx = PipelineContext(
        loop=asyncio.get_running_loop(),
        engine=validate_type(db.bind, AsyncEngine),
        thread_pool=thread_pool,
    )
    ctx = WriteContext(
        pipeline_ctx=pipeline_ctx,
        chat_id=chat_id,
        target_doc_id=body.target_doc,
        source_doc_ids=body.source_docs,
    )

    await create_document(ctx, body.query)
