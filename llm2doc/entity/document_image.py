from uuid import UUID
from typing import TYPE_CHECKING
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Index, ForeignKey

from llm2doc.entity.base import Base

if TYPE_CHECKING:
    from llm2doc.entity.document import Document
    from llm2doc.entity.file import File


class DocumentImage(Base):
    __tablename__ = "document_image"

    doc_id: Mapped[int] = mapped_column(ForeignKey("document.doc_id", onupdate="CASCADE"), primary_key=True)
    file_id: Mapped[UUID] = mapped_column(ForeignKey("file.file_id", onupdate="CASCADE"), primary_key=True)
    display_order: Mapped[int] = mapped_column(nullable=False)

    doc: Mapped["Document"] = relationship("Document", lazy="raise_on_sql", back_populates="images")
    file: Mapped["File"] = relationship("File", lazy="raise_on_sql")

    __table_args__ = (Index("document_image_idx_display_order", "display_order", "file_id"),)
