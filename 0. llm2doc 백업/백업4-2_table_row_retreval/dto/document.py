from pydantic import BaseModel, ConfigDict, field_serializer

from llm2doc.entity import DocumentStatus


class DocumentListEntry(BaseModel):
    """문서 목록을 가져올 때 쓰는 모델"""

    model_config = ConfigDict(from_attributes=True)

    doc_id: int
    display_name: str
    pages_cnt: int
    process_status: DocumentStatus
    process_log: str

    @field_serializer("process_status")
    def serialize_status(self, status: DocumentStatus, _info):
        return status.name.lower()
