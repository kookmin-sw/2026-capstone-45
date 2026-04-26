import base64
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
