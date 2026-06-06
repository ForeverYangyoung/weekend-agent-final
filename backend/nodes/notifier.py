"""Notifier 节点：生成最终的行程卡 + 给亲友的可分享文案。"""
from __future__ import annotations

from backend.roles import trace_line
from backend.schemas import SummaryCard, ToolStatus
from backend.state import AgentState


def _render_markdown(plan, profile, executed, alternatives, *, failed_calls, dry_run_calls) -> str:
    lines = [f"## {plan.summary}", ""]
    head = f"- 人数：{profile.people_count}　预计花费：约 ¥{plan.total_cost_estimate}"
    if plan.score:
        head += f"　综合评分：{plan.score:.2f}"
    lines.append(head)
    lines.append("")
    lines.append("| 时间 | 阶段 | 地点 | 订单 |")
    lines.append("|---|---|---|---|")

    order_by_stage: dict[str, str] = {}
    for c in executed:
        if c.result and "order_id" in c.result:
            order_by_stage[c.stage_name] = c.result["order_id"]

    for s in plan.stages:
        order = order_by_stage.get(s.name, "—")
        lines.append(
            f"| {s.start_time}–{s.end_time} | {s.name} | {s.primary.name} | `{order}` |"
        )

    if alternatives:
        lines.append("")
        lines.append("### 备选方案")
        for i, alt in enumerate(alternatives, start=1):
            order_label = alt.order_label or " → ".join(st.name for st in alt.stages)
            names = " → ".join(st.primary.name for st in alt.stages)
            lines.append(
                f"- 方案 {i}（{order_label}，score={alt.score:.2f}，约 ¥{alt.total_cost_estimate}）：{names}"
            )

    dry_failed = [c for c in dry_run_calls if c.status == ToolStatus.FAILED]
    if failed_calls or dry_failed:
        lines.append("")
        lines.append(
            "⚠️ **订座异常提醒**：部分热门门店已满座或预检未通过。"
            "已尝试切换备选；若仍不满意，可放宽区域至 10 公里或更换菜系后让我重新规划。"
        )
        for c in failed_calls + dry_failed:
            poi = (c.args or {}).get("poi_id", "—")
            lines.append(f"- {c.stage_name} · `{poi}`：{c.error or '不可用'}")

    return "\n".join(lines)


def _render_share(plan) -> str:
    first = plan.stages[0] if plan.stages else None
    if not first:
        return "搞定了，下午出发～"
    return (
        f"搞定了，下午 {first.start_time} 出发，先去 {first.primary.name}，"
        f"之后吃饭定在 {plan.stages[1].primary.name if len(plan.stages) > 1 else '一家轻食店'}，"
        "美团已经下好单啦～"
    )


def notifier_node(state: AgentState) -> dict:
    plan = state.get("plan")
    profile = state.get("group_profile")
    executed = state.get("executed_calls", []) or []
    failed_calls = state.get("failed_calls", []) or []
    dry_run_calls = state.get("dry_run_calls", []) or []
    alternatives = state.get("plan_alternatives") or []

    if not plan or not profile:
        return {"trace": [trace_line("Executor", "跳过：缺 plan/profile", phase="交付")]}

    card = SummaryCard(
        title=plan.summary,
        body_markdown=_render_markdown(
            plan,
            profile,
            executed,
            alternatives,
            failed_calls=failed_calls,
            dry_run_calls=dry_run_calls,
        ),
        share_text=_render_share(plan),
    )

    return {
        "summary_card": card,
        "trace": [
            trace_line(
                "Executor",
                f"行程卡已生成 ✓，分享文案: {card.share_text[:30]}...",
                phase="交付",
            )
        ],
    }
