import asyncio
import json
import logging

from uuid import UUID
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.exc import NoResultFound, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine
from pydantic import BaseModel

from llm2doc.context.pipeline import PipelineContext
from llm2doc.context.write import WriteContext
from llm2doc.debug_trace import GenerationTracer, read_chat_logs, resolve_chat_log_file
from llm2doc.dependency import WithDB, WithThreadPool
from llm2doc.entity import Chat
from llm2doc.entity.message import MessageDepth
from llm2doc.passage_visual_backfill import write_passage_visual_report_for_chat
from llm2doc.repository.chat import (
    append_chat_message,
    create_chat,
    delete_chat,
    list_chat,
    load_chat_message_all,
    load_rendered_document,
)
from llm2doc.repository.document import check_document_exists, is_all_documents_completed
from llm2doc.repository.file import get_file_path
from llm2doc.util import validate_type


router = APIRouter(prefix="/chats")


async def _run_create_document(ctx: WriteContext, query: str):
    from llm2doc.create_document import create_document

    try:
        await create_document(ctx, query)
    except Exception as exc:
        logging.exception("Failed to create document for chat_id=%s", ctx.chat_id)
        if ctx.tracer is not None:
            ctx.tracer.update_summary(status="failed", error_type=type(exc).__name__, error=str(exc))
        async with ctx.pipeline_ctx.with_db() as db:
            await append_chat_message(
                db,
                ctx.chat_id,
                MessageDepth.TRACE,
                json.dumps(
                    {
                        "type": "run_failed",
                        "component": "create_document",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                ),
            )


class CreateChatRequest(BaseModel):
    target_doc: int
    source_docs: list[int]
    query: str


class ChatListEntry(BaseModel):
    chat_id: int
    display_name: str
    has_render: bool


class ChatListResponse(BaseModel):
    chats: list[ChatListEntry]


class ChatMessageEntry(BaseModel):
    message_id: int
    depth: MessageDepth
    content: str
    is_markdown: bool
    extra_content: str | None


class ChatDetailResponse(BaseModel):
    display_name: str
    has_render: bool
    progress: float | None
    target_doc: int
    source_docs: list[int]
    messages: list[ChatMessageEntry]


class DeleteChatResponse(BaseModel):
    status: str


@router.post("")
async def create_chat_route(db: WithDB, thread_pool: WithThreadPool, body: CreateChatRequest):
    all_exists = await check_document_exists(db, [body.target_doc, *body.source_docs])
    if not all_exists:
        raise HTTPException(404, "document not found")

    all_ready = await is_all_documents_completed(db, [body.target_doc, *body.source_docs])
    if not all_ready:
        logging.warning(
            "Creating chat with documents that are not marked completed; artifact build will run in background. "
            "target_doc=%s source_docs=%s",
            body.target_doc,
            body.source_docs,
        )

    display_name = body.query.strip()[:32].strip()

    chat_id = await create_chat(db, display_name, target_doc=body.target_doc, source_docs=body.source_docs)
    tracer = GenerationTracer.for_chat(chat_id)
    tracer.update_summary(status="created", chat_id=chat_id, query=body.query)

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
        tracer=tracer,
    )

    asyncio.create_task(_run_create_document(ctx, body.query))

    return {"chat_id": chat_id}


@router.get("/{chat_id}/logs")
async def get_chat_logs(chat_id: int):
    return read_chat_logs(chat_id)


@router.get("/{chat_id}/logs/file")
async def get_chat_log_file(chat_id: int, path: str = Query(..., min_length=1)):
    try:
        file_path = resolve_chat_log_file(chat_id, path)
    except ValueError:
        raise HTTPException(400, "invalid log path")
    except FileNotFoundError:
        raise HTTPException(404, "log file not found")

    media_type_by_suffix = {
        ".html": "text/html",
        ".json": "application/json",
        ".jsonl": "application/x-ndjson",
        ".png": "image/png",
    }
    media_type = media_type_by_suffix.get(file_path.suffix.lower(), "text/plain")
    return FileResponse(file_path, media_type=media_type)


@router.post("/{chat_id}/logs/passage-visual")
async def create_chat_passage_visual_report(db: WithDB, chat_id: int):
    engine = validate_type(db.bind, AsyncEngine)
    try:
        paths = await write_passage_visual_report_for_chat(engine, chat_id)
    except ValueError as exc:
        message = str(exc)
        if "chat not found" in message:
            raise HTTPException(404, message)
        raise HTTPException(400, message)
    return {"paths": paths}


@router.get("")
async def get_chat_list(db: WithDB):
    chats: list[ChatListEntry] = []

    async for now in list_chat(db):
        chats.append(
            ChatListEntry(
                chat_id=now.chat_id,
                display_name=now.display_name,
                has_render=now.rendered_file_id is not None,
            )
        )

    return ChatListResponse(chats=chats)


@router.get("/{chat_id}")
async def get_chat_detail(db: WithDB, chat_id: int):
    try:
        chat = await db.get_one(Chat, chat_id)
    except NoResultFound:
        raise HTTPException(404, "chat not found")

    source_docs = (await db.execute(chat.source_docs.select())).scalars().all()

    def load_file(file_id: UUID):
        try:
            with open(get_file_path(file_id), "rt", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    # TODO: message pagination
    messages: list[ChatMessageEntry] = []

    async for msg in load_chat_message_all(db, chat_id):
        if msg.content_file_id is not None:
            file_content = await asyncio.to_thread(load_file, msg.content_file_id)
        else:
            file_content = None

        messages.append(
            ChatMessageEntry(
                message_id=msg.message_id,
                depth=msg.depth,
                content=msg.content_text,
                is_markdown=msg.is_markdown,
                extra_content=file_content,
            )
        )

    return ChatDetailResponse(
        display_name=chat.display_name,
        has_render=chat.rendered_file_id is not None,
        progress=None,
        target_doc=chat.target_doc_id,
        source_docs=[x.doc_id for x in source_docs],
        messages=messages,
    )


@router.delete("/{chat_id}", response_model=DeleteChatResponse)
async def delete_chat_route(db: WithDB, chat_id: int):
    try:
        await delete_chat(db, chat_id)
    except IntegrityError:
        raise HTTPException(400, "Cannot delete chat because some associated files are still in use.")

    return DeleteChatResponse(status="ok")


@router.get("/{chat_id}/render")
async def get_chat_rendered_document(db: WithDB, chat_id: int):
    file_id = await load_rendered_document(db, chat_id)
    if file_id is None:
        raise HTTPException(500, "document not yet ready")

    file_path = get_file_path(file_id)

    return FileResponse(file_path, media_type="text/json")
