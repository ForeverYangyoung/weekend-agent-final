"""一键回归「答辩加分项」演示场景。

用法：
    python scripts/demo_highlights.py          # 跑关联 pytest + 打印速览表
    python scripts/demo_highlights.py --live   # 额外跑 2 条 CLI 图（较慢）

每条亮点对应 tests/ 里已有用例，方便 README 写「输入 → 看点 → 怎么验」。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Highlight:
    tier: str  # core | bonus
    title: str
    input_or_action: str
    selling_point: str
    pytest_node: str
    cli_hint: str = ""


HIGHLIGHTS: list[Highlight] = [
    Highlight(
        "core",
        "朋友 · 重口味不误拦",
        "「4 个朋友，想吃重口味，帮我安排」",
        "跨端禁辣档案 Mock 注入后，显式重口味自动覆盖，不拦规划、不选儿童乐园",
        "tests/test_plan_issues.py::test_friends_explicit_heavy_does_not_block_or_pick_kids_play",
        "UI 选朋友场景 + 同上输入",
    ),
    Highlight(
        "core",
        "朋友 · 4 人满座自愈",
        "朋友场景默认规划 → DryRun 预检",
        "姜虎东 4 人桌满座 409 → Compensator 公式换店，Trace 可见 Recovery",
        "tests/test_scene_surgery.py::test_four_person_table_trap_replans_to_backup_restaurant",
        "python -m backend.demo --scene friends",
    ),
    Highlight(
        "core",
        "家庭 · 点名川一哥",
        "「早上出游，中午 12 点川一哥火锅」",
        "preferred_venues + meal_time 锚点排程，点名店优先于高分火锅",
        "tests/test_plan_issues.py::test_named_venue_chuanyige_wins_over_higher_scored_hotpot",
        "UI 家庭场景 + 同上输入",
    ),
    Highlight(
        "bonus",
        "午市满座 · 两卡同步",
        "川一哥 poi_003 午市 12:00 预检 FAIL",
        "主方案 + 备选方案同时换店，右卡不再残留已满座店名",
        "tests/test_failure_self_heal.py::test_no_seat_heals_plan_alternatives_not_only_primary",
        "家庭川一哥 → 选备选卡 → 确认（应与新预检一致）",
    ),
    Highlight(
        "bonus",
        "中途变卦 · 日料 5km",
        "HIL 面板：菜系=日料，距离=5km",
        "清 preferred_venues；严格 ≤5km，不静默出 6km 禾绿",
        "tests/test_plan_issues.py::test_hil_replan_japanese_5km_does_not_pick_6km_sushi",
        "规划后打开偏好面板改日料+5km → replan",
    ),
    Highlight(
        "bonus",
        "偏好矛盾 · 黄条不静默",
        "家庭档案低卡 + 用户加「川菜/火锅」",
        "issueKind=needs_preference_fix，删标签后 replan，不偷偷换店",
        "tests/test_plan_issues.py::test_sichuan_family_explains_distance_reason_or_match",
        "家庭 + 面板加火锅，观察黄条",
    ),
    Highlight(
        "bonus",
        "微调换店 · 品牌排除",
        "方案卡「微调」多次换餐厅",
        "同品牌全店拉黑（Wagas 各分店）、总价重算、两卡重新差异化",
        "tests/test_plan_revise.py::test_refresh_revised_plan_bundle_updates_price_and_alternatives",
        "家庭轻食 → 微调换吃 → 确认价格与店名一致",
    ),
    Highlight(
        "bonus",
        "顺路加餐 · 送到出口",
        "家庭方案勾选「顺畅离园」附加 → 确认下单",
        "HIL 仅 confirm 时落单；order_addon 绑定玩阶段出口 POI",
        "tests/test_scene_surgery.py::test_addon_delivery_links_to_play_exit_on_confirm",
        "家庭默认方案 → 勾选附加 → 就选这个下单",
    ),
    Highlight(
        "core",
        "Top-2 差异化",
        "朋友场景一次规划",
        "左右两卡玩/吃组合不同，带价格距离与 matchReason",
        "tests/test_scene_surgery.py::test_friends_top_k_plans_use_different_venues",
        "python -m backend.demo --scene friends（看备选行）",
    ),
    Highlight(
        "bonus",
        "并行预检 ≤3s",
        "DryRun 多阶段并行 check",
        "读工具并行预检，失败分类 NO_SEAT / NO_TICKET / CONFLICT",
        "tests/test_failure_self_heal.py::test_parallel_precheck_under_3s",
        "SSE Trace 里看 DryRun·预检 汇总",
    ),
    Highlight(
        "bonus",
        "语义 Mock · 有状态满座",
        "poi_003 午市订位",
        "Stateful mock：满座后 child_fatigue 升、POI 进 anomaly 拉黑",
        "tests/test_semantic_catalog.py::test_poi_003_lunch_dry_run_triggers_compensator_state",
        "",
    ),
    Highlight(
        "bonus",
        "确认幂等",
        "同一 session 重复 confirm",
        "idempotency_key 返回原单，不重复扣位",
        "tests/test_mock_http.py::test_idempotency_round_trip",
        "",
    ),
]


def _run_pytest(node: str) -> tuple[bool, str]:
    cmd = [sys.executable, "-m", "pytest", node, "-q", "--tb=no"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = proc.returncode == 0
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    summary = tail[-1] if tail else "no output"
    return ok, summary


def _run_live_demos() -> None:
    for scene in ("friends", "family"):
        print(f"\n── CLI · {scene} ──")
        subprocess.run(
            [sys.executable, "-m", "backend.demo", "--scene", scene],
            encoding="utf-8",
            errors="replace",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="答辩亮点场景回归")
    parser.add_argument("--live", action="store_true", help="额外跑 backend.demo（较慢）")
    args = parser.parse_args()

    passed = failed = 0
    print("Weekend Agent · 答辩亮点回归\n")
    for i, h in enumerate(HIGHLIGHTS, 1):
        ok, summary = _run_pytest(h.pytest_node)
        tag = "PASS" if ok else "FAIL"
        tier = "★" if h.tier == "bonus" else "●"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"{tier} [{tag}] {i:02d}. {h.title}")
        print(f"       输入：{h.input_or_action}")
        print(f"       看点：{h.selling_point}")
        if h.cli_hint:
            print(f"       演示：{h.cli_hint}")
        if not ok:
            print(f"       测试：{h.pytest_node} → {summary}")
        print()

    print(f"合计：{passed} passed, {failed} failed（共 {len(HIGHLIGHTS)} 条）")
    if args.live and failed == 0:
        _run_live_demos()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
