import asyncio
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncEngine
from concurrent.futures import ThreadPoolExecutor

from llm2doc.create_document import create_document
from llm2doc.context.pipeline import PipelineContext
from llm2doc.context.write import WriteContext
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
        db = validate_type(context["db"], AsyncEngine)
        thread_pool = validate_type(context["thread_pool"], ThreadPoolExecutor)

        pipeline_ctx = PipelineContext(
            loop=asyncio.get_running_loop(),
            engine=db,
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
            return

        ctx = WriteContext(
            pipeline_ctx=pipeline_ctx,
            chat_id=-123,
            target_doc_id=target_doc,
            source_doc_ids=source_docs,
        )

        await create_document(ctx, query)


if __name__ == "__main__":
    asyncio.run(main())
