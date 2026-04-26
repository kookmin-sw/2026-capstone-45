import enum

from uuid import UUID
from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, WriteOnlyMapped
from llm2doc.entity.base import Base
from llm2doc.entity.document_image import DocumentImage
from llm2doc.entity.document_log import DocumentLog
from llm2doc.entity.file import File


class DocumentStatus(enum.IntEnum):
    PENDING = 1
    PROCESSING = 2
    COMPLETED = 3
    ERROR = 4


class Document(Base):
    __tablename__ = "document"

    doc_id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    original_file_id: Mapped[UUID] = mapped_column(ForeignKey("file.file_id", onupdate="CASCADE"), nullable=False)
    process_status: Mapped[DocumentStatus] = mapped_column(Integer, nullable=False, default=DocumentStatus.PENDING)
    process_log: Mapped[str] = mapped_column(Text, nullable=False, default="")

    original_file: Mapped["File"] = relationship("File", lazy="raise_on_sql")
    images: WriteOnlyMapped["DocumentImage"] = relationship(
        "DocumentImage", lazy="write_only", back_populates="doc", cascade="all, delete-orphan", passive_deletes=True
    )
    logs: WriteOnlyMapped["DocumentLog"] = relationship(
        "DocumentLog",
        lazy="write_only",
        back_populates="doc",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by=DocumentLog.doc_log_id,
    )
