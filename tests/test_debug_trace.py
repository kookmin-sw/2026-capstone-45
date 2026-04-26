import json
import os
import shutil
import unittest
import uuid
from pathlib import Path

from llm2doc.debug_trace import DecisionTracer, env_flag, resolve_debug_trace


class DebugTraceTests(unittest.TestCase):
    def make_tempdir(self) -> Path:
        base_dir = Path.cwd() / "build" / "test_debug_trace"
        base_dir.mkdir(parents=True, exist_ok=True)
        tmpdir = base_dir / f"case-{uuid.uuid4().hex[:8]}"
        tmpdir.mkdir(parents=True, exist_ok=False)
        return tmpdir

    def test_env_flag_true_values(self) -> None:
        previous = os.environ.get("LLM2DOC_DEBUG_TRACE")
        try:
            os.environ["LLM2DOC_DEBUG_TRACE"] = "true"
            self.assertTrue(env_flag("LLM2DOC_DEBUG_TRACE"))
            self.assertTrue(resolve_debug_trace(None))
        finally:
            if previous is None:
                os.environ.pop("LLM2DOC_DEBUG_TRACE", None)
            else:
                os.environ["LLM2DOC_DEBUG_TRACE"] = previous

    def test_env_flag_default_when_missing(self) -> None:
        previous = os.environ.pop("LLM2DOC_DEBUG_TRACE", None)
        try:
            self.assertFalse(env_flag("LLM2DOC_DEBUG_TRACE"))
            self.assertFalse(resolve_debug_trace(None))
        finally:
            if previous is not None:
                os.environ["LLM2DOC_DEBUG_TRACE"] = previous

    def test_create_enabled_tracer_creates_run_directory(self) -> None:
        tmpdir = self.make_tempdir()
        try:
            tracer = DecisionTracer.create(tmpdir, enabled=True)
            self.assertTrue(tracer.enabled)
            self.assertIsNotNone(tracer.run_id)
            self.assertIsNotNone(tracer.trace_dir)
            assert tracer.trace_dir is not None
            self.assertTrue(tracer.trace_dir.exists())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_append_jsonl_and_save_json(self) -> None:
        tmpdir = self.make_tempdir()
        try:
            tracer = DecisionTracer.create(tmpdir, enabled=True, run_id="run-1")
            tracer.event("component", "event_name", {"value": 1})
            tracer.append_jsonl("search/test.jsonl", {"query": "hello"})
            tracer.save_json("analysis.json", {"status": "ok"})

            events_path = tmpdir / "trace" / "run-1" / "events.jsonl"
            search_path = tmpdir / "trace" / "run-1" / "search" / "test.jsonl"
            analysis_path = tmpdir / "trace" / "run-1" / "analysis.json"

            self.assertTrue(events_path.exists())
            self.assertTrue(search_path.exists())
            self.assertTrue(analysis_path.exists())

            with events_path.open("rt", encoding="utf-8") as f:
                event_row = json.loads(f.readline())
            self.assertEqual(event_row["component"], "component")
            self.assertEqual(event_row["event"], "event_name")

            with analysis_path.open("rt", encoding="utf-8") as f:
                analysis = json.load(f)
            self.assertEqual(analysis["status"], "ok")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_disabled_tracer_is_noop(self) -> None:
        tmpdir = self.make_tempdir()
        try:
            tracer = DecisionTracer.create(tmpdir, enabled=False)
            tracer.event("component", "event_name", {"value": 1})
            tracer.save_json("analysis.json", {"status": "ok"})
            tracer.append_jsonl("search/test.jsonl", {"query": "hello"})

            trace_root = tmpdir / "trace"
            self.assertFalse(trace_root.exists())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
