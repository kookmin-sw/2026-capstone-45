from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TRUE_ENV_VALUES = {"1", "true", "yes", "on"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def trace_time_display() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def _generate_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in TRUE_ENV_VALUES


def resolve_debug_trace(debug_trace: bool | None) -> bool:
    if debug_trace is not None:
        return debug_trace
    return env_flag("LLM2DOC_DEBUG_TRACE", default=False)


@dataclass(slots=True)
class DecisionTracer:
    enabled: bool
    output_dir: Path | None = None
    run_id: str | None = None
    trace_dir: Path | None = None

    @classmethod
    def create(
        cls,
        output_dir: str | os.PathLike[str],
        *,
        enabled: bool,
        run_id: str | None = None,
    ) -> "DecisionTracer":
        output_dir_path = Path(output_dir)
        if not enabled:
            return cls(enabled=False, output_dir=output_dir_path)

        resolved_run_id = run_id or _generate_run_id()
        output_dir_path.mkdir(parents=True, exist_ok=True)
        trace_root = output_dir_path / "trace"
        trace_root.mkdir(parents=True, exist_ok=True)
        trace_dir = trace_root / resolved_run_id
        trace_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            enabled=True,
            output_dir=output_dir_path,
            run_id=resolved_run_id,
            trace_dir=trace_dir,
        )

    def event(self, component: str, event: str, payload: dict[str, Any]) -> None:
        if not self.enabled or self.trace_dir is None or self.run_id is None:
            return

        self.append_jsonl(
            "events.jsonl",
            {
                "time": trace_time_display(),
                "ts": _utc_now_iso(),
                "run_id": self.run_id,
                "component": component,
                "event": event,
                "payload": payload,
            },
        )

    def save_json(self, relative_path: str, payload: Any) -> None:
        if not self.enabled or self.trace_dir is None:
            return

        output_path = self.trace_dir / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("wt", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def save_text(self, relative_path: str, text: str) -> None:
        if not self.enabled or self.trace_dir is None:
            return

        output_path = self.trace_dir / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("wt", encoding="utf-8") as f:
            f.write(text)

    def append_jsonl(self, relative_path: str, payload: Any) -> None:
        if not self.enabled or self.trace_dir is None:
            return

        output_path = self.trace_dir / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("at", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False))
            f.write("\n")
