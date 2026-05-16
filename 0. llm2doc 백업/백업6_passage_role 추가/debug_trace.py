from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


LOG_GROUPS = ("llm", "search", "retrieval", "output", "passage_visual")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def chat_log_root(chat_id: int) -> Path:
    return project_root() / "debug_runs" / f"chat_{chat_id}"


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump_json"):
        try:
            return json.loads(value.model_dump_json())
        except Exception:
            pass
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            pass
    return value


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _safe_relative_path(path: str | Path) -> Path:
    rel = Path(path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("invalid log path")
    return rel


class GenerationTracer:
    def __init__(self, root: str | Path, *, enabled: bool = True, run_id: str | None = None):
        self.root = Path(root)
        self.enabled = enabled
        self.run_id = run_id or _default_run_id()
        self._lock = Lock()

        if self.enabled:
            self.root.mkdir(parents=True, exist_ok=True)
            for group in LOG_GROUPS:
                (self.root / group).mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_chat(cls, chat_id: int) -> "GenerationTracer":
        return cls(chat_log_root(chat_id), run_id=f"chat-{chat_id}")

    @classmethod
    def create(cls, base_dir: str | Path, *, enabled: bool = True, run_id: str | None = None) -> "GenerationTracer":
        resolved_run_id = run_id or _default_run_id()
        return cls(Path(base_dir) / "trace" / resolved_run_id, enabled=enabled, run_id=resolved_run_id)

    def _resolve(self, relative_path: str | Path) -> Path:
        rel = _safe_relative_path(relative_path)
        root = self.root.resolve()
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("invalid log path") from exc
        return target

    def _append_jsonl(self, relative_path: str | Path, row: dict[str, Any]) -> None:
        if not self.enabled:
            return
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with target.open("a", encoding="utf-8") as f:
                f.write(json.dumps(_jsonable(row), ensure_ascii=False, default=str))
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())

    def write_text(self, relative_path: str | Path, text: str) -> None:
        if not self.enabled:
            return
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with target.open("w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())

    def write_json(self, relative_path: str | Path, payload: Any) -> None:
        self.write_text(relative_path, json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, default=str))

    def update_summary(self, **fields: Any) -> None:
        if not self.enabled:
            return
        path = self._resolve("run_summary.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            summary = _read_json(path)
            summary.update({key: _jsonable(value) for key, value in fields.items()})
            tmp_path = path.with_suffix(".json.tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                f.write(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)

    def event(
        self,
        component: str,
        event: str,
        payload: dict[str, Any] | None = None,
        *,
        duration_ms: float | int | None = None,
    ) -> None:
        row: dict[str, Any] = {
            "time": _utc_now(),
            "ts": time.time(),
            "run_id": self.run_id,
            "component": component,
            "event": event,
        }
        if duration_ms is not None:
            row["duration_ms"] = round(float(duration_ms), 3)
        if payload:
            row["payload"] = _jsonable(payload)
        self._append_jsonl("events.jsonl", row)

    def record_trace(self, message: object) -> None:
        if isinstance(message, dict):
            event = str(message.get("event") or message.get("type") or "trace")
            component = str(message.get("component") or "trace")
            duration = message.get("duration_ms")
            payload = {
                key: value
                for key, value in message.items()
                if key not in {"event", "type", "component", "duration_ms"}
            }
            self.event(component, event, payload or None, duration_ms=duration if isinstance(duration, (int, float)) else None)
            if component.startswith("search"):
                self.record_search_event(event, payload)
            return

        self.event("trace", "message", {"message": message})

    def record_search_event(self, event: str, payload: dict[str, Any]) -> None:
        row = {
            "time": _utc_now(),
            "ts": time.time(),
            "run_id": self.run_id,
            "event": event,
            "payload": _jsonable(payload),
        }
        self._append_jsonl("search/first_stage.jsonl", row)


DecisionTracer = GenerationTracer


def list_log_files(root: Path) -> dict[str, list[str]]:
    files: dict[str, list[str]] = {group: [] for group in LOG_GROUPS}
    if not root.exists():
        return files

    for group in LOG_GROUPS:
        group_root = root / group
        if not group_root.exists():
            continue
        for path in sorted(group_root.rglob("*")):
            if path.is_file():
                files[group].append(path.relative_to(root).as_posix())
    return files


def read_events(root: Path) -> list[dict[str, Any]]:
    path = root / "events.jsonl"
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                events.append(parsed)
    return events


def read_chat_logs(chat_id: int) -> dict[str, Any]:
    root = chat_log_root(chat_id)
    summary = _read_json(root / "run_summary.json")
    events = read_events(root)

    status = str(summary.get("status") or "")
    if not status:
        if not root.exists():
            status = "not_started"
        elif events and events[-1].get("event") == "run_completed":
            status = "completed"
        elif events and events[-1].get("event") == "run_failed":
            status = "failed"
        else:
            status = "running"

    return {
        "chat_id": chat_id,
        "status": status,
        "summary": summary,
        "latest_event": events[-1] if events else None,
        "events": events,
        "files": list_log_files(root),
    }


def resolve_chat_log_file(chat_id: int, relative_path: str) -> Path:
    root = chat_log_root(chat_id).resolve()
    rel = _safe_relative_path(relative_path)
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("invalid log path") from exc
    if not target.is_file():
        raise FileNotFoundError(relative_path)
    return target
