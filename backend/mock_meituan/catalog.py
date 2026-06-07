"""Mock 美团：POI 目录数据（取代旧 `agents/researcher.py::_CATALOG`）。

数据布局：
  CATALOG[scene][stage] -> list[dict]，每个 dict 字段对齐 POICandidate：
    poi_id / name / category / score / reason / metadata{avg_price, distance_km}

P1 升级：把这份数据塞进真 mock DB（sqlite / json 文件），路由按 scene+stage 查。
"""
from __future__ import annotations

from typing import Any

# 语义化商户目录：多维度 metadata，支撑家庭/朋友冲突场景（减肥 vs 火锅 vs 亲子）
MOCK_MERCHANTS: dict[str, dict[str, Any]] = {
    "poi_001": {
        "poi_id": "poi_001",
        "name": "绿野低卡轻食（中关村店）",
        "category": "轻食",
        "score": 0.91,
        "reason": "低卡健康约束，适合控热量；4人小桌",
        "metadata": {
            "avg_price": 72,
            "distance_km": 4,
            "district": "海淀区",
            "tags": ["轻食", "低卡", "健康", "减脂"],
            "avg_calories_per_meal": 350,
            "is_low_calorie": True,
            "has_kids_zone": False,
            "max_party_size": 4,
        },
    },
    "poi_002": {
        "poi_id": "poi_002",
        "name": "疯狂原始人儿童乐园",
        "category": "亲子活动",
        "score": 0.93,
        "reason": "强亲子属性，3-7岁室内游乐",
        "metadata": {
            "avg_price": 88,
            "distance_km": 5,
            "district": "朝阳区",
            "tags": ["亲子", "儿童", "室内", "游乐场"],
            "suitable_ages": [3, 4, 5, 6, 7],
            "kid_friendly": True,
            "is_indoor": True,
        },
    },
    "poi_003": {
        "poi_id": "poi_003",
        "name": "川一哥地道老火锅",
        "category": "火锅",
        "score": 0.88,
        "reason": "聚会重口味，高辣高卡；8人大桌，易触发群体冲突",
        "metadata": {
            "avg_price": 110,
            "distance_km": 3,
            "district": "朝阳区",
            "tags": ["火锅", "聚餐", "重口味", "麻辣"],
            "avg_calories_per_meal": 1200,
            "has_kids_zone": False,
            "max_party_size": 8,
            "is_crowded": True,
        },
    },
}

CATALOG: dict[str, dict[str, list[dict[str, Any]]]] = {
    "family": {
        "玩": [
            {
                "poi_id": "poi_park_001",
                "name": "奥林匹克森林公园",
                "category": "亲子活动",
                "score": 0.92,
                "reason": "离家 6km，有儿童游乐区，5 岁孩子合适",
                "metadata": {
                    "avg_price": 0,
                    "distance_km": 6,
                    "district": "朝阳区",
                    "tags": ["户外", "亲子", "奥森"],
                },
            },
            {
                "poi_id": "poi_park_002",
                "name": "朝阳公园童趣园",
                "category": "亲子活动",
                "score": 0.85,
                "reason": "距离稍远但游乐设施更丰富",
                "metadata": {
                    "avg_price": 50,
                    "distance_km": 9,
                    "district": "朝阳区",
                    "tags": ["户外", "亲子", "朝阳公园"],
                },
            },
            {
                "poi_id": "poi_park_003",
                "name": "海洋馆儿童区",
                "category": "亲子活动",
                "score": 0.80,
                "reason": "室内场地避免户外天气影响",
                "metadata": {
                    "avg_price": 120,
                    "distance_km": 8,
                    "district": "西城区",
                    "tags": ["室内", "亲子", "海洋馆"],
                },
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
                "reason": "奥森北园出口步行 5 分钟，低卡沙拉；有儿童椅",
                "metadata": {
                    "avg_price": 80,
                    "distance_km": 5.5,
                    "district": "朝阳区",
                    "tags": ["轻食", "沙拉", "低卡"],
                },
            },
            {
                "poi_id": "poi_rest_jp_001",
                "name": "禾绿回转寿司（奥森店）",
                "category": "日料",
                "score": 0.87,
                "reason": "奥森南门附近，家庭友好日料，有儿童餐",
                "metadata": {
                    "avg_price": 95,
                    "distance_km": 6,
                    "district": "朝阳区",
                    "tags": ["日料", "寿司", "亲子"],
                },
            },
            {
                "poi_id": "poi_rest_os_superbowl",
                "name": "超级碗轻食（奥森北园店）",
                "category": "轻食",
                "score": 0.86,
                "reason": "能量碗份量足，玩完奥森顺路吃；低卡健康",
                "metadata": {
                    "avg_price": 85,
                    "distance_km": 6,
                    "district": "朝阳区",
                    "tags": ["轻食", "健康", "低卡"],
                },
            },
            {
                "poi_id": "poi_rest_os_sichuan",
                "name": "蜀香门第（亚运村店）",
                "category": "川菜",
                "score": 0.83,
                "reason": "奥森玩完顺路，地道川菜，微辣可选",
                "metadata": {
                    "avg_price": 78,
                    "distance_km": 5,
                    "district": "朝阳区",
                    "tags": ["川菜", "地道"],
                },
            },
            {
                "poi_id": "poi_rest_os_hotpot",
                "name": "海底捞（亚运村店）",
                "category": "火锅",
                "score": 0.85,
                "reason": "奥森商圈火锅，儿童餐椅齐全",
                "metadata": {
                    "avg_price": 98,
                    "distance_km": 6,
                    "district": "朝阳区",
                    "tags": ["火锅", "聚餐", "亲子"],
                },
            },
            {
                "poi_id": "poi_rest_022",
                "name": "绿茶餐厅（万柳店）",
                "category": "江浙菜",
                "score": 0.78,
                "reason": "清淡江浙菜，儿童套餐，海淀公园顺路",
                "metadata": {
                    "avg_price": 90,
                    "distance_km": 5,
                    "district": "海淀区",
                    "tags": ["江浙菜", "清淡", "亲子"],
                },
            },
            {
                "poi_id": "poi_rest_023",
                "name": "新元素轻食（万柳店）",
                "category": "轻食",
                "score": 0.82,
                "reason": "海淀公园玩完顺路，低卡套餐",
                "metadata": {
                    "avg_price": 110,
                    "distance_km": 5,
                    "district": "海淀区",
                    "tags": ["轻食", "低卡"],
                },
            },
            {
                "poi_id": "poi_rest_hd_wagas",
                "name": "Wagas 轻食（海淀万柳店）",
                "category": "轻食",
                "score": 0.84,
                "reason": "离海淀公园近，沙拉碗适合控卡",
                "metadata": {
                    "avg_price": 82,
                    "distance_km": 4.5,
                    "district": "海淀区",
                    "tags": ["轻食", "沙拉", "低卡"],
                },
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
            {
                "poi_id": "poi_rest_cy_green",
                "name": "绿茶餐厅（朝阳公园店）",
                "category": "江浙菜",
                "score": 0.80,
                "reason": "朝阳公园西门对面，玩完即吃",
                "metadata": {
                    "avg_price": 88,
                    "distance_km": 9,
                    "district": "朝阳区",
                    "tags": ["江浙菜", "清淡", "亲子"],
                },
            },
            {
                "poi_id": "poi_rest_cy_light",
                "name": "沙野轻食（朝阳公园店）",
                "category": "轻食",
                "score": 0.79,
                "reason": "朝阳公园出口步行可达，低卡便当",
                "metadata": {
                    "avg_price": 72,
                    "distance_km": 9,
                    "district": "朝阳区",
                    "tags": ["轻食", "低卡", "沙拉"],
                },
            },
            {
                "poi_id": "poi_rest_cy_hotpot",
                "name": "海底捞（朝阳公园店）",
                "category": "火锅",
                "score": 0.83,
                "reason": "朝阳公园商圈，玩完顺路吃火锅",
                "metadata": {
                    "avg_price": 100,
                    "distance_km": 9,
                    "district": "朝阳区",
                    "tags": ["火锅", "聚餐"],
                },
            },
            {
                "poi_id": "poi_rest_aq_sushi",
                "name": "禾绿回转寿司（动物园店）",
                "category": "日料",
                "score": 0.86,
                "reason": "海洋馆出口步行 8 分钟，亲子日料",
                "metadata": {
                    "avg_price": 92,
                    "distance_km": 8,
                    "district": "西城区",
                    "tags": ["日料", "寿司", "亲子"],
                },
            },
            {
                "poi_id": "poi_rest_aq_light",
                "name": "外企食堂轻食（动物园店）",
                "category": "轻食",
                "score": 0.77,
                "reason": "海洋馆玩完顺路，低卡套餐",
                "metadata": {
                    "avg_price": 68,
                    "distance_km": 8,
                    "district": "西城区",
                    "tags": ["轻食", "低卡", "健康"],
                },
            },
            {
                "poi_id": "poi_rest_aq_hotpot",
                "name": "海底捞（动物园店）",
                "category": "火锅",
                "score": 0.81,
                "reason": "海洋馆商圈火锅，儿童服务周到",
                "metadata": {
                    "avg_price": 96,
                    "distance_km": 7,
                    "district": "西城区",
                    "tags": ["火锅", "聚餐", "亲子"],
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
            {
                "poi_id": "poi_drink_008",
                "name": "喜茶（送至公园出口）",
                "category": "加餐",
                "score": 0.84,
                "reason": "低糖果茶，玩完送至公园出口自提",
                "metadata": {"avg_price": 28, "distance_km": 0, "tags": ["饮品", "低糖"]},
            },
            {
                "poi_id": "poi_cake_009",
                "name": "味多美低糖蛋糕（送至餐厅）",
                "category": "加餐",
                "score": 0.78,
                "reason": "低糖蛋糕，用餐前送到餐厅",
                "metadata": {"avg_price": 42, "distance_km": 0, "tags": ["甜品", "低糖"]},
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
                    "is_crowded": True,
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


def _semantic_injections(scene: str, stage: str) -> list[dict[str, Any]]:
    """把 MOCK_MERCHANTS 按场景注入对应阶段。"""
    if stage == "吃":
        rows = [MOCK_MERCHANTS["poi_001"], MOCK_MERCHANTS["poi_003"]]
        if scene == "friends":
            return rows
        return rows
    if stage == "玩":
        return [MOCK_MERCHANTS["poi_002"]] if scene == "family" else []
    return []


def search(scene: str, stage: str, limit: int = 10) -> list[dict[str, Any]]:
    """按 scene + stage 查 POI；合并语义目录，按 poi_id 去重。"""
    bucket = CATALOG.get(scene) or CATALOG.get("family") or {}
    items = list(bucket.get(stage, []))
    seen = {row["poi_id"] for row in items}
    for row in _semantic_injections(scene, stage):
        if row["poi_id"] not in seen:
            items.insert(0, row)
            seen.add(row["poi_id"])
    return list(items[:limit])
