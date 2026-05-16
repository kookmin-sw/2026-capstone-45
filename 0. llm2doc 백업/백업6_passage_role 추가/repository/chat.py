from io import IOBase
from typing import Iterable
from beartype import beartype
from fastapi import HTTPException
from sqlalchemy import select, update, delete
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from llm2doc.entity import Chat, ChatSource, File
from llm2doc.entity.message import Message, MessageDepth
from llm2doc.repository.file import create_file


async def create_chat(db: AsyncSession, name: str, target_doc: int, source_docs: Iterable[int]):
    sources: list[ChatSource] = []
    for src_doc_id in source_docs:
        sources.append(ChatSource(doc_id=src_doc_id))

    chat = Chat(display_name=name, target_doc_id=target_doc, source_docs=sources)
    db.add(chat)
    await db.flush([chat])

    return chat.chat_id


async def list_chat(db: AsyncSession):
    stmt = select(Chat).order_by(Chat.chat_id.desc())

    result = await db.stream(stmt)
    async for row in result.scalars():
        yield row


@beartype
async def append_chat_message(
    db: AsyncSession,
    chat_id: int,
    depth: MessageDepth,
    text: str,
    file: str | bytes | IOBase | None = None,
    *,
    is_markdown: bool = False,
):
    if file is not None:
        file_entity = await create_file(db, file)
    else:
        file_entity = None

    msg = Message(
        chat_id=chat_id,
        depth=depth,
        content_text=text,
        content_file=file_entity,
        is_markdown=is_markdown,
    )

    db.add(msg)


async def load_chat_message_all(db: AsyncSession, chat_id: int):
    stmt = select(Message).where(Message.chat_id == chat_id).order_by(Message.message_id)

    result = await db.stream_scalars(stmt)
    async for row in result:
        yield row


async def save_rendered_document(db: AsyncSession, chat_id: int, data: str):
    file = await create_file(db, data, mime_type="text/json")

    stmt = update(Chat).where(Chat.chat_id == chat_id).values(rendered_file_id=file.file_id)

    await db.execute(stmt)


async def load_rendered_document(db: AsyncSession, chat_id: int):
    try:
        result = await db.get_one(Chat, chat_id)
    except NoResultFound:
        raise HTTPException(404, "no chat found")

    return result.rendered_file_id


async def delete_chat(db: AsyncSession, chat_id: int):
    chat = await db.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(404, "chat not found")

    if chat.rendered_file_id is not None:
        stmt = delete(File).where(File.file_id == chat.rendered_file_id)
        await db.execute(stmt)

    await db.delete(chat)
