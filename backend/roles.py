"""逻辑 Agent（对外 4 角色）与 LangGraph 节点（对内实现）的映射。

答辩口径：只有 LOGICAL_AGENTS 里这 4 个是「Agent」；
graph.py 里的 add_node 名称是「步骤」，其中 critic/dry_run/compensator/notifier 不单独算 Agent。
"""
from __future__ import annotations

from typing import Literal

# 对外讲故事的 4 个逻辑角色（与 02.架构和agent.md 一致）
LogicalAgent = Literal["Profiler", "Researcher", "Planner", "Executor"]

LOGICAL_AGENTS: tuple[LogicalAgent, ...] = (
    "Profiler",
    "Researcher",
    "Planner",
    "Executor",
)

# LangGraph 节点名 → (逻辑角色, 子阶段说明)
# tools/ 是工具层，无独立 node；由 Researcher / Executor 调用
NODE_TO_ROLE: dict[str, tuple[LogicalAgent, str | None]] = {
    "profiler": ("Profiler", None),
    "researcher": ("Researcher", None),
    "planner": ("Planner", None),
    "critic": ("Planner", "校验"),
    "dry_run": ("Executor", "预检"),
    "executor": ("Executor", "提交"),
    "compensator": ("Executor", "回滚"),
    "notifier": ("Executor", "交付"),
}


def trace_line(
    role: LogicalAgent,
    message: str,
    *,
    phase: str | None = None,
    suffix: str | None = None,
) -> str:
    """统一 trace 前缀，例如 [Executor·预检] 打听 3 项…"""
    tag = f"{role}·{phase}" if phase else role
    if suffix:
        tag = f"{tag}{suffix}"
    return f"[{tag}] {message}"


def trace_for_node(node_name: str, message: str, *, suffix: str | None = None) -> str:
    """按 graph 节点名生成 trace（节点文件里也可用 trace_line 直接写角色）。"""
    role, phase = NODE_TO_ROLE[node_name]
    return trace_line(role, message, phase=phase, suffix=suffix)
