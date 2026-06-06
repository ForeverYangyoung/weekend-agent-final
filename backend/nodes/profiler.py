"""Profiler 节点：从用户一句话中抽取群体画像。

薄适配层：业务在 `weekend_agent.agents.profiler.analyze_profile`。
保留 `_heuristic_profile` 名字给老测试 / 文档使用。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.agents import analyze_profile
from backend.agents.profiler import _build_editable_tags
from backend.roles import trace_line
from backend.schemas import GroupProfile, ProfileEvidence
from backend.state import AgentState


def _heuristic_profile(
    text: str,
    history_context: Mapping[str, Any] | None = None,
) -> GroupProfile:
    """向后兼容入口（旧代码/文档以此名调用）。"""
    return analyze_profile(text, history_context=history_context)


def _append_dietary_from_history(
    profile: GroupProfile,
    tag: str,
    *,
    term: str,
    evidence: list[ProfileEvidence],
) -> None:
    if tag not in profile.dietary:
        profile.dietary.append(tag)
    evidence.append(
        ProfileEvidence(
            field="dietary",
            value=tag,
            term=term,
            confidence=0.88,
            source="history",
        )
    )


def inject_history_archives(profile: GroupProfile, text: str) -> tuple[GroupProfile, list[str]]:
    """演示用：按场景注入历史健康档案，触发饮食矛盾与 Trace 可解释性。"""
    updated = profile.model_copy(deep=True)
    trace_lines: list[str] = []
    evidence = list(updated.evidence)

    # 家庭：老婆/孩子在控糖控卡周期
    if any(k in text for k in ("老婆", "孩子", "娃")) or updated.scene == "family":
        added: list[str] = []
        for tag in ("低卡", "少糖"):
            if tag not in updated.dietary:
                _append_dietary_from_history(
                    updated, tag, term="历史档案·控糖控卡", evidence=evidence
                )
                added.append(tag)
        if added:
            trace_lines.append(
                trace_line(
                    "Profiler",
                    f"[历史档案唤醒] 检测到成员正处于控糖控卡周期，"
                    f"自动叠加健康轻食约束：{'、'.join(added)}",
                )
            )

    # 朋友：4 人局成员近期禁辣（与 utterance 重口味形成矛盾）
    friends_ctx = (
        any(k in text for k in ("朋友", "4人", "4个人", "三个人"))
        or (updated.scene == "friends" and updated.people_count >= 4)
    )
    if friends_ctx:
        if "禁辣" not in updated.dietary:
            _append_dietary_from_history(
                updated, "禁辣", term="历史档案·上火/痔疮恢复期", evidence=evidence
            )
        spicy_forbidden = ("重辣", "特辣", "变态辣")
        merged_forbidden = list(updated.forbidden_tags)
        for tag in spicy_forbidden:
            if tag not in merged_forbidden:
                merged_forbidden.append(tag)
        updated.forbidden_tags = merged_forbidden
        for tag in spicy_forbidden:
            evidence.append(
                ProfileEvidence(
                    field="forbidden_tags",
                    value=tag,
                    term="历史档案·小明恢复期",
                    confidence=0.9,
                    source="history",
                )
            )
        trace_lines.append(
            trace_line(
                "Profiler",
                "[历史档案唤醒] ⚠️ 系统检测到小明近期有「上火/痔疮」恢复期记录，"
                "已叠加禁辣约束（禁辣 + 禁忌：重辣/特辣/变态辣）",
            )
        )

    if trace_lines:
        updated.evidence = evidence
        updated.editable_tags = _build_editable_tags(updated, has_history=True)
        for tag in updated.editable_tags:
            if tag.key == "dietary" and tag.value in {"低卡", "少糖", "禁辣"}:
                tag.source = "history"

    return updated, trace_lines


def profiler_node(state: AgentState) -> dict:
    """节点入口：返回的 dict 会被合并进 AgentState。"""
    text = state.get("user_input", "")
    history_context = state.get("history_context") or {}  # type: ignore[arg-type]
    profile = analyze_profile(text, history_context=history_context)
    profile, archive_trace = inject_history_archives(profile, text)

    scene_conf = profile.confidence.get("scene", 0.0)
    tags_preview = [t.label for t in profile.editable_tags[:8]]
    start = profile.start_time or "—"

    base_trace = trace_line(
        "Profiler",
        f"scene={profile.scene}(conf={scene_conf:.2f}) people={profile.people_count} "
        f"start={start} dietary={profile.dietary} interests={profile.interests} "
        f"forbidden={profile.forbidden_tags} tags={tags_preview}",
    )

    return {
        "group_profile": profile,
        "plan_iteration": 0,
        "trace": [base_trace, *archive_trace],
    }
