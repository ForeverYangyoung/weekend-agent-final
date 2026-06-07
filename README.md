# Weekend Agent

美团 AI Hackathon · 赛题 06：**本地探索 — 周末闲时活动规划 Agent**

一句话描述周末出行 → Agent 完成 **画像 → 检索 → 规划 → 校验 → 预检 → HIL 确认 → 下单 → 行程卡** 闭环。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .

cd frontend
npm install
npm run build
cd ..

python app.py
# 浏览器 http://127.0.0.1:8000
```

开发模式：`python -m backend` + `cd frontend && npm run dev` → http://localhost:3000

测试：`python -m pytest tests/ -q`（当前 **73** 项）

亮点场景一键回归：`python scripts/demo_highlights.py`

## 演示场景（答辩推荐）

下面每条都能在 UI 或 CLI 演，且有用例兜底（见 `scripts/demo_highlights.py`）。

### 核心闭环（必演）

| 场景 | 输入 / 操作 | 看点（对应能力） |
|------|-------------|------------------|
| **朋友聚餐** | 「下午和 3 个朋友出去，4 人，想吃重口味」 | 跨端**禁辣档案 Mock**；显式重口味覆盖档案；**不选儿童乐园** |
| **4 人满座自愈** | 朋友场景默认规划 → 等预检 | `check_table_availability` 409 → **Compensator** 换店，SSE Trace 可见 Recovery |
| **家庭点名** | 「早上出游，中午 12 点川一哥火锅，孩子 5 岁」 | **preferred_venues** + **meal_time** 锚点；点名店优先于高分火锅 |
| **Top-2 方案** | 任意场景首次规划 | 左右两卡 **玩→吃** 组合不同，带价格/距离/matchReason |

```powershell
python -m backend.demo --scene friends
python -m backend.demo --scene family
python -m backend.demo --scene family --history   # 注入历史画像 Mock（Zero-Skill 切口）
```

### 加分项（建议挑 2～3 条深演）

| 场景 | 输入 / 操作 | 看点 |
|------|-------------|------|
| **午市满座 · 两卡同步** | 家庭 + 川一哥 → 午市预检 FAIL | 主备方案**同时**换店，备选卡不残留已满座店名 |
| **中途变卦** | 偏好面板改「日料 + 5km」→ replan | 清旧点名店；**严格 5km**；范围内无日料则诚实妥协提示 |
| **偏好矛盾** | 家庭低卡档案 + 面板加「火锅」 | `issueKind=needs_preference_fix` 黄条，**不静默换店** |
| **微调换店** | 方案卡「微调」多次换餐厅 | **品牌级排除**（Wagas 全分店）、总价重算、两卡重新差异化 |
| **顺路加餐** | 勾选「顺畅离园」→ 确认下单 | 仅 confirm 落单；`order_addon` **送到玩阶段出口** |
| **并行预检** | 看 SSE Trace | 多阶段读工具 **≤3s 并行**；失败分 NO_SEAT / NO_TICKET / CONFLICT |
| **有状态 Mock** | 川一哥午市再订 | 满座后 POI 进 anomaly、constraint 更新（语义目录 + Stateful backend） |
| **幂等确认** | 同 session 重复 confirm | `idempotency_key` 返回原单 |

### UI 操作速记

1. **朋友**：选场景 → 输入重口味 → 看 Trace 预检/Recovery → 对比两卡 → 确认下单  
2. **家庭川一哥**：输入点名 + 12 点 → 若黄条满座 → 两卡应同步换海底捞等 → 选备选确认  
3. **变卦**：规划后改偏好（日料·5km / 轻食）→ replan；不满意用「微调」换店  
4. **附加**：家庭方案勾选智能附加 → 「就选这个，帮我下单」

## 文档

| 文件 | 说明 |
|------|------|
| [`设计文档.md`](设计文档.md) | **赛题交付**（≤2 页）：Planning、工具链、异常处理、演示 |
| [`docs/mock-api.md`](docs/mock-api.md) | Mock 美团 HTTP 端点 |

## 项目结构

```
backend/     LangGraph + FastAPI + SSE + Mock 美团 + HIL
frontend/    React 答辩 UI（方案卡、Trace、偏好面板）
tests/       API 与场景回归（pytest）
```

## API

| 端点 | 说明 |
|------|------|
| `POST /v1/agent/stream` | 规划 + 预检，SSE 推送 Trace |
| `POST /v1/agent/replan` | HIL 改偏好后重规划 |
| `POST /v1/plan/revise` | 微调（换店/换活动） |
| `POST /v1/agent/confirm` | 确认下单 |
