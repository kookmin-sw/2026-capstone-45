from typing import Any
from dataclasses import dataclass


@dataclass(slots=True)
class DummyTracer:
    run_id: str

    @classmethod
    def create(cls, *args, **kwargs):
        return cls(run_id="null")

    def event(self, component: str, event: str, payload: dict[str, Any]) -> None:
        pass

    def save_json(self, relative_path: str, payload: Any) -> None:
        pass

    def save_text(self, relative_path: str, text: str) -> None:
        pass

    def append_jsonl(self, relative_path: str, payload: Any) -> None:
        pass
