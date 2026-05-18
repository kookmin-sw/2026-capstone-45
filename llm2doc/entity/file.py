from uuid import UUID
from sqlalchemy import Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from llm2doc.entity.base import Base


class File(Base):
    __tablename__ = "file"

    file_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    extension: Mapped[str] = mapped_column(Text, nullable=False)
