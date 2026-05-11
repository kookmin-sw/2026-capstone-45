import base64
import asyncio

from threading import Thread
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

    s = base64.standard_b64encode(buf.getvalue()).decode()

    return "data:image/png;base64," + s


async def join_thread_async(thread: Thread):
    backoff = 0.001

    while thread.is_alive():
        time_to_sleep = backoff if 0.01 <= backoff else 0
        backoff = min(0.5, backoff * 2)

        await asyncio.sleep(time_to_sleep)

    thread.join(timeout=0)
