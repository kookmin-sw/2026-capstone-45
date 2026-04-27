import enum

from uuid import UUID
from typing import TYPE_CHECKING, Optional
from sqlalchemy import ForeignKey, Integer, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from llm2doc.entity.base import Base

if TYPE_CHECKING:
    from llm2doc.entity.chat import Chat
    from llm2doc.entity.file import File


class MessageDepth(enum.IntEnum):
    USER = 10
    """유저에게 바로 보이는 메시지"""

    ERROR = 20
    """처리중 발생한 오류"""

    WARN = 30
    """처리중 발생한 경고"""

    THRESHOLD_VISIBLE_DEFAULT = 40
    """depth가 이 값 미만이면 유저에게 기본으로 보임"""

    REASONING = 50
    """LLM reasoning과 tool call"""

    INTERNAL = 60
    """시스템 내부적으로 생성한 로그"""

    TRACE = 70
    """JSON 형태로 된 trace 로그"""


class Message(Base):
    __tablename__ = "message"

    message_id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chat.chat_id", onupdate="CASCADE"), nullable=False)
    depth: Mapped[MessageDepth] = mapped_column(nullable=False)

    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_file_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("file.file_id", onupdate="CASCADE"))

    is_markdown: Mapped[bool] = mapped_column(Boolean, nullable=False)

    chat: Mapped["Chat"] = relationship("Chat", lazy="raise_on_sql", back_populates="messages")
    content_file: Mapped[Optional["File"]] = relationship("File", lazy="raise_on_sql")
