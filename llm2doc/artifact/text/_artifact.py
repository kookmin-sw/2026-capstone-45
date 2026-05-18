from pydantic import BaseModel


class TextArtifact(BaseModel):
    content_markdown: str
