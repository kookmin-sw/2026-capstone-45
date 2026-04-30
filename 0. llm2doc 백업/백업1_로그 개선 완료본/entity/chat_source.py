from typing import TYPE_CHECKING
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from llm2doc.entity.base import Base

if TYPE_CHECKING:
    from llm2doc.entity.document import Document
    from llm2doc.entity.chat import Chat


class ChatSource(Base):
    __tablename__ = "chat_source"

    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chat.chat_id", onupdate="CASCADE", ondelete="CASCADE"), primary_key=True
    )
    doc_id: Mapped[int] = mapped_column(ForeignKey("document.doc_id", onupdate="CASCADE"), primary_key=True)

    chat: Mapped["Chat"] = relationship("Chat", lazy="raise_on_sql", back_populates="source_docs")
    doc: Mapped["Document"] = relationship("Document", lazy="raise_on_sql")
