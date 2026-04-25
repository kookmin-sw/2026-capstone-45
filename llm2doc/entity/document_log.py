from uuid import UUID
from typing import TYPE_CHECKING, Optional
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Index, ForeignKey

from llm2doc.entity.base import Base

if TYPE_CHECKING:
    from llm2doc.entity.document import Document
    from llm2doc.entity.file import File


class DocumentLog(Base):
    __tablename__ = "document_log"

    doc_log_id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("document.doc_id"))

    content_text: Mapped[str] = mapped_column()
    content_file_id: Mapped[UUID] = mapped_column(ForeignKey("file.file_id"))

    doc: Mapped["Document"] = relationship("Document", lazy="raise_on_sql")
    content_file: Mapped[Optional["File"]] = relationship("File", lazy="raise_on_sql")

    __table_args__ = (
        Index("document_log_idx_doc_id", "doc_id"),
        Index("document_log_idx_content_file_id", "content_file_id"),
    )
