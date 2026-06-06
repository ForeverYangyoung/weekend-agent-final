"""Planner 共享状态与数据模型。

所有类型定义与 01-题目工程拆解.md §8 及 02.架构和agent.md §6 对齐。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# ── 枚举 ─────────────────────────────────────────────


class StageType(str, Enum):
    PLAY = "玩"
    EAT = "吃"
    ENRICH = "增"
    REST = "休息"
    EXTRA = "加餐"
    TRANSIT = "路途"


class TransportMode(str, Enum):
    WALK = "步行"
    SUBWAY = "地铁"
    TAXI = "打车"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLEDBACK = "rolledback"


# ── Profiler 产出的画像 ──────────────────────────────


@dataclass
class Role:
    role: str  # self, spouse, child
    age_group: str  # adult, child, toddler
    age: Optional[int] = None
    tags: list[str] = field(default_factory=list)


@dataclass
class TimeWindow:
    start: str  # "14:00"
    end: str  # "18:00"
    duration_hours: float = 4.0


@dataclass
class Geo:
    anchor: str  # 城市名或 GPS
    radius_km: float = 5.0


@dataclass
class BudgetRange:
    min: float = 100.0
    max: float = 300.0


@dataclass
class UserProfile:
    mode: str  # family | friends | mixed
    party_size: int
    roles: list[Role] = field(default_factory=list)
    time_window: TimeWindow = field(default_factory=TimeWindow)
    geo: Geo = field(default_factory=Geo)
    budget_per_person: BudgetRange = field(default_factory=BudgetRange)
    hard_filters: list[str] = field(default_factory=list)
    soft_preferences: list[str] = field(default_factory=list)
    history_hints: list[str] = field(default_factory=list)


# ── Mock API 返回值 ──────────────────────────────────


@dataclass
class POI:
    id: str
    name: str
    category: str  # 餐厅 | 景点 | 亲子 | 展览 | citywalk | 酒吧
    location: str
    avg_price: float
    tags: list[str] = field(default_factory=list)
    open_hours: str = "10:00-22:00"  # "HH:MM-HH:MM"
    rating: float = 4.0


@dataclass
class RouteResult:
    duration_min: float
    distance_km: float
    path: str = ""
    mode: str = "打车"


# ── 顺路插入行为 ──────────────────────────────────────


@dataclass
class InsertableBehavior:
    """可顺路插入的微行为（不占主时间，< 15min）。"""
    id: str
    name: str  # "买奶茶", "取花", "拍合照"
    duration_min: int  # 5~15
    cost: float  # 预估花费
    category: str  # "餐饮小食" | "礼物" | "休闲" | "纪念"
    suitable_scenes: list[str] = field(default_factory=list)  # ["family", "friends"]


@dataclass
class RouteInsertion:
    """一次具体的插入决策。"""
    behavior: InsertableBehavior
    inserted: bool  # LLM 决定是否插入
    position: str  # "玩→吃之间" / "吃之前" / "结束前"
    reason: str  # LLM 输出的判断理由
    display_text: str  # 给前端展示的一句话


# ── 可插入行为目录 ─────────────────────────────────────

INSERTABLE_CATALOG: list[InsertableBehavior] = [
    InsertableBehavior("bubble_tea", "买杯奶茶", 8, 20,
                       "餐饮小食", ["family", "friends", "couple"]),
    InsertableBehavior("coffee", "顺路带杯咖啡", 5, 25,
                       "餐饮小食", ["friends", "solo"]),
    InsertableBehavior("flower", "取一束鲜花", 10, 80,
                       "礼物", ["family", "couple"]),
    InsertableBehavior("cake", "取预定的蛋糕", 10, 150,
                       "礼物", ["family"]),
    InsertableBehavior("photo", "拍张合照留念", 5, 0,
                       "纪念", ["family", "friends", "couple"]),
    InsertableBehavior("souvenir", "顺路逛文创店", 15, 50,
                       "纪念", ["family", "friends"]),
    InsertableBehavior("snack", "路过小吃摊随手买", 10, 30,
                       "餐饮小食", ["friends", "couple"]),
    InsertableBehavior("restroom", "找洗手间稍作休整", 10, 0,
                       "休闲", ["family"]),
]


@dataclass
class TableResult:
    available: bool
    waiting_minutes: int = 0


@dataclass
class WeatherResult:
    condition: str
    temp: float = 20.0
    suitable_outdoor: bool = True


# ── 内部中间结构 ─────────────────────────────────────


@dataclass
class EnrichedPOI:
    """携带桌位 / 排队信息的 POI。"""
    poi: POI
    table_available: Optional[bool] = None
    waiting_minutes: int = 0
    queue_length: int = 0


@dataclass
class TimeSegment:
    stage_type: StageType
    start_at: str  # "14:00"
    end_at: str  # "15:30"
    target_duration_min: int
    category_filter: str  # 传给 search_poi 的 category


@dataclass
class TimelineSkeleton:
    segments: list[TimeSegment] = field(default_factory=list)
    meal_type: str = ""  # "午餐" | "晚餐"
    total_duration_min: int = 0


@dataclass
class StageAssignment:
    stage_type: StageType
    poi: Optional[POI] = None  # None 表示跳过该阶段
    route_from_prev: Optional[RouteResult] = None


@dataclass
class Combo:
    stages: list[StageAssignment] = field(default_factory=list)

    @property
    def total_duration_min(self) -> float:
        total = 0.0
        for s in self.stages:
            if s.poi is None:
                continue
            total += 90  # 每阶段默认 90 min（可调）
            if s.route_from_prev:
                total += s.route_from_prev.duration_min
        return total

    @property
    def total_cost(self) -> float:
        return sum(s.poi.avg_price for s in self.stages if s.poi is not None)

    @property
    def categories(self) -> list[str]:
        return [s.poi.category for s in self.stages if s.poi is not None]

    @property
    def poi_list(self) -> list["POI"]:
        return [s.poi for s in self.stages if s.poi is not None]


# ── 打分相关 ─────────────────────────────────────────

DEFAULT_WEIGHTS = {
    "preference": 0.30,
    "geo": 0.20,
    "time": 0.20,
    "rating": 0.15,
    "budget": 0.10,
    "diversity": 0.05,
}

GEO_SUB_WEIGHTS = {
    "route_efficiency": 0.50,
    "transport_fit": 0.30,
    "geo_cohesion": 0.20,
}


@dataclass
class GeoSubScores:
    s_route_efficiency: float = 0.5
    s_transport_fit: float = 0.5
    s_geo_cohesion: float = 0.5  # LLM 填充


@dataclass
class ScoreBreakdown:
    total: float = 0.0
    s_preference: float = 0.0
    s_geo: float = 0.0
    s_time: float = 0.0
    s_budget: float = 0.0
    s_rating: float = 0.0
    s_diversity: float = 0.0
    geo_subscores: GeoSubScores = field(default_factory=GeoSubScores)


@dataclass
class ScoredPlan:
    rank: int
    combo: Combo
    score: float
    breakdown: ScoreBreakdown
    summary: str = ""
    llm_calibrated: bool = False
    insertions: list["RouteInsertion"] = field(default_factory=list)


# ── 工具追踪 ─────────────────────────────────────────


@dataclass
class ToolTrace:
    tool_name: str
    input_params: dict = field(default_factory=dict)
    output_summary: dict = field(default_factory=dict)
    duration_ms: float = 0.0
    status: str = ""  # success | failed | timeout


# ── LangGraph State ───────────────────────────────────

@dataclass
class PlannerState:
    """全链路共享状态，与 02 文档 §6 对齐。"""
    raw_query: str = ""
    profile: Optional[UserProfile] = None
    confidence: dict[str, float] = field(default_factory=dict)
    profile_overrides: dict[str, Any] = field(default_factory=dict)
    tool_trace: list[ToolTrace] = field(default_factory=list)
    candidates: dict[str, list[EnrichedPOI]] = field(default_factory=dict)
    scored_plans: list[ScoredPlan] = field(default_factory=list)
    selected_plan_id: Optional[int] = None
    errors: list[str] = field(default_factory=list)
    tool_round: int = 0
    max_tool_rounds: int = 6
    skeleton: Optional[TimelineSkeleton] = None


def create_initial_state(raw_query: str, profile: UserProfile) -> PlannerState:
    return PlannerState(raw_query=raw_query, profile=profile)
