"""LangGraph 的全局 State。所有节点读/写同一份 State。"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from backend.schemas import (
    CriticFeedback,
    GroupProfile,
    Plan,
    ResearchResult,
    SummaryCard,
    ToolCall,
)


class AgentState(TypedDict, total=False):
    # ── 输入 ──
    user_input: str

    # 用户历史上下文（来自画像库，P0 可直接传 dict）。
    # 典型字段：favorite_tags / tag_counts / cuisine_counts / category_counts
    history_context: dict[str, Any]

    # ── Profiler 输出 ──
    group_profile: GroupProfile | None

    # ── Researcher 初搜输出 ──
    research_result: ResearchResult | None

    # ── Planner 输出的顺路活动搜索需求 ──
    targeted_search_requests: list[dict]

    # ── Researcher 精准搜输出 ──
    targeted_research_result: ResearchResult | None

    # ── Planner 输出 ──
    plan: Plan | None
    # Top-K 中除主选外的备选方案，按总分降序；为空说明只生成了一种顺序
    plan_alternatives: list[Plan]
    plan_iteration: int  # 已重规划次数，触发 max_plan_iterations 兜底

    # ── Critic 输出 ──
    critic_feedback: CriticFeedback | None

    # ── DryRun / Executor ──
    dry_run_calls: list[ToolCall]
    executed_calls: list[ToolCall]
    failed_calls: list[ToolCall]

    # ── HIL：前端点改标签回写（replan 前写入，hil 节点消费后清空）──
    profile_overrides: list[dict[str, str]]
    revise_feedback: str
    revise_locked_stages: list[str]
    revise_events: list[dict[str, str]]
    plan_snapshots: list[dict[str, Any]]

    # ── 用户在 HIL 节点的确认结果 ──
    user_confirmed: bool
    selected_addon_ids: list[str]

    # ── Notifier 最终交付 ──
    summary_card: SummaryCard | None

    # ── 追踪日志：每个节点 append 一条，answer 答辩时直接展示 ──
    trace: Annotated[list[str], operator.add]

    # ── Demo 专用：注入某阶段下单失败，用于演示补偿链 ──
    force_failure: str | None
