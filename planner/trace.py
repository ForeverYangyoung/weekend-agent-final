"""标准化全链路追踪与日志。

所有外部调用（Mock API / LLM）经此模块产出一致的 ToolTrace，
支持按 status / tool_name 过滤，便于调试和答辩时展示。

用法:
    logger = TraceLogger()
    with logger.span("search_poi", category="亲子") as span:
        result = do_search()
        span.ok({"count": len(result)})
    # 失败时:
    #   span.fail("connection refused")
"""

import time
from contextlib import contextmanager
from typing import Any, Optional

from planner.state import ToolTrace


class TraceSpan:
    """单次追踪的上下文管理器。"""

    def __init__(self, logger: "TraceLogger", tool_name: str,
                 params: Optional[dict] = None):
        self.logger = logger
        self.tool_name = tool_name
        self.params = params or {}
        self._start: float = 0.0
        self._output: dict = {}
        self._status = ""
        self._closed = False

    def __enter__(self) -> "TraceSpan":
        self._start = time.time()
        return self

    def __exit__(self, *args):
        if not self._closed:
            self._close()

    def ok(self, output: dict | None = None):
        self._status = "success"
        if output:
            self._output = output
        self._close()

    def fail(self, error: str):
        self._status = "failed"
        self._output = {"error": error}
        self._close()

    def _close(self):
        if self._closed:
            return
        self._closed = True
        duration_ms = (time.time() - self._start) * 1000
        trace = ToolTrace(
            tool_name=self.tool_name,
            input_params=self.params,
            output_summary=self._output,
            duration_ms=round(duration_ms, 1),
            status=self._status or "unknown",
        )
        self.logger._entries.append(trace)


class TraceLogger:
    """统一 trace 收集器，挂载在 ToolHub 上。"""

    def __init__(self):
        self._entries: list[ToolTrace] = []

    @property
    def entries(self) -> list[ToolTrace]:
        return self._entries

    def span(self, tool_name: str, **params) -> TraceSpan:
        return TraceSpan(self, tool_name, params)

    def log(self, tool_name: str, status: str, output: dict | None = None,
            params: dict | None = None, duration_ms: float = 0):
        self._entries.append(ToolTrace(
            tool_name=tool_name,
            input_params=params or {},
            output_summary=output or {},
            duration_ms=duration_ms,
            status=status,
        ))

    def filter(self, tool_name: str | None = None,
               status: str | None = None) -> list[ToolTrace]:
        result = self._entries
        if tool_name:
            result = [t for t in result if t.tool_name == tool_name]
        if status:
            result = [t for t in result if t.status == status]
        return result

    def summary(self) -> dict:
        total = len(self._entries)
        ok = sum(1 for t in self._entries if t.status == "success")
        failed = sum(1 for t in self._entries if t.status == "failed")
        total_ms = sum(t.duration_ms for t in self._entries)
        return {
            "total_calls": total,
            "success": ok,
            "failed": failed,
            "total_duration_ms": round(total_ms, 1),
        }

    def dump(self) -> list[dict]:
        return [
            {
                "tool": t.tool_name,
                "params": t.input_params,
                "output": t.output_summary,
                "ms": t.duration_ms,
                "status": t.status,
            }
            for t in self._entries
        ]

    def drain(self) -> list[ToolTrace]:
        entries = self._entries.copy()
        self._entries.clear()
        return entries
