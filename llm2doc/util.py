import base64
import contextlib
import aiosqlite
from io import BytesIO
from typing import TypeVar, Any, cast
from PIL import Image
from beartype import beartype
from beartype.door import die_if_unbearable


T = TypeVar("T")


def validate_type(obj: Any, hint: type[T]) -> T:
    die_if_unbearable(obj, hint)
    return cast(T, obj)


@beartype
def image_as_data_uri(img: Image.Image) -> str:
    buf = BytesIO()
    img.save(buf, "png")

    buf.seek(0)

    output = BytesIO(b"data:image/png;base64,")
    output.seek(0, 2)
    base64.encode(buf, output)

    return output.getvalue().decode()


@contextlib.asynccontextmanager
async def asdf(db: aiosqlite.Connection):
    async with db.cursor() as cursor:
        assert not db.in_transaction

        try:
            yield cursor
        except Exception:
            await db.rollback()
            raise
        else:
            await db.commit()
