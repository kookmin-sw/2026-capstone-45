import os
import shutil

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from llm2doc.entity.chat import Chat
from llm2doc.entity.message import Message, MessageDepth
from llm2doc.repository.file import get_file_path


async def save_chat_messages(db: AsyncSession, chat_id: int, save_path: str):
    os.makedirs(save_path, exist_ok=True)

    stmt = select(Message).where(Message.chat_id == chat_id).order_by(Message.message_id)
    messages = await db.stream_scalars(stmt)

    final_path = os.path.join(save_path, "final.json")
    trace_path = os.path.join(save_path, "trace.jsonl")
    messages_path = os.path.join(save_path, "messages.md")

    with open(trace_path, "w", encoding="utf-8") as f_trace, open(messages_path, "w", encoding="utf-8") as f_messages:
        async for msg in messages:
            if msg.depth == MessageDepth.TRACE:
                f_trace.write(msg.content_text.strip() + "\n")
            else:
                f_messages.write(f"## {msg.depth.name}\n\n")
                if msg.is_markdown:
                    f_messages.write(msg.content_text + "\n\n")
                else:
                    f_messages.write(f"```\n{msg.content_text}\n```\n\n")

    stmt = select(Chat.rendered_file_id).where(Chat.chat_id == chat_id)
    rendered_file_id = (await db.execute(stmt)).scalar_one()

    if rendered_file_id is not None:
        shutil.copyfile(get_file_path(rendered_file_id), final_path)
