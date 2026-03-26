from typing import TypeVar, Any, cast
from beartype.door import die_if_unbearable

T = TypeVar("T")


def validate_type(obj: Any, hint: type[T]) -> T:
    die_if_unbearable(obj, hint)
    return cast(T, obj)
