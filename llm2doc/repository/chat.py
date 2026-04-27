from io import IOBase
from typing import Iterable
from beartype import beartype
from sqlalchemy.ext.asyncio import AsyncSession

from llm2doc.entity import Chat, ChatSource
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
