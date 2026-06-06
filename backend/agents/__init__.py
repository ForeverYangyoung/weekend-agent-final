"""Agent 业务逻辑层（独立于 LangGraph 节点的纯函数）。

节点 `nodes/*.py` 只做 state 读写与 trace；具体业务在这里。
"""

from backend.agents.planner import (
    build_family_stub,
    build_friends_stub,
    build_plans,
    suggest_insertions,
)
from backend.agents.profiler import analyze_profile
from backend.agents.researcher import run_initial_research, run_targeted_research

__all__ = [
    "analyze_profile",
    "build_family_stub",
    "build_friends_stub",
    "build_plans",
    "run_initial_research",
    "run_targeted_research",
    "suggest_insertions",
]
