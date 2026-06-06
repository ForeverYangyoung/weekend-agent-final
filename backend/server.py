"""FastAPI：SSE 流式推送 Agent 状态 + HIL 确认/重规划 + 前端静态资源。"""
from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.graph import (
    dry_run_recovery_graph,
    execution_graph,
    planning_graph,
    replan_graph,
)
from backend.schemas import ToolStatus
from backend.hil import (
    BUILD_VERSION,
    build_plans_payload,
    detect_preference_conflicts,
    create_session,
    get_session,
    profile_chips,
    save_session,
    select_plan,
)
from backend.mock_meituan import mock_router
from backend.roles import trace_line
from backend.state import AgentState
from backend.tools.http_client import current_mode

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_frontend_dist() -> Path | None:
    for name in ("frontend", "frontend-v2"):
        dist = _PROJECT_ROOT / name / "dist"
        if dist.is_dir() and (dist / "index.html").is_file():
            return dist
    return None


_FRONTEND_DIST = _resolve_frontend_dist()
_FRONTEND_ASSETS = (_FRONTEND_DIST / "assets") if _FRONTEND_DIST else None

FRONTEND_AVAILABLE = _FRONTEND_DIST is not None

_BUILD_HINT = (
    "前端未构建。请在项目根目录执行：\n"
    "  cd frontend && npm install && npm run build\n"
    "或直接运行 python app.py（会自动尝试构建）。"
)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    mode, base = current_mode()
    url = "http://127.0.0.1:8000"
    frontend_line = f"  前端页面:     {url}/" if FRONTEND_AVAILABLE else f"  前端页面:     （未构建，见 README）"
    print(
        f"\n  {'─' * 45}\n"
        f"  Weekend Agent 启动成功\n"
        f"  {'─' * 45}\n"
        f"{frontend_line}\n"
        f"  API 文档:     {url}/docs\n"
        f"  HIL 确认:     POST /v1/agent/confirm\n"
        f"  HIL 重规划:   POST /v1/agent/replan\n"
        f"  {'─' * 45}\n"
        f"  Mock 美团: mode={mode} base_url={base}\n",
        flush=True,
    )
    yield


app = FastAPI(
    title="Weekend Agent API",
    version="0.1.0",
    lifespan=_lifespan,
    description="周末活动规划 Agent：SSE + HIL 人机协同。",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(mock_router, prefix="/mock-meituan")


def _json_safe(obj: Any) -> Any:
    if obj is None or isinstance(obj, str | int | float | bool):
        return obj
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_json_safe(v) for v in obj]
    return str(obj)


def _sse_line(payload: dict[str, Any]) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


class ProfileOverrideItem(BaseModel):
    key: str
    value: str = ""
    action: Literal["add", "remove", "set"] = "set"


class StreamAgentRequest(BaseModel):
    user_input: str = Field(..., min_length=1, max_length=8000)
    force_failure: Literal["玩", "吃", "加餐"] | None = None
    overrides: list[ProfileOverrideItem] = Field(default_factory=list)


class ReplanAgentRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=32)
    overrides: list[ProfileOverrideItem] = Field(default_factory=list)
    note: str | None = None


class ConfirmAgentRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=32)
    plan_id: str = "primary"
    selected_addon_ids: list[str] = Field(default_factory=list)


def _merge_stream_update(running: dict[str, Any], update: dict[str, Any] | None) -> None:
    """把 LangGraph updates 模式下的单步 patch 合并进累积 state。"""
    if not update:
        return
    for key, value in update.items():
        if key == "trace" and isinstance(value, list):
            running.setdefault("trace", [])
            running["trace"].extend(value)
        else:
            running[key] = value


def _stream_graph_steps(graph, initial: AgentState):
    """按节点逐步执行图，yield (node_name, trace_delta, running_state)。"""
    running: dict[str, Any] = dict(initial)
    running.setdefault("trace", [])

    for chunk in graph.stream(initial, stream_mode="updates"):  # type: ignore[arg-type]
        if not isinstance(chunk, dict):
            continue
        for node_name, update in chunk.items():
            if update is None:
                continue
            _merge_stream_update(running, update)
            trace_delta = list(update.get("trace") or [])
            yield node_name, trace_delta, dict(running)


def _run_planning_stream(
    graph,
    initial: AgentState,
    *,
    session_id: str | None = None,
    is_replan: bool = False,
) -> Iterator[str]:
    yield _sse_line(
        {
            "event": "start",
            "user_input": initial.get("user_input", ""),
            "session_id": session_id,
            "replan": is_replan,
        }
    )

    try:
        last: AgentState | None = None
        for node_name, trace_delta, running in _stream_graph_steps(graph, initial):
            last = running  # type: ignore[assignment]
            yield _sse_line(
                {
                    "event": "step",
                    "step": node_name,
                    "trace_delta": trace_delta,
                    "state": _json_safe(running),
                }
            )

        if last is None:
            yield _sse_line({"event": "error", "message": "未产生任何状态更新"})
            return

        # 预检满座等失败 → 分步恢复，让 Trace 可见「失败→换店→再预检」
        max_recover = get_settings().max_plan_iterations
        for _ in range(max_recover):
            dry_calls = last.get("dry_run_calls") or []
            dry_failed = [c for c in dry_calls if c.status == ToolStatus.FAILED]
            if not dry_failed:
                break

            plan = last.get("plan")
            poi_names: dict[str, str] = {}
            if plan is not None:
                poi_names = {s.primary.poi_id: s.primary.name for s in plan.stages}

            failed_parts: list[str] = []
            for c in dry_failed:
                pid = (c.args or {}).get("poi_id") or "?"
                pname = poi_names.get(pid, pid)
                reason = c.error or "不可用"
                if c.result and c.result.get("reason"):
                    reason = str(c.result["reason"])
                people_n = (c.args or {}).get("people", "?")
                failed_parts.append(
                    f"{pname}({pid}) people={people_n} → {reason}"
                )

            recovery_line = trace_line(
                "DryRun",
                "Recovery启动 | "
                + "；".join(failed_parts)
                + " | action=Planner拉黑该POI并换备选(如炙烤大叔)",
                phase="恢复",
            )
            running_trace = list(last.get("trace") or [])
            running_trace.append(recovery_line)
            last = {**last, "trace": running_trace}  # type: ignore[misc]
            yield _sse_line(
                {
                    "event": "trace_delta",
                    "lines": [recovery_line],
                    "note": "dry_run_recovery_start",
                }
            )

            for node_name, trace_delta, running in _stream_graph_steps(
                dry_run_recovery_graph,
                last,  # type: ignore[arg-type]
            ):
                last = running  # type: ignore[assignment]
                yield _sse_line(
                    {
                        "event": "step",
                        "step": f"recovery/{node_name}",
                        "trace_delta": trace_delta,
                        "state": _json_safe(running),
                        "note": "dry_run_recovery",
                    }
                )

        sid = session_id or create_session(last)
        save_session(sid, last)

        gp = last.get("group_profile")
        dry_runs = last.get("dry_run_calls") or []

        yield _sse_line(
            {
                "event": "awaiting_confirm",
                "session_id": sid,
                "summary": {
                    "scene": gp.scene if gp else None,
                    "plan_iteration": last.get("plan_iteration"),
                    "dry_run_ok": len(dry_runs),
                },
                "profile_chips": profile_chips(gp),
                "preference_conflicts": detect_preference_conflicts(gp),
                "plans": build_plans_payload(last),
                "dry_run_calls": _json_safe(dry_runs),
                "message": "预检完成，请确认方案或点改偏好后重规划",
            }
        )
        yield _sse_line({"event": "done"})
    except Exception as e:  # noqa: BLE001
        yield _sse_line({"event": "error", "message": str(e)})


def _run_stream(req: StreamAgentRequest) -> Iterator[str]:
    initial: AgentState = {
        "user_input": req.user_input.strip(),
        "trace": [],
        "profile_overrides": [o.model_dump() for o in req.overrides],
    }
    if req.force_failure:
        initial["force_failure"] = req.force_failure

    yield from _run_planning_stream(planning_graph, initial)


def _run_replan(req: ReplanAgentRequest) -> Iterator[str]:
    base = get_session(req.session_id)
    if base is None:
        yield _sse_line({"event": "error", "message": f"会话不存在: {req.session_id}"})
        return

    overrides = [o.model_dump() for o in req.overrides]
    if req.note and req.note.strip():
        base = dict(base)
        base["user_input"] = f"{base.get('user_input', '')}；{req.note.strip()}"

    initial: AgentState = {
        **base,
        "profile_overrides": overrides,
        "user_confirmed": False,
        "trace": list(base.get("trace") or []),
    }

    yield from _run_planning_stream(
        replan_graph,
        initial,
        session_id=req.session_id,
        is_replan=True,
    )


@app.get("/", response_model=None)
def root() -> FileResponse | HTMLResponse:
    if FRONTEND_AVAILABLE:
        return FileResponse(
            str(_FRONTEND_DIST / "index.html"),
            media_type="text/html; charset=utf-8",
        )
    return HTMLResponse(content=f"<pre>{_BUILD_HINT}</pre>", status_code=503)


@app.get("/health")
def health() -> dict[str, object]:
    mode, base = current_mode()
    return {
        "status": "ok",
        "build": BUILD_VERSION,
        "frontend": "/" if FRONTEND_AVAILABLE else "not_built",
        "stream": "/v1/agent/stream",
        "replan": "/v1/agent/replan",
        "confirm": "/v1/agent/confirm",
        "mock_meituan_mode": mode,
        "mock_meituan_base_url": base,
    }


@app.post("/v1/agent/confirm")
def confirm_agent(req: ConfirmAgentRequest) -> dict[str, object]:
    state = get_session(req.session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"会话不存在: {req.session_id}")

    state = select_plan(state, req.plan_id)
    state = dict(state)
    state["user_confirmed"] = True
    plan = state.get("plan")
    if req.selected_addon_ids:
        state["selected_addon_ids"] = list(req.selected_addon_ids)
    elif plan and plan.addons:
        state["selected_addon_ids"] = [a.addon_id for a in plan.addons]
    else:
        state["selected_addon_ids"] = []

    try:
        final: AgentState = execution_graph.invoke(state)  # type: ignore[arg-type]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e

    save_session(req.session_id, final)

    executed = final.get("executed_calls") or []
    orders = [
        {
            "stage": c.stage_name,
            "order_id": (c.result or {}).get("order_id"),
            "status": c.status.value if hasattr(c.status, "value") else str(c.status),
        }
        for c in executed
        if c.result and c.result.get("order_id")
    ]

    return {
        "status": "ok",
        "session_id": req.session_id,
        "plan_id": req.plan_id,
        "executed": len(executed),
        "failed": len(final.get("failed_calls") or []),
        "orders": orders,
        "summary_card": _json_safe(final.get("summary_card")),
        "trace": _json_safe(final.get("trace") or []),
        "trace_tail": (final.get("trace") or [])[-6:],
    }


def _stream_response(iterator: Iterator[str]) -> StreamingResponse:
    return StreamingResponse(
        iterator,
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/v1/agent/stream")
def stream_agent(req: StreamAgentRequest) -> StreamingResponse:
    if not req.user_input.strip():
        raise HTTPException(status_code=400, detail="user_input 不能为空")
    return _stream_response(_run_stream(req))


@app.post("/agent/stream")
def stream_agent_short_path(req: StreamAgentRequest) -> StreamingResponse:
    return stream_agent(req)


@app.post("/v1/agent/replan")
def replan_agent(req: ReplanAgentRequest) -> StreamingResponse:
    return _stream_response(_run_replan(req))


@app.post("/agent/replan")
def replan_agent_short_path(req: ReplanAgentRequest) -> StreamingResponse:
    return replan_agent(req)


if FRONTEND_AVAILABLE:
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_ASSETS)), name="assets")

    @app.get("/favicon.svg")
    def favicon() -> FileResponse:
        return FileResponse(str(_FRONTEND_DIST / "favicon.svg"))
