import asyncio

from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from concurrent.futures import ThreadPoolExecutor

from llm2doc.create_document import create_document
from llm2doc.context.pipeline import PipelineContext
from llm2doc.context.write import WriteContext
from llm2doc.repository.chat import create_chat
from llm2doc.save_chat import save_chat_messages
from llm2doc.server import lifespan
from llm2doc.util import validate_type


async def main():
    load_dotenv(override=True)
    option = 3

    mapping = {
        "financial1": 3,
        "financial2": 4,
        "financial3": 5,
        "news1": 6,
    }

    async with lifespan(None) as context:
        engine = validate_type(context["db"], AsyncEngine)
        thread_pool = validate_type(context["thread_pool"], ThreadPoolExecutor)

        pipeline_ctx = PipelineContext(
            loop=asyncio.get_running_loop(),
            engine=engine,
            thread_pool=thread_pool,
        )

        if option == 0:
            query = None
            source_docs = [mapping["financial2"]]
            target_doc = mapping["financial1"]
        elif option == 1:
            query = "KMW 기업 보고서 작성해"
            source_docs = [mapping["financial2"], mapping["financial3"]]
            target_doc = mapping["financial1"]
        elif option == 2:
            query = "삼성전자 관련 데일리 브리핑 작성해 (시장 전체 말고 삼성전자만)"
            source_docs = [mapping["financial3"]]
            target_doc = mapping["financial2"]
        elif option == 3:
            query = "트럼프 관련 기사로 문서 작성해줘"
            source_docs = [mapping["news1"]]
            target_doc = mapping["financial2"]
        else:
            raise ValueError(f"invalid {option=}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        async with AsyncSession(engine) as db:
            async with db.begin():
                chat_id = await create_chat(db, timestamp, target_doc, source_docs)

        ctx = WriteContext(
            pipeline_ctx=pipeline_ctx,
            chat_id=chat_id,
            target_doc_id=target_doc,
            source_doc_ids=source_docs,
        )

        try:
            await create_document(ctx, query)
        finally:
            async with AsyncSession(engine) as db:
                await save_chat_messages(db, chat_id, f"debug_{timestamp}")


if __name__ == "__main__":
    asyncio.run(main())
