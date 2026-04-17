"""여러 모듈에서 공통으로 사용하는 소형 유틸리티 함수들.

복잡한 로직은 없지만, 타입 검증과 이미지 직렬화처럼 여러 단계에서
반복적으로 필요한 작업을 한곳에 모아둔다.
"""

import base64
from io import BytesIO
from typing import TypeVar, Any, cast
from PIL import Image
from beartype import beartype
from beartype.door import die_if_unbearable


T = TypeVar("T")


def validate_type(obj: Any, hint: type[T]) -> T:
    """런타임 값이 기대한 타입 힌트를 만족하는지 강제 검증한다.

    이 프로젝트는 OCR/LLM/외부 라이브러리의 반환값을 많이 다루기 때문에,
    정적 타입 검사만으로는 부족한 경우가 많다. 이 함수는 beartype의
    런타임 검증을 통해 값을 확인한 뒤, 이후 코드에서 안전하게 사용할 수
    있도록 캐스팅된 값을 그대로 반환한다.
    """
    die_if_unbearable(obj, hint)
    return cast(T, obj)


@beartype
def image_as_data_uri(img: Image.Image) -> str:
    """PIL 이미지를 `data:image/png;base64,...` 문자열로 변환한다.

    OpenAI Responses API의 `input_image`에 바로 넣기 위한 형태로 직렬화한다.
    중간 파일을 만들지 않고 메모리 버퍼만 사용하므로 임시 파일 관리가 필요 없다.
    """
    buf = BytesIO()
    img.save(buf, "png")

    buf.seek(0)

    output = BytesIO(b"data:image/png;base64,")
    output.seek(0, 2)
    base64.encode(buf, output)

    return output.getvalue().decode()
