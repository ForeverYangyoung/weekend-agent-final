"""Mock 美团：POI 目录数据（取代旧 `agents/researcher.py::_CATALOG`）。

数据布局：
  CATALOG[scene][stage] -> list[dict]，每个 dict 字段对齐 POICandidate：
    poi_id / name / category / score / reason / metadata{avg_price, distance_km}

P1 升级：把这份数据塞进真 mock DB（sqlite / json 文件），路由按 scene+stage 查。
"""
from __future__ import annotations

from typing import Any

CATALOG: dict[str, dict[str, list[dict[str, Any]]]] = {
    "family": {
        "玩": [
            {
                "poi_id": "poi_park_001",
                "name": "奥林匹克森林公园",
                "category": "亲子活动",
                "score": 0.92,
                "reason": "离家 6km，有儿童游乐区，5 岁孩子合适",
                "metadata": {"avg_price": 0, "distance_km": 6},
            },
            {
                "poi_id": "poi_park_002",
                "name": "朝阳公园童趣园",
                "category": "亲子活动",
                "score": 0.85,
                "reason": "距离稍远但游乐设施更丰富",
                "metadata": {"avg_price": 50, "distance_km": 9},
            },
            {
                "poi_id": "poi_park_003",
                "name": "海洋馆儿童区",
                "category": "亲子活动",
                "score": 0.80,
                "reason": "室内场地避免户外天气影响",
                "metadata": {"avg_price": 120, "distance_km": 8},
            },
            {
                "poi_id": "poi_park_hd_001",
                "name": "海淀公园",
                "category": "亲子活动",
                "score": 0.86,
                "reason": "海淀区亲子散步，湖面骑行",
                "metadata": {
                    "avg_price": 0,
                    "distance_km": 5,
                    "district": "海淀区",
                    "tags": ["户外", "亲子", "海淀"],
                },
            },
        ],
        "吃": [
            {
                "poi_id": "poi_rest_021",
                "name": "Wagas 沙拉轻食（奥森店）",
                "category": "轻食",
                "score": 0.88,
                "reason": "低卡轻食沙拉，符合减肥需求；有儿童椅",
                "metadata": {
                    "avg_price": 80,
                    "distance_km": 1,
                    "tags": ["轻食", "沙拉", "低卡"],
                },
            },
            {
                "poi_id": "poi_rest_jp_001",
                "name": "禾绿回转寿司（奥森店）",
                "category": "日料",
                "score": 0.87,
                "reason": "家庭友好日料，有儿童餐；刺身新鲜",
                "metadata": {
                    "avg_price": 95,
                    "distance_km": 2,
                    "tags": ["日料", "寿司", "亲子"],
                },
            },
            {
                "poi_id": "poi_rest_022",
                "name": "绿茶餐厅",
                "category": "江浙菜",
                "score": 0.78,
                "reason": "清淡选择多，儿童套餐",
                "metadata": {"avg_price": 90, "distance_km": 2, "tags": ["江浙菜", "清淡"]},
            },
            {
                "poi_id": "poi_rest_023",
                "name": "新元素轻食",
                "category": "轻食",
                "score": 0.75,
                "reason": "低卡套餐",
                "metadata": {"avg_price": 110, "distance_km": 3, "tags": ["轻食", "低卡"]},
            },
            {
                "poi_id": "poi_rest_hd_sichuan",
                "name": "川味小馆（海淀店）",
                "category": "川菜",
                "score": 0.91,
                "reason": "海淀区地道川菜，人均亲民",
                "metadata": {
                    "avg_price": 75,
                    "distance_km": 4,
                    "district": "海淀区",
                    "tags": ["川菜", "地道", "高性价比"],
                },
            },
            {
                "poi_id": "poi_rest_hd_hotpot",
                "name": "海底捞（中关村店）",
                "category": "火锅",
                "score": 0.84,
                "reason": "海淀商圈火锅，适合聚餐",
                "metadata": {
                    "avg_price": 95,
                    "distance_km": 6,
                    "district": "海淀区",
                    "tags": ["火锅", "聚餐"],
                },
            },
        ],
        "加餐": [
            {
                "poi_id": "poi_cake_007",
                "name": "原麦山丘 小蛋糕（送至餐厅）",
                "category": "加餐",
                "score": 0.81,
                "reason": "低糖款，给孩子的小惊喜",
                "metadata": {"avg_price": 35, "distance_km": 0},
            },
        ],
    },
    "friends": {
        "玩": [
            {
                "poi_id": "poi_act_101",
                "name": "罪有引力剧本杀（三里屯店）",
                "category": "活动",
                "score": 0.90,
                "reason": "4 人本，2 男 2 女均衡",
                "metadata": {"avg_price": 120, "distance_km": 2, "district": "三里屯"},
            },
            {
                "poi_id": "poi_act_102",
                "name": "开心麻花密室",
                "category": "活动",
                "score": 0.83,
                "reason": "评价高",
                "metadata": {"avg_price": 140, "distance_km": 2.5, "district": "三里屯"},
            },
        ],
        "吃": [
            {
                "poi_id": "poi_rest_201",
                "name": "姜虎东白丁烤肉（三里屯）",
                "category": "烤肉",
                "score": 0.89,
                "reason": "4 人聚餐口碑高，网红打卡",
                "metadata": {
                    "avg_price": 160,
                    "distance_km": 1,
                    "tags": ["烤肉", "网红打卡", "社交", "重口味"],
                    "table_type": ["4人桌"],
                },
            },
            {
                "poi_id": "poi_rest_202",
                "name": "炙烤大叔",
                "category": "烤肉",
                "score": 0.82,
                "reason": "人均稍低，4 人桌充足",
                "metadata": {
                    "avg_price": 110,
                    "distance_km": 2,
                    "tags": ["烤肉", "社交", "高性价比", "重口味"],
                    "table_type": ["4人桌"],
                },
            },
            {
                "poi_id": "poi_rest_203",
                "name": "Wagas 轻食（三里屯）",
                "category": "轻食",
                "score": 0.86,
                "reason": "4 人窗边位，沙拉碗适合聚餐",
                "metadata": {
                    "avg_price": 95,
                    "distance_km": 1.5,
                    "tags": ["轻食", "沙拉", "低卡", "社交"],
                    "table_type": ["4人桌"],
                },
            },
            {
                "poi_id": "poi_rest_204",
                "name": "超级碗轻食（三里屯）",
                "category": "轻食",
                "score": 0.81,
                "reason": "能量碗份量足，4 人分享友好",
                "metadata": {
                    "avg_price": 85,
                    "distance_km": 2,
                    "tags": ["轻食", "健康", "低卡", "社交"],
                    "table_type": ["4人桌"],
                },
            },
        ],
        "加餐": [
            {
                "poi_id": "poi_flower_009",
                "name": "花点时间 小花束（送至餐厅）",
                "category": "加餐",
                "score": 0.76,
                "reason": "给女生的小惊喜",
                "metadata": {"avg_price": 80, "distance_km": 0},
            },
        ],
    },
}


def search(scene: str, stage: str, limit: int = 10) -> list[dict[str, Any]]:
    """按 scene + stage 查 POI；scene 缺省回退到 family，stage 不存在返回空。"""
    bucket = CATALOG.get(scene) or CATALOG.get("family") or {}
    items = bucket.get(stage, [])
    return list(items[:limit])
