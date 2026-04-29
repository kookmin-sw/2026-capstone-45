import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from llm2doc.server import lifespan
from llm2doc.repository.artifact import clear_artifacts
from llm2doc.util import validate_type


async def main():
    artifact_names = ["SemanticArtifact"]

    async with lifespan(None) as life:
        engine = validate_type(life["db"], AsyncEngine)

        async with AsyncSession(engine) as db:
            async with db.begin():
                await clear_artifacts(db, None, artifact_names)


if __name__ == "__main__":
    asyncio.run(main())
