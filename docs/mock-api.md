# Mock 美团 API

Weekend Agent 演示用的「假美团」HTTP 服务。Agent 通过 `httpx` 调用本服务，
逻辑等价于真调美团 API；切换真服务只需改一个环境变量。

## 文件清单

```
backend/
├── mock_meituan/
│   ├── app.py        独立 FastAPI 入口（uvicorn 直接起）
│   ├── routes.py     全部 HTTP 路由（POI 搜索 / 可用性预检 / 下单 / 取消）
│   ├── backend.py    内存订单簿 + 幂等表 + 注入开关
│   └── catalog.py    POI 数据（按 scene + stage 索引）
└── tools/
    ├── http_client.py  Agent 侧 sync 客户端（asyncio.run + httpx）
    └── registry.py     tool_name → HTTP path 的翻译层
```

## 端点速查

| 方法 | 路径 | 用途 |
|---|---|---|
| GET  | `/poi/search?scene=&stage=&limit=` | 取候选 POI（Researcher 调） |
| POST | `/availability/activity` | 查活动票（DryRun 调） |
| POST | `/availability/table` | 查餐厅桌位 |
| POST | `/availability/addon` | 查加餐库存 |
| POST | `/order/buy_ticket` | 真购票 |
| POST | `/order/book_table` | 真订桌 |
| POST | `/order/order_addon` | 真下加餐 |
| POST | `/order/cancel` | 取消订单（Compensator 调） |
| GET  | `/health` | 健康检查 + 订单计数 |
| POST | `/admin/reset` | 清空订单簿（demo 间复位） |

## 三种部署形态

### 1. ASGI 内联（默认 · 零配置）

Agent 用 `httpx.ASGITransport(app=mock_app)` 在进程内直接打到 FastAPI 路由——
**不开端口**，但 HTTP 协议、状态码、JSON 体全部走完整流程：

```bash
python -m backend.demo --scene family
# 顶部会显示：Mock 美团：ASGI 内联（默认）
```

### 2. 主进程附挂

直接 `python -m backend`，mock 路由会被挂在 `/mock-meituan/*`：

```bash
python -m backend
# 评委可 curl 验证：
curl 'http://127.0.0.1:8000/mock-meituan/health'
curl 'http://127.0.0.1:8000/mock-meituan/poi/search?scene=family&stage=%E5%90%83'
```

### 3. 独立 mock server（最接近生产）

把 mock 拉成独立进程，Agent 通过环境变量切到真 TCP：

```bash
# 终端 A：拉假美团（:8001）
python -m uvicorn backend.mock_meituan.app:mock_app --port 8001

# 终端 B：跑 Agent，并指向终端 A
$env:MOCK_MEITUAN_BASE_URL = "http://127.0.0.1:8001"   # PowerShell
# export MOCK_MEITUAN_BASE_URL=http://127.0.0.1:8001   # bash
python -m backend.demo --scene friends
```

`MOCK_MEITUAN_BASE_URL` 留空 / `internal` / `memory` 都视为内联模式。

> Windows 注意：默认 `trust_env=False`，避免系统注册表里的代理把 `127.0.0.1`
> 也劫持成 502。如果要让 httpx 读系统代理（切真公网 API 才需要），设
> `MOCK_MEITUAN_TRUST_ENV=1`。

## 失败注入

写类路由的请求体都接受一个 `force_fail` 字段：

| 值 | 行为 |
|---|---|
| `table_full` | `/order/book_table` 返 409「餐厅已满座」 |
| `sold_out` | `/order/buy_ticket` 返 410「已售罄」 |
| `out_of_stock` | `/order/order_addon` 返 409「库存不足」 |

Agent 侧无需手写，CLI 直接给：

```bash
python -m backend.demo --scene family --fail 吃
```

`tools/registry.py` 会自动把 `state["force_failure"]="吃"` 翻译成对 `book_table`
请求体的 `force_fail="table_full"`，mock 路由直接返 409，触发 Compensator
取消已成功的订单并重规划。

## 一句话现场演示脚本

```bash
# 1. 拉 mock server
python -m uvicorn backend.mock_meituan.app:mock_app --port 8001 &

# 2. 用 curl 证明它是真 HTTP 服务
curl 'http://127.0.0.1:8001/poi/search?scene=family&stage=%E5%90%83'

# 3. Agent 通过真 TCP 调它，跑完整链路
$env:MOCK_MEITUAN_BASE_URL = "http://127.0.0.1:8001"
python -m backend.demo --scene family --fail 吃

# 4. 再 curl 看订单簿：3 笔成功 + 2 笔被回滚
curl 'http://127.0.0.1:8001/health'
```
