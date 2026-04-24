from sqlalchemy import select, func
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from llm2doc.dto.document import DocumentListEntry
from llm2doc.entity import Document, DocumentImage, File


async def list_all_documents(db: AsyncSession) -> list[DocumentListEntry]:
    pages_cnt = (
        select(func.count(DocumentImage.file_id))
        .where(DocumentImage.doc_id == Document.doc_id)
        .correlate(Document)
        .scalar_subquery()
        .label("pages_cnt")
    )

    stmt = select(
        Document.doc_id, Document.display_name, pages_cnt, Document.process_status, Document.process_log
    ).order_by(Document.doc_id.desc())

    result: list[DocumentListEntry] = []

    async for row in await db.stream(stmt):
        print(row)
        result.append(
            DocumentListEntry(
                doc_id=row.doc_id,
                display_name=row.display_name,
                pages_cnt=row.pages_cnt,
                process_status=row.process_status,
                process_log=row.process_log,
            )
        )

    return result


async def load_document(db: AsyncSession, doc_id: int) -> Document:
    try:
        return await db.get_one(Document, doc_id)
    except NoResultFound:
        raise HTTPException(404, "no such document found")


async def load_document_image(db: AsyncSession, doc: Document, page: int) -> File:
    stmt = (
        select(File)
        .join(DocumentImage, File.file_id == DocumentImage.file_id)
        .where(DocumentImage.doc_id == doc.doc_id)
        .order_by(DocumentImage.display_order, DocumentImage.file_id)
        .limit(1)
        .offset(page)
    )

    result = await db.execute(stmt)
    try:
        return result.scalar_one()
    except NoResultFound:
        raise HTTPException(404, "no such page found")
