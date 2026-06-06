"""硬约束过滤器 — 全部确定性代码，不给 LLM 判断。

过滤维度（02 文档 §4.1）：
  1. 营业时间与时间窗冲突
  2. 人数与桌位/排队不可接受
  3. 地理距离/路程时间溢出
  4. 画像硬过滤（儿童友好、低卡等）
  5. 总时长超出时间窗
"""

from planner.state import (
    Combo,
    EnrichedPOI,
    StageType,
    TimeSegment,
    UserProfile,
)


def _parse_time_range(open_hours: str) -> tuple[float, float]:
    """'10:00-22:00' → (10.0, 22.0)"""
    try:
        start_str, end_str = open_hours.split("-")
        s = float(start_str.split(":")[0]) + float(start_str.split(":")[1]) / 60
        e = float(end_str.split(":")[0]) + float(end_str.split(":")[1]) / 60
        return s, e
    except Exception:
        return 0.0, 24.0  # 解析失败就假设全天营业


# ── 单项过滤 ──────────────────────────────────────────


def filter_by_business_hours(ep: EnrichedPOI, segment: TimeSegment) -> bool:
    """POI 在时段内是否营业。"""
    open_start, open_end = _parse_time_range(ep.poi.open_hours)
    s_hour = _time_to_hour(segment.start_at)
    e_hour = _time_to_hour(segment.end_at)
    if s_hour == 0 and e_hour == 0:
        return True  # 时段未设置，放过
    return s_hour >= open_start and e_hour <= open_end


def filter_by_party_size(ep: EnrichedPOI, profile: UserProfile) -> bool:
    """桌位/排队是否支持当前人数。"""
    if ep.poi.category != "餐厅":
        return True
    if ep.table_available is False:
        return False
    if ep.waiting_minutes > 60:
        return False  # 等太久
    return True


def filter_by_hard_tags(ep: EnrichedPOI, profile: UserProfile) -> bool:
    """硬标签匹配：儿童友好、低卡、素食等。"""
    if not profile.hard_filters:
        return True
    poi_tags_lower = [t.lower() for t in ep.poi.tags]
    for hf in profile.hard_filters:
        needle = hf.lower().replace("needs_", "").replace("_", "")
        # 映射常见硬过滤到标签关键词
        keyword = _hard_filter_to_keyword(needle)
        if keyword and not any(keyword in t for t in poi_tags_lower):
            return False
    return True


def filter_by_geo_radius(ep: EnrichedPOI, profile: UserProfile) -> bool:
    """地理半径检查 — 宽松处理，Mock 数据 location 是字符串。"""
    # Mock 数据没有精确 GPS，放宽处理：只要 location 非空就通过
    if not ep.poi.location:
        return False
    return True


def filter_combo_by_time(combo: Combo, profile: UserProfile) -> bool:
    """组合总时长是否在时间窗内（含路途）。"""
    max_minutes = profile.time_window.duration_hours * 60
    return combo.total_duration_min <= max_minutes * 1.15  # 15% 宽容


# ── 批量过滤 ──────────────────────────────────────────


def apply_stage_filters(
    candidates: list[EnrichedPOI],
    segment: TimeSegment,
    profile: UserProfile,
) -> list[EnrichedPOI]:
    """对一个阶段的所有候选执行全部硬约束过滤。"""
    passed: list[EnrichedPOI] = []
    for ep in candidates:
        if not filter_by_business_hours(ep, segment):
            continue
        if not filter_by_party_size(ep, profile):
            continue
        if not filter_by_hard_tags(ep, profile):
            continue
        if not filter_by_geo_radius(ep, profile):
            continue
        passed.append(ep)
    return passed


# ── 辅助函数 ──────────────────────────────────────────


def _time_to_hour(t: str) -> float:
    """'14:30' → 14.5；空字符串返回 0。"""
    if not t:
        return 0.0
    try:
        parts = t.split(":")
        return float(parts[0]) + float(parts[1]) / 60
    except Exception:
        return 0.0


def _hard_filter_to_keyword(needle: str) -> str:
    mapping = {
        "kidfriendly": "儿童",
        "kidsfriendly": "儿童",
        "lowcalorie": "低卡",
        "lowcalorieoptions": "低卡",
        "vegetarian": "素食",
        "familyfriendly": "家庭",
        "petfriendly": "宠物",
    }
    return mapping.get(needle, needle)
