from typing import TypeAlias, Annotated
from fastapi import Request, Depends
from concurrent.futures import ThreadPoolExecutor

from llm2doc.util import validate_type


def with_thread_pool(request: Request):
    thread_pool = validate_type(request.state.thread_pool, ThreadPoolExecutor)
    return thread_pool


WithThreadPool: TypeAlias = Annotated[ThreadPoolExecutor, Depends(with_thread_pool)]
