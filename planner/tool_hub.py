"""工具调用中枢 — 统一封装所有外部调用。

职责：
  1. 重试：指数退避 (1s, 2s, 4s)，最多 3 次（01 文档 §7 E-03）
  2. 缓存：避免相同参数重复调用（同次规划内）
  3. 追踪：每次调用产出一致的 ToolTrace
  4. 降级：失败时返回安全默认值，绝不抛异常

内部依赖 retriever（裸 HTTP）和 llm_wrapper（裸 LLM），
对外暴露带质量的 safe_* 方法。
"""

import time
from typing import Optional

from planner.llm_wrapper import LLMClient
from planner.retriever import (
    check_queue,
    check_table,
    get_poi_detail,
    get_route,
    get_weather,
    search_poi,
)
from planner.state import (
    EnrichedPOI,
    POI,
    RouteResult,
    TableResult,
    TransportMode,
    WeatherResult,
)
from planner.trace import TraceLogger


# ── 配置 ──────────────────────────────────────────────

MAX_RETRIES = 3
RETRY_BACKOFF = [1.0, 2.0, 4.0]  # seconds
MAX_CACHE_SIZE = 200


class ToolHub:
    """所有外部调用经此中枢，提供重试 + 缓存 + 追踪 + 降级。"""

    def __init__(self, llm: LLMClient | None = None,
                 tracer: TraceLogger | None = None):
        self.llm = llm or LLMClient()
        self.tracer = tracer or TraceLogger()
        self._route_cache: dict[tuple, RouteResult] = {}
        self._poi_cache: dict[str, list[POI]] = {}
        self._table_cache: dict[tuple, TableResult] = {}
        self._call_counts: dict[str, int] = {}  # 去重统计

    # ── 安全检索 ──────────────────────────────────────

    def safe_search_poi(self, category: str, location: str,
                        filters: dict | None = None,
                        size: int = 5) -> list[POI]:
        cache_key = _make_cache_key("search", category, location,
                                     str(filters), str(size))
        if cache_key in self._poi_cache:
            return self._poi_cache[cache_key]

        with self.tracer.span("search_poi", category=category,
                              location=location, size=size) as span:
            try:
                result = self._retry_call(
                    lambda: search_poi(category, location, filters, size),
                    "search_poi"
                )
                span.ok({"count": len(result)})
                self._cache_set(self._poi_cache, cache_key, result)
                return result
            except Exception as e:
                span.fail(str(e))
                return []

    def safe_check_table(self, poi_id: str, time_str: str,
                         people: int) -> TableResult:
        cache_key = (poi_id, time_str, people)
        if cache_key in self._table_cache:
            return self._table_cache[cache_key]

        with self.tracer.span("check_table", poi_id=poi_id,
                              time=time_str, people=people) as span:
            try:
                result = self._retry_call(
                    lambda: check_table(poi_id, time_str, people),
                    "check_table"
                )
                span.ok({"available": result.available,
                          "waiting": result.waiting_minutes})
                self._cache_set(self._table_cache, cache_key, result)
                return result
            except Exception as e:
                span.fail(str(e))
                return TableResult(available=False, waiting_minutes=999)

    def safe_check_queue(self, poi_id: str) -> dict:
        with self.tracer.span("check_queue", poi_id=poi_id) as span:
            try:
                result = self._retry_call(
                    lambda: check_queue(poi_id), "check_queue"
                )
                span.ok(result)
                return result
            except Exception as e:
                span.fail(str(e))
                return {"current_waiting": 0, "estimated_minutes": 0}

    def safe_get_route(self, origin: str, dest: str,
                       mode: TransportMode = TransportMode.TAXI) -> RouteResult:
        cache_key = (origin, dest, mode.value)
        if cache_key in self._route_cache:
            return self._route_cache[cache_key]

        with self.tracer.span("get_route", origin=origin,
                              dest=dest, mode=mode.value) as span:
            try:
                result = self._retry_call(
                    lambda: get_route(origin, dest, mode), "get_route"
                )
                span.ok({"duration_min": result.duration_min,
                          "distance_km": result.distance_km})
                self._cache_set(self._route_cache, cache_key, result)
                return result
            except Exception as e:
                span.fail(str(e))
                return RouteResult(duration_min=60, distance_km=20,
                                   mode=mode.value)

    def safe_get_weather(self, location: str,
                         time_str: str) -> WeatherResult:
        with self.tracer.span("get_weather", location=location,
                              time=time_str) as span:
            try:
                result = self._retry_call(
                    lambda: get_weather(location, time_str), "get_weather"
                )
                span.ok({"condition": result.condition})
                return result
            except Exception as e:
                span.fail(str(e))
                return WeatherResult(condition="未知", temp=20,
                                     suitable_outdoor=True)

    def safe_get_poi_detail(self, poi_id: str) -> Optional[POI]:
        with self.tracer.span("get_poi_detail", poi_id=poi_id) as span:
            try:
                result = self._retry_call(
                    lambda: get_poi_detail(poi_id), "get_poi_detail"
                )
                span.ok({"name": result.name})
                return result
            except Exception as e:
                span.fail(str(e))
                return None

    # ── 批量操作 ──────────────────────────────────────

    def parallel_retrieve(self, category: str, location: str,
                          filters: dict | None = None,
                          size: int = 5) -> list[EnrichedPOI]:
        pois = self.safe_search_poi(category, location, filters, size)
        enriched: list[EnrichedPOI] = []
        for p in pois:
            ep = EnrichedPOI(poi=p)
            if p.category == "餐厅":
                table = self.safe_check_table(p.id, "12:00", 2)
                ep.table_available = table.available
                ep.waiting_minutes = table.waiting_minutes
                ep.queue_length = 0
            enriched.append(ep)
        return enriched

    def fetch_routes_between(self, pois_a: list[POI], pois_b: list[POI],
                             mode: TransportMode = TransportMode.TAXI
                             ) -> dict[tuple[str, str], RouteResult]:
        routes: dict[tuple[str, str], RouteResult] = {}
        for a in pois_a:
            for b in pois_b:
                r = self.safe_get_route(a.location, b.location, mode)
                routes[(a.id, b.id)] = r
        return routes

    # ── LLM 安全调用 ──────────────────────────────────

    def safe_llm_chat(self, system: str, user: str,
                      task_name: str = "llm_call",
                      temperature: float = 0.3) -> str:
        with self.tracer.span(task_name) as span:
            try:
                result = self._retry_call(
                    lambda: self.llm.chat(system, user, temperature),
                    task_name
                )
                span.ok({"len": len(result)})
                return result
            except Exception as e:
                span.fail(str(e))
                return ""

    # ── 内建重试 ──────────────────────────────────────

    def _retry_call(self, fn, name: str):
        last_err = None
        for attempt in range(MAX_RETRIES):
            try:
                return fn()
            except Exception as e:
                last_err = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF[attempt])
        raise last_err  # type: ignore[misc]

    # ── 缓存管理 ──────────────────────────────────────

    def _cache_set(self, store: dict, key, value):
        if len(store) >= MAX_CACHE_SIZE:
            # 简单 FIFO：删第一个
            first = next(iter(store))
            del store[first]
        store[key] = value

    def clear_caches(self):
        self._route_cache.clear()
        self._poi_cache.clear()
        self._table_cache.clear()
        self._call_counts.clear()

    # ── 统计 ──────────────────────────────────────────

    @property
    def stats(self) -> dict:
        return {
            "route_cache_size": len(self._route_cache),
            "poi_cache_size": len(self._poi_cache),
            "table_cache_size": len(self._table_cache),
            "trace_summary": self.tracer.summary(),
        }


def _make_cache_key(*args: str) -> str:
    return "|".join(str(a) for a in args)
