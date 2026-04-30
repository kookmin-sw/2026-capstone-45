from typing import TYPE_CHECKING
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Index, ForeignKey, VARCHAR

from llm2doc.entity.base import Base

if TYPE_CHECKING:
    from llm2doc.entity.document import Document


class Artifact(Base):
    __tablename__ = "artifact"

    artifact_id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = mapped_column(
        ForeignKey("document.doc_id", onupdate="CASCADE", ondelete="CASCADE"), nullable=False
    )
    artifact_name: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)

    content_json: Mapped[str] = mapped_column(nullable=False)

    doc: Mapped["Document"] = relationship("Document", lazy="raise_on_sql", back_populates="artifacts")

    __table_args__ = (Index("artifact_doc_id", "doc_id", "artifact_name"),)
