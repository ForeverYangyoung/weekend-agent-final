"""核心领域模型（Pydantic）。LLM 输出的 JSON 全部通过这些模型校验。"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ─────────────────────────── 群体画像 ───────────────────────────


class EditableTag(BaseModel):
    """前端可点改的画像标签胶囊（对应 02.架构和agent.md §3.2 ui_chips）。"""

    key: str  # 对应 GroupProfile 的字段名，如 "scene" / "dietary"
    label: str  # 展示文案，如 "家庭" / "约 5 小时"
    value: str = ""  # 序列化后的值，前端编辑后回传
    confidence: float = 0.0  # 0~1，<0.6 视为低置信，UI 可弱化
    editable: bool = True
    source: Literal["utterance", "history", "rule"] = "rule"


class ProfileEvidence(BaseModel):
    """画像字段的证据链：依据哪句关键词、来自哪里。"""

    field: str  # 影响的字段，如 "scene" / "dietary"
    value: str  # 推断值的字符串形态
    term: str = ""  # 触发的原文片段，如 "老婆孩子"
    confidence: float = 0.0
    source: Literal["utterance", "history", "rule"] = "utterance"


class GroupProfile(BaseModel):
    """从用户一句话里抽取出的群体画像。"""

    scene: Literal["family", "friends", "couple", "solo", "unknown"] = "unknown"
    people_count: int = 1
    kids_ages: list[int] = Field(default_factory=list)
    distance_limit_km: float = 10.0
    duration_hours: float = 4.0
    start_time: str | None = None  # ISO 字符串，None 表示尽快出发
    meal_time: str | None = None  # 用户锚定的用餐时刻，如「中午12点想吃」
    preferred_venues: list[str] = Field(default_factory=list)  # 点名店名，如「川一哥」
    dietary: list[str] = Field(default_factory=list)  # 例 ["低卡", "不辣"]
    forbidden_tags: list[str] = Field(default_factory=list)  # 历史禁忌，例 ["重辣", "特辣"]
    interests: list[str] = Field(default_factory=list)  # 例 ["亲子", "展览"]
    budget_per_person: int | None = None
    district: str | None = None  # 目标区域，如「海淀区」
    raw_text: str = ""
    # 每字段置信度（0~1），缺失字段视为 0.5
    confidence: dict[str, float] = Field(default_factory=dict)
    # 给前端的可编辑标签；空表示前端不展示
    editable_tags: list[EditableTag] = Field(default_factory=list)
    # 每个字段的证据链；面试可亮「依据哪句话推出来的」
    evidence: list[ProfileEvidence] = Field(default_factory=list)
    # 历史偏好权重（来自 history_context），0~1，越大越喜欢
    history_weights: dict[str, float] = Field(default_factory=dict)


# ─────────────────────────── 打分明细 ───────────────────────────


class ScoreBreakdown(BaseModel):
    """五维打分明细，附在 POICandidate.breakdown。

    评委追问「为啥选 A 不选 B」时，可亮明细。
    """

    preference: float = 0.0  # 标签匹配 35%
    history: float = 0.0  # 历史偏好 20%
    rating: float = 0.0  # POI 评分 20%
    distance: float = 0.0  # 距离 15%
    budget: float = 0.0  # 预算 10%
    total: float = 0.0


# ─────────────────────────── 方案 ───────────────────────────


class POICandidate(BaseModel):
    poi_id: str
    name: str
    category: str  # 餐厅 / 活动 / 加餐 等
    score: float = 0.0
    reason: str = ""  # 为什么推这家（可解释性）
    metadata: dict = Field(default_factory=dict)  # avg_price / distance_km / open_hours / tags 等
    # 五维加权打分明细，None 表示尚未打分（如 stub 兜底方案）
    breakdown: ScoreBreakdown | None = None


class PlanAddon(BaseModel):
    """HIL 可选附加项：用户勾选后才在 Executor 下单。"""

    addon_id: str
    type: str = "surprise"  # refresh / surprise
    description: str
    poi_id: str
    target_poi_id: str
    price: int = 0


class PlanStage(BaseModel):
    """方案的一个阶段。一个阶段对应一段时间窗口和一个动作。"""

    name: str  # "玩" / "吃" / "加餐" / "通勤"
    start_time: str  # "14:00"
    end_time: str  # "16:00"
    primary: POICandidate
    backups: list[POICandidate] = Field(default_factory=list)
    notes: str = ""


class Plan(BaseModel):
    summary: str = ""
    stages: list[PlanStage] = Field(default_factory=list)
    total_duration_hours: float = 0.0
    total_cost_estimate: int = 0  # 单位：元
    # 方案总分（取所有 stage.primary.breakdown.total 平均）；用于 Top-K 排序
    score: float = 0.0
    # 阶段顺序，例如 "玩→吃→加餐" / "吃→玩→加餐"，给评委展示「试过多种顺序」
    order_label: str = ""
    addons: list[PlanAddon] = Field(default_factory=list)
    is_compromised: bool = False
    compromise_message: str = ""
    compromise_source: Literal["", "researcher_relax", "planner_fallback", "recovery"] = ""


# ─────────────────────────── Researcher 输出 ───────────────────────────


class ResearchStageResult(BaseModel):
    """单个阶段（玩/吃/加餐）的检索结果。"""

    stage_name: str
    candidates: list[POICandidate] = Field(default_factory=list)
    selected: POICandidate | None = None


class ResearchResult(BaseModel):
    """Researcher 节点输出：分阶段 POI 候选 + 工具调用追踪。"""

    stages: list[ResearchStageResult] = Field(default_factory=list)
    tool_trace: list[str] = Field(default_factory=list)


# ─────────────────────────── Critic 反馈 ───────────────────────────


class CriticIssue(BaseModel):
    severity: Literal["block", "warn"] = "warn"
    field: str  # 涉及的字段，如 "stages[1].primary"
    message: str


class CriticFeedback(BaseModel):
    approved: bool = True
    issues: list[CriticIssue] = Field(default_factory=list)


# ─────────────────────────── Tool 调用记录 ───────────────────────────


class ToolStatus(str, Enum):
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ToolCall(BaseModel):
    """一次 Tool 调用的全量记录（用于 DryRun / Executor / Compensator）。"""

    id: str  # 全局唯一，便于回滚定位
    stage_name: str  # 属于 Plan 的哪个阶段
    tool_name: str
    args: dict = Field(default_factory=dict)
    status: ToolStatus = ToolStatus.PENDING
    result: dict | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


# ─────────────────────────── 行程卡（最终交付） ───────────────────────────


class SummaryCard(BaseModel):
    title: str
    body_markdown: str
    share_text: str  # 给老婆/朋友的微信可分享文案


# ─────────────────────────── 故障自愈 & 多人协同 ───────────────────────────


class FailureType(str, Enum):
    """三类可自愈故障（LangGraph 全局流实时读取）。"""

    NO_SEAT = "NO_SEAT"  # 409 满座
    NO_TICKET = "NO_TICKET"  # 404/410 售罄无票
    CONFLICT = "CONFLICT"  # 时间重叠 / 行程超时


class CollaborativeConsensus(BaseModel):
    """多人协同共识槽：投票与反馈，供 HIL / Notifier 读取。"""

    shared_users: list[str] = Field(
        default_factory=lambda: ["User_A", "User_B", "User_C"]
    )
    votes: dict[str, dict[str, bool]] = Field(default_factory=dict)
    feedback_notes: list[str] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    """动态时间轴事件（Compensator 压缩用）。"""

    stage_name: str
    poi_id: str
    name: str
    start_time: str
    end_time: str
    duration_minutes: int
    is_core_constraint: bool = False
    weight: float = 1.0


class ConstraintTracker(BaseModel):
    """硬约束追踪：重规划每轮必须校验，AI 不得选违反约束的商户。"""

    remaining_calories: float = 600.0
    child_fatigue_index: int = 0  # 0~100，>80 须切休息/室内
    accepted_cuisines: list[str] = Field(default_factory=list)
