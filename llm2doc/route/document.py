import os
import uuid
import shutil
import asyncio
import fitz
import logging

from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any
from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from pydantic import BaseModel

from llm2doc.artifact.run import build_artifact
from llm2doc.util import validate_type
from llm2doc.dependency import WithDB, WithThreadPool
from llm2doc.entity import DocumentStatus, File as FileRow, Document, DocumentImage
from llm2doc.dto.document import DocumentListEntry
from llm2doc.repository.artifact import clear_artifacts
from llm2doc.repository.document import list_all_documents, load_document, load_document_image


router = APIRouter(prefix="/documents")


class ListDocumentResponse(BaseModel):
    docs: list[DocumentListEntry]


@router.get("")
async def list_document(db: WithDB):
    docs = await list_all_documents(db)
    return ListDocumentResponse(docs=docs)


@router.get("/{doc_id}/image/{page}")
async def get_document_image(db: WithDB, doc_id: int, page: int):
    doc = await load_document(db, doc_id)
    file = await load_document_image(db, doc, page)

    return FileResponse(f"file/{file.file_id}", media_type=file.mime_type)


@router.post("")
async def create_document(file: Annotated[UploadFile, File()], db: WithDB):
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Uploaded file lacks filename")

    file_ext = ""
    if "." in file.filename:
        file_ext = file.filename.rsplit(".", maxsplit=1)[1].lower()

    if len(file_ext) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file does not have file extension")

    if file_ext == "pdf":
        file_type = "pdf"
        mime_type = "application/pdf"
    elif file_ext in ("md", "txt", "html", "htm", "tex", "svg"):
        file_type = "text"
        mime_type = "text/plain"
        raise HTTPException(status_code=400, detail="Unsupported file type yet")
    elif file_ext in ("avif", "bmp", "gif", "heic", "jpeg", "jpg", "png", "tiff", "tif", "webp"):
        file_type = "image"
        mime_type = f"image/{file_ext}"
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    file_id = uuid.uuid4()

    def copy_file():
        os.makedirs("file", exist_ok=True)

        with open(f"file/{file_id}", "wb") as f:
            shutil.copyfileobj(file.file, f)

    await asyncio.to_thread(copy_file)

    file_row = FileRow(file_id=file_id, mime_type=mime_type)
    doc = Document(display_name=file.filename, original_file=file_row)
    db.add(doc)
    await db.flush()

    doc_id = validate_type(await doc.awaitable_attrs.doc_id, int)
    await asyncio.create_task(create_document_worker(db.bind, doc_id, file_id, file_type, True))

    return {"id": doc_id}


@router.post("/{doc_id}/artifacts/rebuild")
async def rebuild_artifact(doc_id: int, db: WithDB):
    from llm2doc.artifact.run import build_artifact

    await clear_artifacts(db, doc_id)

    engine = validate_type(db.bind, AsyncEngine)
    await build_artifact(engine, [doc_id])

    return {}


async def create_document_worker(engine: Any, doc_id: int, file_id: uuid.UUID, file_type: str, build_artifacts: bool):
    engine = validate_type(engine, AsyncEngine)

    async def add_images(img_ids: list[uuid.UUID]):
        async with AsyncSession(engine) as sess:
            async with sess.begin():
                doc = await sess.get_one(Document, doc_id)

                # FIXME: Fake MIME type
                for i, img_id in enumerate(img_ids):
                    file = FileRow(file_id=img_id, mime_type="image/png")
                    doc.images.add(DocumentImage(file=file, display_order=i + 1))

    async def update_log_status(status: DocumentStatus, log: str):
        async with AsyncSession(engine) as sess:
            async with sess.begin():
                doc = await sess.get_one(Document, doc_id)

                doc.process_status = status
                doc.process_log += f"{log}\n"

    def serialize_pdf():
        img_ids: list[uuid.UUID] = []

        pdf_file = fitz.Document(f"file/{file_id}", filetype="pdf")
        for i in range(len(pdf_file)):
            page = pdf_file[i]

            img_id = uuid.uuid4()
            img_ids.append(img_id)

            img = page.get_pixmap(dpi=300)
            img.save(f"file/{img_id}", output="PNG")

        return img_ids

    try:
        if file_type == "image":
            img_ids = [file_id]
        elif file_type == "pdf":
            img_ids = await asyncio.to_thread(serialize_pdf)
        else:
            raise RuntimeError(f"Invalid {file_type=}")

        await add_images(img_ids)

        await update_log_status(DocumentStatus.PROCESSING, f"Saved {len(img_ids)} images.")

        if build_artifacts:
            asyncio.create_task(build_artifact(engine, [doc_id]))

    except Exception as e:
        logging.exception("Failed to process uploaded document", e)
        await update_log_status(DocumentStatus.ERROR, repr(e))
        pass
