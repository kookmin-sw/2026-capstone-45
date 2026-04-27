import asyncio
import shutil

from io import IOBase
from uuid import UUID, uuid4
from typing import overload
from beartype import beartype
from sqlalchemy.ext.asyncio import AsyncSession

from llm2doc.entity import File


def get_file_path(file_id: UUID) -> str:
    return f"file/{file_id}"


@overload
async def read_file(file_id: UUID, encoding: None = ...) -> bytes: ...


@overload
async def read_file(file_id: UUID, encoding: str) -> str: ...


async def read_file(file_id: UUID, encoding: str | None = None) -> bytes | str:
    mode = "rb" if encoding is None else "rt"

    def read_file_inner():
        with open(get_file_path(file_id), mode, encoding=encoding) as f:
            return f.read()

    return await asyncio.to_thread(read_file_inner)


@beartype
async def create_file(db: AsyncSession, content: str | bytes | IOBase, mime_type: str = "application/octet-stream"):
    def write_file():
        file_id = uuid4()
        with open(get_file_path(file_id), "wb") as f:
            if isinstance(content, bytes):
                f.write(content)
            elif isinstance(content, str):
                f.write(content.encode("utf-8"))
            else:
                shutil.copyfileobj(content, f)

        return file_id

    file_id = await asyncio.to_thread(write_file)

    file_entity = File(file_id=file_id, mime_type=mime_type)
    db.add(file_entity)

    return file_entity
