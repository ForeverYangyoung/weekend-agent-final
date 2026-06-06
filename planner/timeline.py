"""时间感知的时间轴骨架分解。

第一步：用规则枚举 3~5 个可行阶段顺序。
第二步：LLM 从候选中选最优。
第三步：把选中的顺序串成 TimelineSkeleton。
"""

from planner.state import (
    StageType,
    TimeSegment,
    TimelineSkeleton,
    UserProfile,
)


def _parse_hour(time_str: str) -> float:
    """'14:30' → 14.5"""
    parts = time_str.strip().split(":")
    return float(parts[0]) + float(parts[1]) / 60.0


def _format_time(hour: float) -> str:
    """14.5 → '14:30'"""
    h = int(hour)
    m = int((hour - h) * 60)
    return f"{h:02d}:{m:02d}"


# ── 候选顺序枚举 ──────────────────────────────────────


def enumerate_candidate_orders(profile: UserProfile) -> list[dict]:
    """用规则生成 3~5 个可行阶段顺序，供 LLM 选择。

    不在此处做决策——只过滤掉明显不合法的顺序，其余全部交给 LLM。
    """
    start_hour = _parse_hour(profile.time_window.start)
    total_hours = profile.time_window.duration_hours
    candidates: list[dict] = []

    # 判断餐食类型（供 LLM 参考）
    if start_hour < 14.0:
        meal_type = "午餐"
    else:
        meal_type = "晚餐"

    # ── 基础候选（人人都有） ──
    candidates.append({
        "order": ["玩", "吃"],
        "label": "先玩后吃",
        "meal_type": meal_type,
    })
    candidates.append({
        "order": ["吃", "玩"],
        "label": "先吃后玩",
        "meal_type": meal_type,
    })

    # ── 含增项的变体（时间窗 ≥ 5h 才加）──
    if total_hours >= 5:
        candidates.append({
            "order": ["玩", "吃", "增"],
            "label": "玩→吃→增项活动",
            "meal_type": meal_type,
        })
        candidates.append({
            "order": ["吃", "玩", "增"],
            "label": "吃→玩→增项活动",
            "meal_type": meal_type,
        })

    # ── 含休息的变体（时间窗 ≥ 6h 才加）──
    if total_hours >= 6:
        candidates.append({
            "order": ["玩", "休息", "吃"],
            "label": "玩→小憩→吃",
            "meal_type": meal_type,
        })

    # ── 上午特有：加餐/下午茶 ──
    if start_hour <= 12.0 and total_hours >= 5:
        candidates.append({
            "order": ["吃", "玩", "加餐"],
            "label": "午餐→活动→下午茶",
            "meal_type": "午餐",
        })

    # ── 晚饭场景：饭后可续活动 ──
    if start_hour >= 17.0 and total_hours >= 4:
        candidates.append({
            "order": ["吃", "玩"],
            "label": "晚餐→夜间活动",
            "meal_type": "晚餐",
        })

    # ── 朋友场景：社交节奏不同 ──
    if profile.mode == "friends" and total_hours >= 5:
        candidates.append({
            "order": ["玩", "增", "吃"],
            "label": "活动→小逛→聚餐",
            "meal_type": meal_type,
        })

    return candidates


# ── 骨架构建 ──────────────────────────────────────────


def build_skeleton_from_order(order: list[str], profile: UserProfile) -> TimelineSkeleton:
    """把 LLM 选中的阶段顺序串成完整 TimelineSkeleton。

    输入: ["玩", "吃", "增"]
    输出: TimelineSkeleton(segments=[...], meal_type, total_duration_min)
    """
    start_hour = _parse_hour(profile.time_window.start)
    total_minutes = int(profile.time_window.duration_hours * 60)

    if start_hour < 14.0:
        meal_type = "午餐"
    else:
        meal_type = "晚餐"

    # 每类阶段的默认时长和检索 category
    stage_defs = {
        "玩":   ("玩", _play_category(profile), 90),
        "吃":   ("吃", "餐厅", 75),
        "增":   ("增", _enrich_category(profile), 60),
        "加餐": ("加餐", "餐厅", 45),
        "休息": ("休息", "景点", 30),
    }

    segments: list[TimeSegment] = []
    for name in order:
        if name not in stage_defs:
            continue
        label, category, default_duration = stage_defs[name]
        segments.append(TimeSegment(
            stage_type=StageType(label),
            start_at="",
            end_at="",
            target_duration_min=default_duration,
            category_filter=category,
        ))

    return _fill_segments(segments, profile, meal_type, total_minutes)


def _fill_segments(segments: list[TimeSegment], profile: UserProfile,
                   meal_type: str, total_minutes: int) -> TimelineSkeleton:
    """填时间 + 必要时砍可选阶段。"""
    active = [s for s in segments if s.target_duration_min > 0]
    total_fixed = sum(s.target_duration_min for s in active)
    transit_budget = (len(active) - 1) * 15

    if total_fixed + transit_budget > total_minutes:
        # 砍增项 → 砍加餐 → 仍不够则均摊压缩
        for s in segments:
            if s.stage_type.value in ("增", "加餐"):
                s.target_duration_min = 0
        active = [s for s in segments if s.target_duration_min > 0]
        total_fixed = sum(s.target_duration_min for s in active)

    current = _parse_hour(profile.time_window.start)
    for s in segments:
        if s.target_duration_min == 0:
            continue
        s.start_at = _format_time(current)
        current += s.target_duration_min / 60.0 + 0.25
        s.end_at = _format_time(min(current, _parse_hour(profile.time_window.end)))

    return TimelineSkeleton(
        segments=segments,
        meal_type=meal_type,
        total_duration_min=total_minutes,
    )


# ── category 映射 ─────────────────────────────────────


def _play_category(profile: UserProfile) -> str:
    if profile.mode == "family":
        return "亲子"
    prefs = [p.lower() for p in profile.soft_preferences]
    if "展览" in prefs or "exhibition" in prefs:
        return "展览"
    if "citywalk" in prefs:
        return "citywalk"
    return "景点"


def _enrich_category(profile: UserProfile) -> str:
    prefs = [p.lower() for p in profile.soft_preferences]
    if "展览" in prefs or "exhibition" in prefs:
        return "展览"
    if "citywalk" in prefs:
        return "citywalk"
    if profile.mode == "friends":
        return "酒吧"
    return "景点"
