"""顺路加餐/微行为目录（供 Planner suggest_insertions 使用）。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InsertableBehavior:
    id: str
    name: str
    duration_min: int
    cost: float
    category: str
    suitable_scenes: list[str] = field(default_factory=list)


INSERTABLE_CATALOG: list[InsertableBehavior] = [
    InsertableBehavior("bubble_tea", "买杯奶茶", 8, 20, "餐饮小食", ["family", "friends", "couple"]),
    InsertableBehavior("coffee", "顺路带杯咖啡", 5, 25, "餐饮小食", ["friends", "solo"]),
    InsertableBehavior("flower", "取一束鲜花", 10, 80, "礼物", ["family", "couple"]),
    InsertableBehavior("cake", "取预定的蛋糕", 10, 150, "礼物", ["family"]),
    InsertableBehavior("photo", "拍张合照留念", 5, 0, "纪念", ["family", "friends", "couple"]),
    InsertableBehavior("souvenir", "顺路逛文创店", 15, 50, "纪念", ["family", "friends"]),
    InsertableBehavior("snack", "路过小吃摊随手买", 10, 30, "餐饮小食", ["friends", "couple"]),
    InsertableBehavior("restroom", "找洗手间稍作休整", 10, 0, "休闲", ["family"]),
]
