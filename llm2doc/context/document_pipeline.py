import enum
import asyncio

from dataclasses import dataclass
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


class DocumentPipelineStage(enum.IntEnum):
    OCR_WHOLE_DOCUMENT = 1
    """PaddleOCR-VL을 이용해 문서 전체를 OCR하는 단계"""

    EXTRACT_STYLE = 2
    """Tesseract를 이용해 각 블록별 스타일 추출하는 단계"""


@dataclass
class DocumentPipeline:
    loop: asyncio.AbstractEventLoop
    engine: AsyncEngine

    doc_id: int
    stage: DocumentPipelineStage

    @asynccontextmanager
    async def with_db(self):
        async with AsyncSession(self.engine) as sess:
            async with sess.begin():
                yield sess
