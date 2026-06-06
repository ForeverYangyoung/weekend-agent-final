"""LLM 调用封装层。

提供：
  - rank_timeline_orders：从候选阶段顺序中选最优（LLM-as-a-Judge）
  - generate_summary：Top-K 方案的一句话摘要
  - reflect_and_decide：ReAct 循环反思
  - judge_route_insertions：判断可顺路插入的微行为

LLM-as-a-Judge 打分函数（pairwise_judge, evaluate_geo_cohesion）
已迁移至 scoring.llm_judges。

默认使用 Qwen API（OpenAI 兼容），可通过 provider 参数切换。
"""

import json
import os
from typing import Optional

from planner.state import (
    Combo,
    InsertableBehavior,
    RouteInsertion,
    ScoredPlan,
    UserProfile,
)


class LLMClient:
    """DeepSeek / 通义等 OpenAI 兼容 API 的轻量封装。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "qwen-plus",
    ):
        self.api_key = api_key or os.getenv(
            "QWEN_API_KEY", "sk-gqmotF1H7foQGCJkGkRyyy0NwvaUSaSoc6F0GfjpSdLPjfMV"
        )
        self.base_url = base_url or os.getenv(
            "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        self.model = model

    def chat(self, system: str, user: str,
             temperature: float = 0.3) -> str:
        """发送一次对话，返回文本。"""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "openai 未安装。请执行: pip install openai"
            )

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        resp = client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""


# ── LLM 功能函数 ──────────────────────────────────────


def rank_timeline_orders(
    candidates: list[dict],
    profile: UserProfile,
    llm: LLMClient,
) -> dict:
    """LLM 从候选阶段顺序中选最优，输出最佳顺序 + 可解释理由。

    Args:
        candidates: enumerate_candidate_orders() 的返回值
        profile: 用户画像
        llm: LLM 客户端

    Returns:
        {"best_order": ["玩","吃"], "label": "先玩后吃",
         "reason": "下午两点出门先活动消耗体力...", "confidence": 0.85}
    """
    system = (
        "你是一个出行规划专家。根据用户画像、出行场景、时间窗，"
        "从候选的阶段顺序中选出最合理的一个。"
        "考虑因素：出门时间决定的餐食节奏、人群体力（带小孩不宜先玩太久）、"
        "交通高峰、饭点时间等。"
        "只输出 JSON："
        '{"best_order": ["玩","吃"], "label": "先玩后吃", '
        '"reason": "一句话解释（≤40字）", "confidence": 0.0~1.0}'
    )
    candidate_lines = []
    for i, c in enumerate(candidates):
        arrow = " → ".join(c["order"])
        candidate_lines.append(f"{i+1}. {c['label']}: {arrow} (餐食={c.get('meal_type', '')})")

    user = (
        f"用户画像：{_profile_to_text(profile)}\n\n"
        f"候选阶段顺序：\n" + "\n".join(candidate_lines)
    )
    try:
        raw = llm.chat(system, user, temperature=0.2).strip()
        result = json.loads(raw)
    except Exception:
        # 降级：选第一个候选
        c = candidates[0]
        return {
            "best_order": c["order"],
            "label": c["label"],
            "reason": "默认顺序（LLM 调用失败）",
            "confidence": 0.3,
        }

    return {
        "best_order": result.get("best_order", candidates[0]["order"]),
        "label": result.get("label", candidates[0]["label"]),
        "reason": result.get("reason", ""),
        "confidence": float(result.get("confidence", 0.5)),
    }


def generate_summary(
    plan: ScoredPlan,
    llm: LLMClient,
) -> str:
    """对 Top-2 方案生成一句话"为什么推荐"。

    只做包装，不参与排序（02 文档 §4.1 步骤 5）。
    """
    system = (
        "你是一个本地活动规划助手。根据方案内容和评分，生成一句中文推荐理由"
        "（≤ 50 字），说明该方案为什么适合用户。不要重复 POI 名称，要讲原因。"
    )
    user = _combo_to_text(plan.combo, plan.score, plan.breakdown)
    try:
        return llm.chat(system, user, temperature=0.5).strip()
    except Exception:
        return f"综合评分 {plan.score:.2f}，推荐此方案"


def reflect_and_decide(
    state,  # PlannerState (避免循环导入)
    llm: LLMClient,
) -> dict:
    """ReAct 反思：当前候选是否充分？是否还需再搜？

    Returns: {"need_more": bool, "reason": str, "suggestions": list[str]}
    """
    system = (
        "你是一个规划系统的元认知模块。审视当前搜索结果和候选方案，"
        "判断是否需要继续搜索更多 POI。只输出 JSON："
        '{"need_more": true/false, "reason": "简短", '
        '"suggestions": ["换个category", "扩大范围"]}'
    )
    n_pois = sum(len(v) for v in state.candidates.values())
    n_plans = len(state.scored_plans)
    user = (
        f"当前轮次：{state.tool_round}/{state.max_tool_rounds}\n"
        f"候选 POI 总数：{n_pois}\n"
        f"生成方案数：{n_plans}\n"
        f"用户画像：{_profile_to_text(state.profile)}"
    )
    try:
        raw = llm.chat(system, user, temperature=0.2).strip()
        return json.loads(raw)
    except Exception:
        return {"need_more": False, "reason": "fallback", "suggestions": []}


def judge_route_insertions(
    plan: ScoredPlan,
    profile: UserProfile,
    catalog: list[InsertableBehavior],
    llm: LLMClient,
) -> list[RouteInsertion]:
    """LLM 判断可顺路插入的微行为是否值得插入、在哪插入。

    输出结果直接给前端展示，例如：
      "根据路线顺序，先买奶茶，不耽误主要行程"

    Returns: list[RouteInsertion]，只含 inserted=True 的项
    """
    system = (
        "你是一个出行路线优化师。给定一个已有的出行方案和一份可插入行为列表，"
        "判断每个行为是否值得插入到路线中。"
        ""
        "判断标准："
        "1. 行为是否适合当前用户画像（家庭/朋友/情侣等）"
        "2. 行为时长是否可以在路途间隙完成（≤15min 通常可插入）"
        "3. 插入后会不会耽误主要行程（吃饭预约时间、活动开始时间等）"
        "4. 行为是否自然——比如'带孩子买奶茶'自然，'聚餐前取蛋糕'也自然"
        ""
        "只输出一个 JSON 数组，每个元素："
        '{"id": "行为ID", "insert": true/false, '
        '"position": "玩和吃之间"|"出发前"|"结束后"|"吃之前", '
        '"reason": "简短判断理由（≤20字）", '
        '"display": "给用户看的推荐语（≤30字，用第二人称，如：逛完公园顺路买杯奶茶解渴）"}'
    )
    user = (
        f"用户画像：{_profile_to_text(profile)}\n\n"
        f"当前方案路线：{_route_to_text(plan.combo)}\n"
        f"各阶段时间：\n"
        + "\n".join(
            f"  {s.stage_type.value}: {s.poi.name if s.poi else '无'}"
            for s in plan.combo.stages
        )
        + f"\n\n可插入行为列表：\n"
        + "\n".join(
            f"  [{b.id}] {b.name} ({b.duration_min}min, ¥{b.cost:.0f}, {b.category})"
            for b in catalog
        )
    )
    try:
        raw = llm.chat(system, user, temperature=0.2).strip()
        results = json.loads(raw)
    except Exception:
        return []

    insertions: list[RouteInsertion] = []
    behavior_map = {b.id: b for b in catalog}
    for item in results:
        bid = item.get("id", "")
        if bid not in behavior_map:
            continue
        behavior = behavior_map[bid]
        ri = RouteInsertion(
            behavior=behavior,
            inserted=item.get("insert", False),
            position=item.get("position", ""),
            reason=item.get("reason", ""),
            display_text=item.get("display", ""),
        )
        if ri.inserted:
            insertions.append(ri)

    return insertions


# ── 文本格式化 ────────────────────────────────────────


def _combo_to_text(combo: Combo, score: float, breakdown) -> str:
    parts = [f"总分 {score:.2f}"]
    for s in combo.stages:
        if s.poi:
            parts.append(
                f"{s.stage_type.value}: {s.poi.name} "
                f"(¥{s.poi.avg_price:.0f}, {s.poi.rating:.1f}分)"
            )
    return "\n".join(parts)


def _plan_to_text(plan: ScoredPlan) -> str:
    lines = [f"总分: {plan.score:.2f}"]
    for s in plan.combo.stages:
        if s.poi:
            route = s.route_from_prev
            route_info = f" (路途 {route.duration_min:.0f}min)" if route else ""
            lines.append(
                f"  {s.stage_type.value}: {s.poi.name} "
                f"| ¥{s.poi.avg_price:.0f} | {s.poi.rating:.1f}分"
                f"| 标签: {', '.join(s.poi.tags)}{route_info}"
            )
    return "\n".join(lines)


def _profile_to_text(profile: UserProfile) -> str:
    if profile is None:
        return "未知"
    return (
        f"模式={profile.mode}, {profile.party_size}人, "
        f"时间={profile.time_window.start}-{profile.time_window.end}, "
        f"预算={profile.budget_per_person.min}-{profile.budget_per_person.max}/人, "
        f"硬过滤={profile.hard_filters}, 偏好={profile.soft_preferences}"
    )


def _route_to_text(combo: Combo) -> str:
    lines = []
    for s in combo.stages:
        if s.poi:
            route = s.route_from_prev
            route_str = (
                f"← {route.duration_min:.0f}min/{route.distance_km:.1f}km "
                f"({route.mode})" if route else ""
            )
            lines.append(
                f"{s.stage_type.value}: {s.poi.name} ({s.poi.location}) "
                f"{route_str}"
            )
    return "\n".join(lines) if lines else "无路线信息"
