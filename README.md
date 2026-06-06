# Weekend Agent

美团 AI Hackathon · 赛题 06：**本地探索 — 周末闲时活动规划 Agent**

一句话描述周末出行需求，Agent 完成「画像 → 检索 → 规划 → 校验 → 预检 → HIL 确认 → 下单 → 行程卡」闭环。

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
# 打开 http://127.0.0.1:8000
```

**开发模式**（前端热更新）：`python -m backend` + `cd frontend && npm run dev` → [http://localhost:3000](http://localhost:3000)

## 演示说明

**怎么理解实现与未来方向**：现场看 Trace / 左栏黄条 / 「档案」标签；书面看 [`设计文档.md`](设计文档.md) §5 和 [`docs/解释文档.md`](docs/解释文档.md)。


| 场景         | 操作         | 三线看点                                               |
| ---------- | ---------- | -------------------------------------------------- |
| **朋友（主推）** | 选朋友 → 规划 | ① Trace 痔疮恢复期禁辣 ② 黄条 Zero-Skill Mock ③ 满座 Recovery |
| **家庭** | 选家庭 → 可加火锅 | 控糖控卡档案 vs 火锅 HIL |


```powershell
python -m backend.demo --scene family
python -m backend.demo --scene friends
python -m backend.demo --scene family --fail 吃
```

## 文档


| 文件                                     | 用途                                   |
| -------------------------------------- | ------------------------------------ |
| `[设计文档.md](设计文档.md)`                   | **赛题交付**：Planning 策略、工具链路、异常处理（≤2 页） |
| [`docs/mock-api.md`](docs/mock-api.md) | Mock 美团 HTTP 端点 |
| [`docs/解释文档.md`](docs/解释文档.md) | 实现逻辑、演示叙事与 Zero-Skill 未来方向 |
| [`archive_out/`](archive_out/) | 开发期长文档留底 |


## 结构


| 路径          | 说明                            |
| ----------- | ----------------------------- |
| `backend/`  | LangGraph、FastAPI、SSE、Mock 美团 |
| `frontend/` | React 答辩 UI                   |
| `tests/`    | API 与场景回归                     |


## API


| 端点                       | 说明                            |
| ------------------------ | ----------------------------- |
| `POST /v1/agent/stream`  | 规划 + 预检（HIL 暂停）               |
| `POST /v1/agent/replan`  | 改偏好后重规划                       |
| `POST /v1/agent/confirm` | 确认后下单（含 `selected_addon_ids`） |


