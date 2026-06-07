"""Profiler Agent：把一句自然语言转成结构化 GroupProfile。

P0：规则 + 正则；为每个字段给出置信度 + 可编辑标签 + 证据链，对齐 02.架构 §3。
P1：可在调用方按 `use_llm` 切到 LLM Function Calling，输出仍是 GroupProfile。

节点 `nodes/profiler.py` 只做 state 适配，业务全部在这里。
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from backend.mock_meituan.catalog import MOCK_MERCHANTS
from backend.schemas import EditableTag, GroupProfile, ProfileEvidence

# ─────────────────────────── 关键词表 ───────────────────────────

_FAMILY_KEYWORDS = (
    "老婆", "老公", "孩子", "娃", "宝宝", "孩", "一家", "亲子",
    "儿子", "女儿", "妈妈", "爸爸",
)
_FRIENDS_KEYWORDS = ("朋友", "哥们", "闺蜜", "同事", "同学", "搭子")
_COUPLE_KEYWORDS = ("对象", "女朋友", "男朋友", "约会", "情侣", "二人世界")

_LOW_CAL_KEYWORDS = ("减肥", "低卡", "轻食", "沙拉", "控糖", "减脂", "健康餐")
_HEAVY_FLAVOR_KEYWORDS = ("重口味", "重口", "口味重", "想吃重", "重的")
_NO_SPICY_KEYWORDS = ("不辣", "微辣", "清淡")

# 兴趣标签 → 命中关键词
_INTEREST_KEYWORDS: dict[str, tuple[str, ...]] = {
    "亲子": ("亲子", "儿童", "宝宝", "娃"),
    "展览": ("展览", "美术馆", "博物馆", "艺术展"),
    "citywalk": ("citywalk", "逛街", "散步", "随便逛"),
    "剧本杀": ("剧本杀", "密室"),
    "户外": ("公园", "户外", "露营", "骑行"),
}

_NEAR_HINTS = ("别太远", "不要远", "近点", "别离家太远", "附近", "周边")

_DISTRICT_NAMES: tuple[str, ...] = (
    "海淀", "朝阳", "西城", "东城", "丰台", "石景山", "通州", "昌平",
    "大兴", "顺义", "房山", "门头沟", "怀柔", "平谷", "密云", "延庆",
)

_EXPLICIT_HEAVY_DIETARY = frozenset({"火锅", "烤肉", "川菜", "湘菜", "重口味"})
_IMPLICIT_LIGHT_DIETARY = frozenset({"低卡", "少糖", "轻食"})
_IMPLICIT_ARCHIVE_DIETARY = _IMPLICIT_LIGHT_DIETARY | frozenset({"禁辣"})
_IMPLICIT_SPICY_FORBIDDEN = frozenset({"重辣", "特辣", "变态辣"})

_CUISINE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("川菜", "川菜"),
    ("火锅", "火锅"),
    ("粤菜", "粤菜"),
    ("日料", "日料"),
    ("烤肉", "烤肉"),
    ("轻食", "轻食"),
    ("沙拉", "轻食"),
)
_AFTERNOON_HINTS = ("下午", "饭后", "下午茶")
_EVENING_HINTS = ("晚上", "晚饭", "夜里", "晚餐")
_MORNING_HINTS = ("上午", "早上", "早饭")

# 中文小数字 → 阿拉伯数字
_CN_DIGIT: dict[str, int] = {
    "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

# 中文常见「人数说法」短语 → (人数, 触发词)
_PEOPLE_PHRASES: tuple[tuple[str, int], ...] = (
    ("一家三口", 3),
    ("一家四口", 4),
    ("一家五口", 5),
    ("两口子", 2),
    ("两口", 2),
    ("我们俩", 2),
    ("俩人", 2),
    ("我俩", 2),
    ("我们三个", 3),
    ("三人行", 3),
    ("我们四个", 4),
)

# 预算正则：「人均 200」「预算 300」「300 元/人」
_BUDGET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"人均\s*(\d+)"), "人均"),
    (re.compile(r"预算\s*(?:每人)?\s*(\d+)"), "预算"),
    (re.compile(r"(\d+)\s*(?:元|块)?\s*/\s*人"), "元/人"),
)


# ─────────────────────────── 工具函数 ───────────────────────────


def _hits(text: str, keywords) -> list[str]:
    return [k for k in keywords if k in text]


def _conf_by_hits(n: int, *, low: float = 0.55, mid: float = 0.82, high: float = 0.92) -> float:
    if n >= 2:
        return high
    if n == 1:
        return mid
    return low


# ─────────────────────────── 各维度推理 ───────────────────────────


def _infer_scene(text: str) -> tuple[str, float, list[str]]:
    """返回 (scene, confidence, 触发词列表)。"""
    cpl = _hits(text, _COUPLE_KEYWORDS)
    text_for_friends = text
    for kw in cpl:
        text_for_friends = text_for_friends.replace(kw, "")
    fam = _hits(text, _FAMILY_KEYWORDS)
    fri = _hits(text_for_friends, _FRIENDS_KEYWORDS)

    priority = {"family": 3, "couple": 2, "friends": 1}
    ranked = sorted(
        [
            ("family", len(fam), fam),
            ("couple", len(cpl), cpl),
            ("friends", len(fri), fri),
        ],
        key=lambda x: (x[1], priority[x[0]]),
        reverse=True,
    )
    scene, n, terms = ranked[0]
    if n == 0:
        return "solo", 0.55, []
    return scene, _conf_by_hits(n), terms


def _infer_people(text: str, scene: str) -> tuple[int, float, str]:
    """优先级：阿拉伯数字 > 短语表 > 单字中文 > 场景默认。返回 (n, conf, term)。"""
    m = re.search(r"(\d+)\s*(?:个人|人)", text)
    if m:
        return int(m.group(1)), 0.95, m.group(0)

    for phrase, n in _PEOPLE_PHRASES:
        if phrase in text:
            return n, 0.92, phrase

    for ch, n in _CN_DIGIT.items():
        if f"{ch}个人" in text or f"{ch}人" in text:
            return n, 0.85, f"{ch}人"

    defaults = {"family": (3, 0.6, "default-family"), "friends": (4, 0.6, "default-friends"),
                "couple": (2, 0.7, "default-couple")}
    return defaults.get(scene, (1, 0.5, "default-solo"))


def _infer_kids_ages(text: str, scene: str) -> tuple[list[int], list[str]]:
    if scene != "family":
        return [], []
    matches = list(re.finditer(r"(\d+)\s*岁", text))
    if not matches:
        return [], []
    return [int(m.group(1)) for m in matches[:3]], [m.group(0) for m in matches[:3]]


_MEAL_TIME_RE = re.compile(
    r"(中午|晚上|上午|早上|下午)?\s*(\d+)\s*点\s*想\s*吃"
)
_MEAL_TIME_ALT_RE = re.compile(
    r"想\s*吃[^，。；\n]{0,12}?(中午|晚上|上午|早上|下午)?\s*(\d+)\s*点"
)
_NAMED_VENUE_FALLBACK: tuple[str, ...] = (
    "川一哥", "姜虎东", "海底捞", "炙烤大叔", "禾绿", "绿茶",
)


def _hour_from_period(period: str, hour: int) -> int:
    if period in ("下午", "晚上") and hour < 12:
        return hour + 12
    return hour


def _infer_meal_time(text: str) -> tuple[str | None, float, str]:
    for pattern in (_MEAL_TIME_RE, _MEAL_TIME_ALT_RE):
        m = pattern.search(text)
        if m:
            period = (m.group(1) or "").strip()
            hour = int(m.group(2))
            hour = _hour_from_period(period, hour)
            return f"{hour:02d}:00", 0.92, m.group(0)
    return None, 0.4, ""


def _infer_preferred_venues(text: str) -> tuple[list[str], list[tuple[str, str, float]]]:
    """从原文匹配 catalog 店名或常见品牌简称。"""
    hints: list[str] = []
    ev: list[tuple[str, str, float]] = []
    seen: set[str] = set()

    for merchant in MOCK_MERCHANTS.values():
        full_name = str(merchant.get("name") or "")
        short = full_name.split("（")[0].strip()
        for token in (short, full_name):
            if len(token) < 2 or token not in text:
                continue
            if short in seen:
                break
            seen.add(short)
            hints.append(short)
            ev.append((short, token, 0.95))
            break

    for token in _NAMED_VENUE_FALLBACK:
        if token in text and token not in seen:
            seen.add(token)
            hints.append(token)
            ev.append((token, token, 0.9))

    return hints, ev


def _infer_start_time(
    text: str,
    *,
    meal_time: str | None = None,
) -> tuple[str | None, float, str]:
    mor = _hits(text, _MORNING_HINTS)
    if meal_time and mor:
        return "09:00", 0.88, mor[0]

    m = re.search(r"(下午|晚上|早上|中午|上午)\s*(\d+)\s*点", text)
    if m:
        period, hour = m.group(1), int(m.group(2))
        if meal_time and period == "中午":
            return "09:00", 0.82, f"{m.group(0)}·出游出发"
        hour = _hour_from_period(period, hour)
        return f"{hour:02d}:00", 0.9, m.group(0)

    m = re.search(r"(\d+)\s*点", text)
    if m:
        if meal_time:
            return "09:00", 0.75, f"{m.group(0)}·出游出发"
        return f"{int(m.group(1)):02d}:00", 0.75, m.group(0)

    aft = _hits(text, _AFTERNOON_HINTS)
    if aft:
        return "14:00", 0.7, aft[0]
    eve = _hits(text, _EVENING_HINTS)
    if eve:
        return "18:00", 0.7, eve[0]
    mor = _hits(text, _MORNING_HINTS)
    if mor:
        return "09:00", 0.7, mor[0]
    return None, 0.4, ""


def _infer_duration(text: str) -> tuple[float, float, str]:
    m = re.search(r"(\d+)\s*小时", text)
    if m:
        return float(m.group(1)), 0.9, m.group(0)
    if "几个小时" in text:
        return 5.0, 0.75, "几个小时"
    if "下午" in text:
        return 5.0, 0.65, "下午"
    return 4.0, 0.5, "default"


def _infer_distance(text: str) -> tuple[float, float, str]:
    near = _hits(text, _NEAR_HINTS)
    if near:
        return 8.0, 0.85, near[0]
    return 10.0, 0.5, "default"


def _infer_dietary(text: str) -> tuple[list[str], list[tuple[str, str, float]]]:
    """返回 (tags, evidence_tuples)；evidence_tuples = (value, term, conf)。"""
    tags: list[str] = []
    ev: list[tuple[str, str, float]] = []
    low_hits = _hits(text, _LOW_CAL_KEYWORDS)
    if low_hits:
        tags.append("低卡")
        ev.append(("低卡", low_hits[0], 0.85))
    no_spicy = _hits(text, _NO_SPICY_KEYWORDS)
    if no_spicy:
        tags.append("不辣")
        ev.append(("不辣", no_spicy[0], 0.85))
    heavy_hits = _hits(text, _HEAVY_FLAVOR_KEYWORDS)
    if heavy_hits:
        tags.append("重口味")
        ev.append(("重口味", heavy_hits[0], 0.88))
    return tags, ev


def _infer_interests(
    text: str, scene: str, kids_ages: list[int]
) -> tuple[list[str], list[tuple[str, str, float]]]:
    text_low = text.lower()
    tags: list[str] = []
    ev: list[tuple[str, str, float]] = []
    if scene == "family" and kids_ages:
        tags.append("亲子")
        ev.append(("亲子", f"scene=family+kids={kids_ages}", 0.85))
    for tag, kws in _INTEREST_KEYWORDS.items():
        if tag in tags:
            continue
        for k in kws:
            if k.lower() in text_low:
                tags.append(tag)
                ev.append((tag, k, 0.8))
                break
    return tags, ev


def _infer_budget(text: str) -> tuple[int | None, float, str]:
    for pat, label in _BUDGET_PATTERNS:
        m = pat.search(text)
        if m:
            return int(m.group(1)), 0.9, f"{label}={m.group(0)}"
    m = re.search(r"(\d+)\s*以内", text)
    if m:
        return int(m.group(1)), 0.88, f"以内={m.group(0)}"
    m = re.search(r"不超过\s*(\d+)", text)
    if m:
        return int(m.group(1)), 0.88, f"不超过={m.group(0)}"
    return None, 0.4, ""


def _infer_district(text: str) -> tuple[str | None, float, str]:
    for name in _DISTRICT_NAMES:
        token = f"{name}区"
        if token in text or name in text:
            return token, 0.9, token
    return None, 0.4, ""


def _infer_cuisine_tags(text: str) -> tuple[list[str], list[tuple[str, str, float]]]:
    tags: list[str] = []
    ev: list[tuple[str, str, float]] = []
    for kw, label in _CUISINE_KEYWORDS:
        if kw in text and label not in tags:
            tags.append(label)
            ev.append((label, kw, 0.85))
    return tags, ev


# ─────────────────────────── 历史偏好融合 ───────────────────────────


def _build_history_weights(history: Mapping[str, Any]) -> dict[str, float]:
    """把历史 dict 汇总成 {tag: weight}，weight 归一化到 [0,1]，top-5。"""
    counter: dict[str, float] = {}
    for src in ("tag_counts", "cuisine_counts", "category_counts"):
        for k, v in (history.get(src) or {}).items():
            if not isinstance(k, str) or not isinstance(v, (int, float)) or v <= 0:
                continue
            counter[k] = counter.get(k, 0.0) + float(v)
    # favorite_tags 视作命中 3 次（明示偏好权重最高）
    for t in history.get("favorite_tags") or []:
        if isinstance(t, str):
            counter[t] = counter.get(t, 0.0) + 3.0

    if not counter:
        return {}
    top = sorted(counter.items(), key=lambda x: -x[1])[:5]
    max_v = top[0][1] or 1.0
    return {k: round(v / max_v, 3) for k, v in top}


def _merge_history(
    profile: GroupProfile, history: Mapping[str, Any], evidence: list[ProfileEvidence]
) -> None:
    weights = _build_history_weights(history)
    profile.history_weights = weights
    for tag, w in weights.items():
        if w >= 0.55 and tag not in profile.interests:
            profile.interests.append(tag)
            evidence.append(
                ProfileEvidence(
                    field="interests",
                    value=tag,
                    term=f"history(w={w:.2f})",
                    confidence=min(0.9, 0.5 + w / 2),
                    source="history",
                )
            )


# ─────────────────────────── 可编辑标签 ───────────────────────────


_SCENE_LABEL = {
    "family": "家庭",
    "friends": "朋友",
    "couple": "情侣",
    "solo": "独自",
    "unknown": "未识别",
}


_PEOPLE_INTEREST_RE = re.compile(r"^\d+人?$")


def has_explicit_heavy_dietary(profile: GroupProfile) -> bool:
    return bool(_EXPLICIT_HEAVY_DIETARY & set(profile.dietary))


def apply_explicit_preference_priority(profile: GroupProfile) -> GroupProfile:
    """显式菜系/重口味优先：自动拿掉隐式档案叠加的健康约束。"""
    if not has_explicit_heavy_dietary(profile):
        return profile
    kept = [d for d in profile.dietary if d not in _IMPLICIT_ARCHIVE_DIETARY]
    forbidden = [
        tag for tag in profile.forbidden_tags if tag not in _IMPLICIT_SPICY_FORBIDDEN
    ]
    if len(kept) == len(profile.dietary) and len(forbidden) == len(profile.forbidden_tags):
        return profile
    return profile.model_copy(update={"dietary": kept, "forbidden_tags": forbidden})


def _sanitize_profile_consistency(profile: GroupProfile) -> GroupProfile:
    """去掉人数/场景自相矛盾的画像（如 独自 + 1人 + 兴趣「3人」）。"""
    profile.interests = [
        i for i in profile.interests if not _PEOPLE_INTEREST_RE.match(str(i).strip())
    ]

    if profile.people_count >= 3 and profile.scene in ("solo", "unknown"):
        profile.scene = "friends"
    elif profile.people_count == 2 and profile.scene == "solo":
        profile.scene = "couple"
    elif profile.people_count == 1 and profile.scene == "friends":
        profile.people_count = max(profile.people_count, 3)
        profile.scene = "friends"
    elif profile.people_count == 1 and profile.scene == "family":
        profile.people_count = max(profile.people_count, 3)

    if profile.scene == "friends" and profile.people_count < 2:
        profile.people_count = 4
    if profile.scene == "family" and profile.people_count < 2:
        profile.people_count = 3

    return profile


def _build_editable_tags(profile: GroupProfile, has_history: bool) -> list[EditableTag]:
    profile = _sanitize_profile_consistency(profile)
    tags: list[EditableTag] = [
        EditableTag(
            key="scene",
            label=_SCENE_LABEL.get(profile.scene, profile.scene),
            value=profile.scene,
            confidence=profile.confidence.get("scene", 0.5),
            source="utterance",
        ),
        EditableTag(
            key="people_count",
            label=f"{profile.people_count} 人",
            value=str(profile.people_count),
            confidence=profile.confidence.get("people_count", 0.5),
            source="utterance",
        ),
        EditableTag(
            key="distance_limit_km",
            label=f"≤ {profile.distance_limit_km:.0f} km",
            value=f"{profile.distance_limit_km}",
            confidence=profile.confidence.get("distance_limit_km", 0.5),
            source="utterance",
        ),
        EditableTag(
            key="duration_hours",
            label=f"约 {profile.duration_hours:.0f} 小时",
            value=f"{profile.duration_hours}",
            confidence=profile.confidence.get("duration_hours", 0.5),
            source="utterance",
        ),
    ]
    if profile.kids_ages:
        tags.append(
            EditableTag(
                key="kids_ages",
                label="孩子 " + "、".join(f"{a}岁" for a in profile.kids_ages),
                value=",".join(str(a) for a in profile.kids_ages),
                confidence=0.9,
                source="utterance",
            )
        )
    if profile.start_time:
        tags.append(
            EditableTag(
                key="start_time",
                label=f"{profile.start_time} 出发",
                value=profile.start_time,
                confidence=profile.confidence.get("start_time", 0.5),
                source="utterance",
            )
        )
    if profile.budget_per_person is not None:
        tags.append(
            EditableTag(
                key="budget_per_person",
                label=f"约 ¥{profile.budget_per_person}/人",
                value=str(profile.budget_per_person),
                confidence=profile.confidence.get("budget_per_person", 0.5),
                source="utterance",
            )
        )
    if profile.district:
        tags.append(
            EditableTag(
                key="district",
                label=profile.district,
                value=profile.district,
                confidence=profile.confidence.get("district", 0.5),
                source="utterance",
            )
        )
    for d in profile.dietary:
        tags.append(
            EditableTag(
                key="dietary",
                label=d,
                value=d,
                confidence=profile.confidence.get("dietary", 0.7),
                source="utterance",
            )
        )
    for i in profile.interests:
        is_from_history = has_history and i in profile.history_weights
        tags.append(
            EditableTag(
                key="interests",
                label=i + ("（历史）" if is_from_history else ""),
                value=i,
                confidence=profile.confidence.get("interests", 0.7),
                source="history" if is_from_history else "utterance",
            )
        )
    return tags


# ─────────────────────────── 入口 ───────────────────────────


def analyze_profile(
    text: str,
    *,
    history_context: Mapping[str, Any] | None = None,
) -> GroupProfile:
    """规则引擎抽取群体画像。

    Args:
        text: 用户一句话。
        history_context: 可选历史上下文（`favorite_tags` / `tag_counts` /
            `cuisine_counts` / `category_counts`）。
    """
    text = text or ""
    profile = GroupProfile(raw_text=text)
    evidence: list[ProfileEvidence] = []

    scene, scene_conf, scene_terms = _infer_scene(text)
    profile.scene = scene
    profile.confidence["scene"] = scene_conf
    if scene_terms or scene != "solo":
        evidence.append(
            ProfileEvidence(
                field="scene",
                value=scene,
                term="/".join(scene_terms) if scene_terms else "default",
                confidence=scene_conf,
                source="utterance" if scene_terms else "rule",
            )
        )

    people, people_conf, people_term = _infer_people(text, scene)
    profile.people_count = people
    profile.confidence["people_count"] = people_conf
    evidence.append(
        ProfileEvidence(
            field="people_count",
            value=str(people),
            term=people_term,
            confidence=people_conf,
            source="utterance" if not people_term.startswith("default") else "rule",
        )
    )

    kids_ages, kids_terms = _infer_kids_ages(text, scene)
    profile.kids_ages = kids_ages
    if kids_ages:
        evidence.append(
            ProfileEvidence(
                field="kids_ages",
                value=",".join(str(a) for a in kids_ages),
                term="/".join(kids_terms),
                confidence=0.9,
                source="utterance",
            )
        )

    meal_time, mt_conf, mt_term = _infer_meal_time(text)
    profile.meal_time = meal_time
    profile.confidence["meal_time"] = mt_conf
    if meal_time:
        evidence.append(
            ProfileEvidence(
                field="meal_time",
                value=meal_time,
                term=mt_term,
                confidence=mt_conf,
                source="utterance",
            )
        )

    start_time, st_conf, st_term = _infer_start_time(text, meal_time=meal_time)
    profile.start_time = start_time
    profile.confidence["start_time"] = st_conf
    if start_time:
        evidence.append(
            ProfileEvidence(
                field="start_time",
                value=start_time,
                term=st_term,
                confidence=st_conf,
                source="utterance",
            )
        )

    venues, venue_ev = _infer_preferred_venues(text)
    profile.preferred_venues = venues
    profile.confidence["preferred_venues"] = 0.9 if venues else 0.5
    for value, term, conf in venue_ev:
        evidence.append(
            ProfileEvidence(
                field="preferred_venues",
                value=value,
                term=term,
                confidence=conf,
                source="utterance",
            )
        )

    duration, du_conf, du_term = _infer_duration(text)
    profile.duration_hours = duration
    profile.confidence["duration_hours"] = du_conf
    evidence.append(
        ProfileEvidence(
            field="duration_hours",
            value=f"{duration}",
            term=du_term,
            confidence=du_conf,
            source="utterance" if du_term != "default" else "rule",
        )
    )

    distance, dist_conf, dist_term = _infer_distance(text)
    profile.distance_limit_km = distance
    profile.confidence["distance_limit_km"] = dist_conf
    evidence.append(
        ProfileEvidence(
            field="distance_limit_km",
            value=f"{distance}",
            term=dist_term,
            confidence=dist_conf,
            source="utterance" if dist_term != "default" else "rule",
        )
    )

    dietary, diet_ev = _infer_dietary(text)
    profile.dietary = dietary
    profile.confidence["dietary"] = 0.85 if dietary else 0.5
    for value, term, conf in diet_ev:
        evidence.append(
            ProfileEvidence(
                field="dietary", value=value, term=term,
                confidence=conf, source="utterance",
            )
        )

    interests, int_ev = _infer_interests(text, scene, profile.kids_ages)
    profile.interests = interests
    profile.confidence["interests"] = 0.8 if interests else 0.5
    for value, term, conf in int_ev:
        evidence.append(
            ProfileEvidence(
                field="interests", value=value, term=term,
                confidence=conf, source="utterance",
            )
        )

    budget, bud_conf, bud_term = _infer_budget(text)
    profile.budget_per_person = budget
    profile.confidence["budget_per_person"] = bud_conf
    if budget is not None:
        evidence.append(
            ProfileEvidence(
                field="budget_per_person", value=str(budget), term=bud_term,
                confidence=bud_conf, source="utterance",
            )
        )

    district, dist_conf, dist_term = _infer_district(text)
    profile.district = district
    profile.confidence["district"] = dist_conf
    if district:
        evidence.append(
            ProfileEvidence(
                field="district", value=district, term=dist_term,
                confidence=dist_conf, source="utterance",
            )
        )

    cuisines, cuisine_ev = _infer_cuisine_tags(text)
    for label in cuisines:
        if label not in profile.dietary and label not in profile.interests:
            profile.dietary.append(label)
    for value, term, conf in cuisine_ev:
        evidence.append(
            ProfileEvidence(
                field="dietary", value=value, term=term,
                confidence=conf, source="utterance",
            )
        )

    has_history = bool(history_context)
    if has_history:
        _merge_history(profile, history_context, evidence)

    profile = apply_explicit_preference_priority(profile)
    profile = _sanitize_profile_consistency(profile)
    profile.evidence = evidence
    profile.editable_tags = _build_editable_tags(profile, has_history=has_history)
    return profile


def apply_profile_overrides(
    profile: GroupProfile,
    overrides: list[dict[str, str]],
) -> GroupProfile:
    """HIL：把前端点改标签合并回 GroupProfile，并重建 editable_tags。"""
    updated = profile.model_copy(deep=True)

    for item in overrides:
        key = (item.get("key") or "").strip()
        value = (item.get("value") or "").strip()
        action = (item.get("action") or "set").strip()

        if not key:
            continue

        if key == "dietary":
            if action == "remove":
                updated.dietary = [d for d in updated.dietary if d != value]
            elif action == "add" and value and value not in updated.dietary:
                updated.dietary.append(value)
            elif action == "set":
                updated.dietary = [value] if value else []
                if value:
                    updated.preferred_venues = []
                    updated.confidence["preferred_venues"] = 0.5
        elif key == "interests":
            if action == "remove":
                updated.interests = [i for i in updated.interests if i != value]
            elif action == "add" and value and value not in updated.interests:
                updated.interests.append(value)
            elif action == "set":
                updated.interests = [value] if value else []
        elif key == "district":
            if action == "remove":
                updated.district = None
            else:
                updated.district = value or None
                updated.confidence["district"] = 0.95
        elif key == "budget_per_person":
            if action == "remove":
                updated.budget_per_person = None
            else:
                try:
                    updated.budget_per_person = int(value)
                    updated.confidence["budget_per_person"] = 0.95
                except ValueError:
                    pass
        elif key == "scene" and value:
            updated.scene = value  # type: ignore[assignment]
            updated.confidence["scene"] = 0.95
        elif key == "people_count" and value:
            try:
                updated.people_count = max(1, int(value))
                updated.confidence["people_count"] = 0.95
            except ValueError:
                pass
        elif key == "distance_limit_km" and value:
            try:
                updated.distance_limit_km = max(1.0, float(value))
                updated.confidence["distance_limit_km"] = 0.95
            except ValueError:
                pass

    updated = apply_explicit_preference_priority(updated)
    updated = _sanitize_profile_consistency(updated)
    has_history = bool(updated.history_weights)
    updated.editable_tags = _build_editable_tags(updated, has_history=has_history)
    return updated
