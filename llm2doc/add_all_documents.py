import os
import uuid
import shutil
import logging
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from llm2doc.artifact.run import build_artifact
from llm2doc.server import lifespan
from llm2doc.entity import File as FileRow, Document
from llm2doc.route.document import create_document_worker
from llm2doc.repository.file import get_file_path
from llm2doc.util import validate_type


def find_pdf_files(data_dir: str = "data") -> list[str]:
    """Scan data_dir (non-recursive) for PDF files."""
    pdf_files: list[str] = []
    try:
        for entry in os.scandir(data_dir):
            if entry.is_file() and entry.name.lower().endswith(".pdf"):
                pdf_files.append(entry.path)
    except FileNotFoundError:
        pass
    return sorted(pdf_files)


async def add_all_documents(data_dir: str = "data", build_artifacts: bool = True) -> None:
    """Scan data directory for PDF files and add them to the database."""
    pdf_files = find_pdf_files(data_dir)

    if not pdf_files:
        print(f"No PDF files found in '{data_dir}'")
        return

    print(f"Found {len(pdf_files)} PDF file(s) in '{data_dir}'")

    async with lifespan(None) as context:
        engine = validate_type(context["db"], AsyncEngine)
        doc_ids: list[int] = []

        async with AsyncSession(engine) as db:
            for i, pdf_path in enumerate(pdf_files, 1):
                print(f"[{i}/{len(pdf_files)}] Adding: {pdf_path}")

                file_id = uuid.uuid4()

                shutil.copy2(pdf_path, get_file_path(file_id))

                # Create File and Document rows
                async with db.begin():
                    file_row = FileRow(file_id=file_id, mime_type="application/pdf", extension="pdf")
                    doc = Document(display_name=os.path.basename(pdf_path), original_file=file_row)
                    db.add(doc)
                    await db.flush()

                    doc_id = doc.doc_id
                    assert doc_id is not None

                # Process PDF (render pages to images)
                await create_document_worker(engine, doc_id, file_id, "pdf", False)

                doc_ids.append(doc_id)

            if build_artifacts:
                await build_artifact(engine, doc_ids)

    print(f"Done. {len(pdf_files)} PDF file(s) processed.")
