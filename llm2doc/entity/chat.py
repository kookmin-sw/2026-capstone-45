from typing import TYPE_CHECKING, Optional
from uuid import UUID
from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, WriteOnlyMapped
from llm2doc.entity.base import Base
from llm2doc.entity.message import Message
from llm2doc.entity.chat_source import ChatSource

if TYPE_CHECKING:
    from llm2doc.entity.document import Document
    from llm2doc.entity.file import File


class Chat(Base):
    __tablename__ = "chat"

    chat_id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    target_doc_id: Mapped[int] = mapped_column(ForeignKey("document.doc_id", onupdate="CASCADE"), nullable=False)

    rendered_file_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("file.file_id", onupdate="CASCADE"), nullable=True
    )

    target_doc: Mapped["Document"] = relationship("Document", lazy="raise_on_sql")
    source_docs: WriteOnlyMapped["ChatSource"] = relationship(
        "ChatSource",
        lazy="write_only",
        back_populates="chat",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by=ChatSource.doc_id,
    )
    rendered_file: Mapped["File"] = relationship("File", lazy="raise_on_sql")
    messages: WriteOnlyMapped["Message"] = relationship(
        "Message",
        lazy="write_only",
        back_populates="chat",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by=Message.message_id,
    )
