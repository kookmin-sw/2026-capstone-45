from io import IOBase
from beartype import beartype
from sqlalchemy.ext.asyncio import AsyncSession

from llm2doc.entity.message import Message, MessageDepth
from llm2doc.repository.file import create_file


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


async def append_chat_internal_log(
    db: AsyncSession,
    chat_id: int,
    text: str,
    file: str | bytes | IOBase | None = None,
    *,
    is_markdown: bool = False,
):
    await append_chat_message(db, chat_id, MessageDepth.INTERNAL, text, file, is_markdown=is_markdown)
