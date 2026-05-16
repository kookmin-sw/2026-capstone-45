from sqlalchemy import VARCHAR, Text
from sqlalchemy.orm import Mapped, mapped_column

from llm2doc.entity.base import Base


class Config(Base):
    __tablename__ = "config"

    key: Mapped[str] = mapped_column(VARCHAR(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
