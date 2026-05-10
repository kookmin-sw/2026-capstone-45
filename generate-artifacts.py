import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from llm2doc.artifact.run import build_artifact
from llm2doc.repository.document import list_all_documents
from llm2doc.server import lifespan
from llm2doc.util import validate_type


async def main():
    async with lifespan(None) as life:
        engine = validate_type(life["db"], AsyncEngine)

        async with AsyncSession(engine) as db:
            async with db.begin():
                documents = await list_all_documents(db)

        doc_ids = [x.doc_id for x in documents]

        await build_artifact(engine, doc_ids)


if __name__ == "__main__":
    asyncio.run(main())
