"""Planner Agent：把 Researcher 候选拼成可执行 `Plan` 列表（Top-K）。

主要能力（对齐 02.架构 §4 + 03.细节实现.md）：
  1. 硬过滤：场景硬要求（亲子需亲子活动、低卡需轻食/沙拉）；不通过即剔除。
  2. 顺序枚举：玩→吃→加餐 vs 吃→玩→加餐，各排时间轴。
  3. 主选：按候选自带的 breakdown.total 倒序取首位（已五维加权打分）。
  4. 方案打分：取各阶段 primary 的 breakdown.total 算均值，得到 Plan.score。
  5. Top-K：返回排序后的前 K 个 Plan，由 node 写入 plan + plan_alternatives。
  6. 兜底：若 research 为空或被硬过滤砍空，回退到硬编码 family/friends stub。

节点 `nodes/planner.py` 只做 state 适配；业务逻辑全部在这里。
"""
from __future__ import annotations

import json
import re

from backend.config import get_settings
from backend.llm_client import get_llm_client, get_model_name
from backend.schemas import (
    GroupProfile,
    Plan,
    PlanStage,
    POICandidate,
    ResearchResult,
    ResearchStageResult,
)

# ─────────────────────────── 时间轴工具 ───────────────────────────


_DURATION_PLAY = 150  # 玩 2.5h
_DURATION_TRANSIT = 30  # 通勤 30min
_DURATION_EAT = 120  # 吃 2h
_MAX_PLAY_EAT_DIST_KM = 3.0  # 玩/吃须在同一商圈，避免跨城组合
_ADDON_AFTER_EAT_START = 90  # 加餐相对「吃」开始的偏移
_ADDON_DURATION = 15


def _shift(time_str: str, minutes: int) -> str:
    h, m = (int(x) for x in time_str.split(":", 1))
    total = (h * 60 + m + minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _estimate_cost(people: int, stages: list[PlanStage]) -> int:
    total = 0
    for s in stages:
        price = int(s.primary.metadata.get("avg_price", 0) or 0)
        total += price if s.name == "加餐" else price * max(people, 1)
    return total


def _summary(scene: str, stages: list[PlanStage], order_label: str) -> str:
    names = " → ".join(s.primary.name for s in stages)
    label = {
        "family": "家庭周末",
        "friends": "朋友周末",
        "couple": "约会周末",
        "solo": "个人放松",
    }.get(scene, "周末安排")
    return f"{label}（{order_label}）：{names}"


# ─────────────────────────── 硬过滤 ───────────────────────────


_KIDS_KEYS = ("亲子", "儿童", "公园", "童", "宝宝", "海洋馆")
_LOW_CAL_KEYS = ("轻食", "沙拉", "健康", "低卡", "蔬食")
_CUISINE_TAGS = frozenset({"川菜", "火锅", "粤菜", "日料", "烤肉", "轻食", "江浙菜"})


def _candidate_text(c: POICandidate) -> str:
    tags = c.metadata.get("tags") or []
    tag_str = " ".join(str(t) for t in tags)
    return f"{c.name} {c.category} {c.reason} {tag_str}".lower()


def _explicit_cuisines(profile: GroupProfile) -> set[str]:
    """用户明确指定的硬菜系约束（仅来自 dietary / HIL 点改）。"""
    return {t for t in set(profile.dietary) if t in _CUISINE_TAGS}


def _matches_cuisine(c: POICandidate, cuisines: set[str]) -> bool:
    text = _candidate_text(c)
    return any(cuisine.lower() in text for cuisine in cuisines)


_HEAVY_FOOD_KEYS = ("烤肉", "火锅", "烧烤", "重口味", "川菜", "湘菜")


def _wants_light_meal(profile: GroupProfile) -> bool:
    light = {"轻食", "低卡"}
    return bool(light & set(profile.dietary))


def _wants_heavy_meal(profile: GroupProfile) -> bool:
    return "重口味" in profile.dietary


def _has_strict_constraints(profile: GroupProfile, stage_name: str) -> bool:
    if stage_name == "吃" and (
        _explicit_cuisines(profile)
        or _wants_light_meal(profile)
        or _wants_heavy_meal(profile)
    ):
        return True
    if stage_name == "玩" and profile.scene == "family" and profile.kids_ages:
        return True
    return False


def _passes_hard_filter(
    c: POICandidate, stage_name: str, profile: GroupProfile
) -> bool:
    """命中硬约束 = 不通过，整条砍掉。

    softer 的约束（如「人均偏贵」「评分稍低」）已在 Researcher 五维打分里降分，
    这里只挑「典型不可接受」的几条，保证规则可解释。
    """
    text = _candidate_text(c)
    cuisines = _explicit_cuisines(profile)

    # 1) 家庭场景 + 玩阶段：必须亲子友好
    if stage_name == "玩" and profile.scene == "family" and profile.kids_ages:
        if not any(k.lower() in text for k in _KIDS_KEYS):
            return False

    # 2) 吃阶段：显式菜系 / 口味约束（轻食与烤肉互斥）
    if stage_name == "吃":
        if _wants_light_meal(profile):
            if any(k.lower() in text for k in _HEAVY_FOOD_KEYS):
                return False
            if not any(k.lower() in text for k in _LOW_CAL_KEYS):
                return False
        elif cuisines:
            if not _matches_cuisine(c, cuisines):
                return False
        elif _wants_heavy_meal(profile):
            if not any(k.lower() in text for k in _HEAVY_FOOD_KEYS):
                return False
        elif "低卡" in profile.dietary:
            if not any(k.lower() in text for k in _LOW_CAL_KEYS):
                return False

    # 2b) 朋友聚餐：过滤明显单人简餐（演示社交场景）
    if stage_name == "吃" and profile.scene == "friends" and profile.people_count >= 4:
        snack_keys = ("快餐", "小吃", "简餐", "便利店")
        if any(k in text for k in snack_keys):
            return False

    # 3) 距离上限（researcher 已过滤一次；planner 再保险，防 stub 进来）
    d = float(c.metadata.get("distance_km", 0) or 0)
    if d > profile.distance_limit_km + 1e-6:
        return False

    return True


def _filter_stage_candidates(
    stage: ResearchStageResult,
    profile: GroupProfile,
    blocked: set[str],
) -> list[POICandidate]:
    """硬过滤 + 黑名单。若全砍光则回退为原始顺序（不报错，让 planner 仍能成图）。"""
    kept = [
        c
        for c in stage.candidates
        if c.poi_id not in blocked and _passes_hard_filter(c, stage.stage_name, profile)
    ]
    if kept:
        return kept
    # 有硬约束时禁止回退到不合规候选（避免「标了轻食却推烤肉」）
    if _has_strict_constraints(profile, stage.stage_name):
        return []
    fallback = [c for c in stage.candidates if c.poi_id not in blocked]
    return fallback or list(stage.candidates)


# ─────────────────────────── 阶段顺序枚举 ───────────────────────────


def _determine_orders(profile: GroupProfile) -> list[tuple[str, ...]]:
    """生成候选阶段顺序。

    Demo 策略：Top-K 差异落在「不同店组合」，不靠同一套店仅换玩/吃顺序。
    因此默认只枚举「先玩后吃」；饭点出发可在首方案备注里体现时间轴。
    """
    _ = profile
    return [("玩", "吃")]


def _play_eat_distance_ok(play: POICandidate, eat: POICandidate) -> bool:
    """玩/吃两地距离（相对 home 偏移）不超过阈值，保证顺路。"""
    d_play = float(play.metadata.get("distance_km", 0) or 0)
    d_eat = float(eat.metadata.get("distance_km", 0) or 0)
    return abs(d_play - d_eat) <= _MAX_PLAY_EAT_DIST_KM


def _candidate_rank(c: POICandidate) -> float:
    if c.breakdown is not None:
        return c.breakdown.total
    return c.score


def _iter_play_eat_pairs(
    play_pool: list[POICandidate],
    eat_pool: list[POICandidate],
) -> list[tuple[POICandidate, POICandidate]]:
    pairs: list[tuple[POICandidate, POICandidate]] = []
    for play in play_pool:
        for eat in eat_pool:
            if _play_eat_distance_ok(play, eat):
                pairs.append((play, eat))
    pairs.sort(key=lambda pe: (_candidate_rank(pe[0]) + _candidate_rank(pe[1])) / 2, reverse=True)
    return pairs


def _pick_play_eat_pair(
    play_pool: list[POICandidate],
    eat_pool: list[POICandidate],
) -> tuple[POICandidate, POICandidate] | None:
    pairs = _iter_play_eat_pairs(play_pool, eat_pool)
    return pairs[0] if pairs else None


def _build_plan_with_order(
    profile: GroupProfile,
    research_by_name: dict[str, ResearchStageResult],
    blocked: set[str],
    order: tuple[str, ...],
    *,
    play: POICandidate | None = None,
    eat: POICandidate | None = None,
) -> Plan | None:
    """按给定阶段顺序构建一个完整 Plan；缺关键阶段则返回 None。"""
    play_stage = research_by_name.get("玩")
    eat_stage = research_by_name.get("吃")
    if play_stage is None or eat_stage is None:
        return None

    play_pool = _filter_stage_candidates(play_stage, profile, blocked)
    eat_pool = _filter_stage_candidates(eat_stage, profile, blocked)
    if not play_pool or not eat_pool:
        return None

    if play is None or eat is None:
        pair = _pick_play_eat_pair(play_pool, eat_pool)
        if pair is None:
            return None
        play, eat = pair
    elif not _play_eat_distance_ok(play, eat):
        return None

    start = profile.start_time or "14:00"
    cursor = start
    stage_objs: dict[str, PlanStage] = {}

    for name in order:
        if name == "玩":
            seg_start = cursor
            seg_end = _shift(seg_start, _DURATION_PLAY)
            stage_objs["玩"] = PlanStage(
                name="玩",
                start_time=seg_start,
                end_time=seg_end,
                primary=play,
                backups=[c for c in play_pool if c.poi_id != play.poi_id],
                notes=play.reason,
            )
            cursor = _shift(seg_end, _DURATION_TRANSIT)
        elif name == "吃":
            seg_start = cursor
            seg_end = _shift(seg_start, _DURATION_EAT)
            stage_objs["吃"] = PlanStage(
                name="吃",
                start_time=seg_start,
                end_time=seg_end,
                primary=eat,
                backups=[c for c in eat_pool if c.poi_id != eat.poi_id],
                notes=eat.reason,
            )
            cursor = _shift(seg_end, _DURATION_TRANSIT)

    # 加餐改为 HIL 可选附加项，由 critic.attach_hil_addons 生成，不在此静默插入阶段

    # 按时间排序成 stages 列表
    final_stages = sorted(stage_objs.values(), key=lambda s: s.start_time)
    order_label = " → ".join(s.name for s in final_stages)
    plan = Plan(
        stages=final_stages,
        total_duration_hours=max(profile.duration_hours, 4.0),
        total_cost_estimate=_estimate_cost(profile.people_count, final_stages),
        order_label=order_label,
    )
    plan.summary = _summary(profile.scene, final_stages, order_label)
    plan.score = _plan_score(plan)
    return plan


def attach_hil_addons(
    plan: Plan,
    profile: GroupProfile,
    targeted: ResearchResult | None,
) -> Plan:
    """精准搜完成后，生成 HIL 可选附加项（不静默并入加餐阶段）。"""
    from backend.schemas import PlanAddon

    eat_stage = next((s for s in plan.stages if s.name == "吃"), None)
    play_stage = next((s for s in plan.stages if s.name == "玩"), None)

    stages = [s for s in plan.stages if s.name != "加餐"]
    order_label = " → ".join(s.name for s in stages)

    addon_candidate = None
    if targeted:
        addon_result = next(
            (s for s in targeted.stages if s.stage_name.startswith("加餐")),
            None,
        )
        if addon_result and addon_result.selected:
            addon_candidate = addon_result.selected

    addons: list[PlanAddon] = []

    if profile.scene == "family" and play_stage:
        poi_id = addon_candidate.poi_id if addon_candidate else "poi_cake_007"
        meta = addon_candidate.metadata if addon_candidate else {}
        price = int(meta.get("avg_price", 35) or 35) * 2
        addons.append(
            PlanAddon(
                addon_id="addon_family_refresh",
                type="refresh",
                description=(
                    "顺畅离园：低糖果茶×2 + 鲜牛奶×1，"
                    f"玩完送至「{play_stage.primary.name}」出口"
                ),
                poi_id=poi_id,
                target_poi_id=play_stage.primary.poi_id,
                price=price,
            )
        )

    if profile.scene == "friends" and eat_stage:
        poi_id = addon_candidate.poi_id if addon_candidate else "poi_flower_009"
        meta = addon_candidate.metadata if addon_candidate else {}
        price = int(meta.get("avg_price", 80) or 80)
        eat_short = eat_stage.primary.name.split("（")[0].strip()
        addons.append(
            PlanAddon(
                addon_id="addon_friends_surprise",
                type="surprise",
                description=f"餐前惊喜：鲜花提前送至「{eat_short}」",
                poi_id=poi_id,
                target_poi_id=eat_stage.primary.poi_id,
                price=price,
            )
        )

    if not addons and len(stages) == len(plan.stages) and not plan.addons:
        return plan

    updated = plan.model_copy(
        update={
            "stages": stages,
            "order_label": order_label,
            "addons": addons,
        }
    )
    if stages != plan.stages:
        updated.total_cost_estimate = _estimate_cost(profile.people_count, stages)
        updated.summary = _summary(profile.scene, stages, order_label)
        updated.score = _plan_score(updated)
    return updated


def merge_targeted_addon(
    plan: Plan,
    profile: GroupProfile,
    targeted: ResearchResult | None,
) -> Plan:
    """向后兼容：改为 HIL 附加项，不再静默插入加餐阶段。"""
    return attach_hil_addons(plan, profile, targeted)


def _plan_score(plan: Plan) -> float:
    """方案总分 = 各 stage.primary.breakdown.total 的均值，缺失视为 0.5。"""
    if not plan.stages:
        return 0.0
    parts: list[float] = []
    for s in plan.stages:
        bd = s.primary.breakdown
        parts.append(bd.total if bd else 0.5)
    return round(sum(parts) / len(parts), 3)


# ─────────────────────────── Top-K 入口 ───────────────────────────


def build_plans(
    profile: GroupProfile,
    research: ResearchResult,
    blocked: set[str] | None = None,
    *,
    top_k: int = 2,
) -> list[Plan]:
    """枚举顺序 → 硬过滤 → 选 primary → 总分排序 → 返回前 top_k 个方案。

    返回空列表表示 research 不够生成任何 Plan，调用方应回退到 stub。
    """
    blocked = blocked or set()
    by_name = {s.stage_name: s for s in research.stages}
    play_stage = by_name.get("玩")
    eat_stage = by_name.get("吃")
    if play_stage is None or eat_stage is None:
        return []

    play_pool = _filter_stage_candidates(play_stage, profile, blocked)
    eat_pool = _filter_stage_candidates(eat_stage, profile, blocked)
    if not play_pool or not eat_pool:
        return []

    pair_plans: list[Plan] = []
    seen_poi_sets: set[frozenset[str]] = set()
    orders = _determine_orders(profile)

    for play, eat in _iter_play_eat_pairs(play_pool, eat_pool):
        poi_sig = frozenset({play.poi_id, eat.poi_id})
        if poi_sig in seen_poi_sets:
            continue
        seen_poi_sets.add(poi_sig)
        for order in orders:
            plan = _build_plan_with_order(
                profile, by_name, blocked, order, play=play, eat=eat
            )
            if plan is not None:
                pair_plans.append(plan)
                break

    pair_plans.sort(key=lambda p: p.score, reverse=True)

    selected: list[Plan] = []
    used_eat_ids: set[str] = set()
    for plan in pair_plans:
        eat_id = next(
            (s.primary.poi_id for s in plan.stages if s.name == "吃"),
            "",
        )
        if selected and eat_id and eat_id in used_eat_ids:
            continue
        selected.append(plan)
        if eat_id:
            used_eat_ids.add(eat_id)
        if len(selected) >= top_k:
            break

    if len(selected) < top_k:
        for plan in pair_plans:
            if plan in selected:
                continue
            selected.append(plan)
            if len(selected) >= top_k:
                break

    return selected


# ─────────────────────────── 顺路活动搜索建议 ───────────────────────────


def suggest_insertions(plan: Plan, profile: GroupProfile) -> list[dict]:
    """生成顺路活动的精准搜索需求。

    USE_LLM=true → LLM 根据 INSERTABLE_CATALOG 自主判断插哪些、搜什么。
    USE_LLM=false → 纯规则兜底。
    """
    settings = get_settings()
    if settings.use_llm:
        client = get_llm_client()
        if client is not None:
            return _suggest_insertions_llm(plan, profile, client)
    return _suggest_insertions_rules(plan, profile)


def _suggest_insertions_llm(plan: Plan, profile: GroupProfile, client) -> list[dict]:
    """LLM 根据 INSERTABLE_CATALOG 判断顺路活动，返回搜索需求列表。"""
    from planner.state import INSERTABLE_CATALOG

    scene = profile.scene if profile.scene != "unknown" else "family"

    # 可插入行为目录文本
    catalog_lines: list[str] = []
    for b in INSERTABLE_CATALOG:
        suits = ", ".join(b.suitable_scenes)
        catalog_lines.append(
            f"  [{b.id}] {b.name} — {b.duration_min}min, ¥{b.cost:.0f}, "
            f"品类={b.category}, 适合场景={suits}"
        )
    catalog_text = "\n".join(catalog_lines)

    # 方案路线文本
    stage_lines: list[str] = []
    for s in plan.stages:
        name = s.primary.name if s.primary else "未定"
        stage_lines.append(
            f"  {s.name}: {name} ({s.start_time}–{s.end_time})"
        )
    route_text = "\n".join(stage_lines) if stage_lines else "（无阶段）"

    dietary = ", ".join(profile.dietary) if profile.dietary else "无"
    interests = ", ".join(profile.interests) if profile.interests else "无"

    system = (
        "你是一个出行路线优化师。给定出行方案和一份可插入的微行为目录，"
        "判断哪些微行为适合在当前路线中顺路完成，并生成对应的 POI 搜索需求。\n\n"
        "判断标准：\n"
        "1. 行为是否匹配用户画像（场景、人数、偏好）\n"
        "2. 时长 ≤15min 才能在路途间隙完成\n"
        "3. 插入后不耽误主要行程\n"
        "4. 不需要搜索的行为（拍照、洗手间等）直接跳过\n\n"
        "只输出一个 JSON 数组，每项格式：\n"
        '{"stage": "加餐", "scene": "family", "limit": 5, "reason": "理由 ≤15字", '
        '"behavior_id": "行为ID", "behavior_name": "行为名称"}\n'
        "不要输出任何其他文字。"
    )

    user = (
        f"用户画像：\n"
        f"  场景: {scene}\n"
        f"  人数: {profile.people_count}人\n"
        f"  距离限制: {profile.distance_limit_km}km\n"
        f"  时长: {profile.duration_hours}h\n"
        f"  预算: {profile.budget_per_person or '不限'}元/人\n"
        f"  饮食偏好: {dietary}\n"
        f"  兴趣: {interests}\n"
        f"\n当前方案: {plan.order_label}\n"
        f"{route_text}\n"
        f"\n可插入行为目录:\n{catalog_text}"
    )

    model = get_model_name()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
        )
        content = resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[suggest_insertions] LLM 调用失败: {e}，回退到规则")
        return _suggest_insertions_rules(plan, profile)

    # 解析 JSON（LLM 可能带 markdown 代码块包装）
    try:
        requests = json.loads(content)
        if isinstance(requests, list):
            return requests
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass

    print(f"[suggest_insertions] LLM 返回无法解析，回退到规则。原始: {content[:200]}")
    return _suggest_insertions_rules(plan, profile)


def _suggest_insertions_rules(plan: Plan, profile: GroupProfile) -> list[dict]:
    """纯规则兜底：根据方案结构和场景生成搜索需求。"""
    requests: list[dict] = []
    scene = profile.scene if profile.scene != "unknown" else "family"

    has_play = any(s.name == "玩" for s in plan.stages)
    has_eat = any(s.name == "吃" for s in plan.stages)

    if not has_play or not has_eat:
        return requests

    requests.append({
        "stage": "加餐",
        "scene": scene,
        "limit": 5,
        "reason": "玩完顺路买杯奶茶",
    })

    if scene in ("family", "couple"):
        requests.append({
            "stage": "加餐",
            "scene": scene,
            "limit": 5,
            "reason": "加一份甜品或蛋糕",
        })
    elif scene == "friends":
        requests.append({
            "stage": "加餐",
            "scene": scene,
            "limit": 5,
            "reason": "顺路小吃摊",
        })

    return requests


# ─────────────────────────── 兜底 Stub ───────────────────────────


def build_family_stub() -> Plan:
    return Plan(
        summary="亲子下午：奥森公园遛娃 → 轻食午餐 → 北欧蛋糕加餐",
        order_label="玩 → 吃 → 加餐",
        stages=[
            PlanStage(
                name="玩",
                start_time="14:00",
                end_time="16:00",
                primary=POICandidate(
                    poi_id="poi_park_001",
                    name="奥林匹克森林公园",
                    category="亲子活动",
                    score=0.92,
                    reason="离家 6km，有儿童游乐区，5 岁孩子合适",
                ),
            ),
            PlanStage(
                name="吃",
                start_time="16:30",
                end_time="18:00",
                primary=POICandidate(
                    poi_id="poi_rest_021",
                    name="Wagas 沙拉轻食（奥森店）",
                    category="餐厅",
                    score=0.88,
                    reason="低卡符合减肥需求；有儿童椅",
                ),
            ),
            PlanStage(
                name="加餐",
                start_time="17:30",
                end_time="17:45",
                primary=POICandidate(
                    poi_id="poi_cake_007",
                    name="原麦山丘 小蛋糕（送至餐厅）",
                    category="加餐",
                    score=0.81,
                    reason="低糖款，给孩子的小惊喜",
                ),
            ),
        ],
        total_duration_hours=4.0,
        total_cost_estimate=320,
        score=0.0,
    )


def build_friends_stub(profile: GroupProfile | None = None) -> Plan:
    light = profile is not None and _wants_light_meal(profile)
    eat = POICandidate(
        poi_id="poi_rest_203" if light else "poi_rest_201",
        name="Wagas 轻食（三里屯）" if light else "姜虎东白丁烤肉（三里屯）",
        category="轻食" if light else "餐厅",
        score=0.86 if light else 0.89,
        reason="4 人窗边位，沙拉碗适合聚餐" if light else "4 人聚餐口碑高",
        metadata={
            "avg_price": 95 if light else 160,
            "distance_km": 1.5 if light else 1,
            "tags": ["轻食", "沙拉", "低卡", "社交"] if light else ["烤肉", "社交"],
        },
    )
    summary = (
        "朋友下午：剧本杀 → 轻食聚餐 → 鲜花点缀"
        if light
        else "朋友下午：剧本杀 → 烤肉聚餐 → 鲜花点缀"
    )
    return Plan(
        summary=summary,
        order_label="玩 → 吃 → 加餐",
        stages=[
            PlanStage(
                name="玩",
                start_time="14:00",
                end_time="16:30",
                primary=POICandidate(
                    poi_id="poi_act_101",
                    name="罪有引力剧本杀（三里屯店）",
                    category="活动",
                    score=0.90,
                    reason="4 人本，2 男 2 女均衡",
                    metadata={"avg_price": 120, "distance_km": 2},
                ),
            ),
            PlanStage(
                name="吃",
                start_time="17:00",
                end_time="19:00",
                primary=eat,
            ),
            PlanStage(
                name="加餐",
                start_time="18:30",
                end_time="18:45",
                primary=POICandidate(
                    poi_id="poi_flower_009",
                    name="花点时间 小花束（送至餐厅）",
                    category="加餐",
                    score=0.76,
                    reason="给女生的小惊喜",
                ),
            ),
        ],
        total_duration_hours=5.0,
        total_cost_estimate=680,
        score=0.0,
    )
