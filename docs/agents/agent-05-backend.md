# Agent 工作包 05 · 后端平台官（Backend & Data Officer）

- **Wave**：W2 开工（与考古官并行），横跨到 W3（worker 装配要等智能体/沙箱接口就绪）
- **负责栈**：`docs/tasks/05-后端API与数据层.md`（T-BE-01…10），产出物在 `apps/api/`
- **你的使命**：控制面全套——数据模型、REST 契约冻结（前端与 CLI 靠你）、认证配额、Celery worker、SSE 事件、胶囊存储、管理端。

## 投喂清单
1. 本文件
2. `docs/tasks/00-总览与派发指南.md`（§1 认证/事件/存储决策、§7 环境变量）
3. `docs/tasks/05-后端API与数据层.md`（工单正文）
4. `schemas/` 全部（只读；你的响应模型必须与之零漂移）
5. W3 阶段追加：`agents/.../ports.py` + `local_pipeline.assemble_pipeline`（沙箱官交付）

## 执行顺序与要点
| 序 | 工单 | 额外注意 |
|---|---|---|
| 1 | T-BE-01 | app 工厂 + readyz 依赖检查；request_id 贯穿到 worker 日志 |
| 2 | T-BE-02 | 迁移必须 up/down/up 三连自证；job_events JSONB 入库前 schema 校验 |
| 3 | T-BE-03 | **对外冻结点**：路由表逐条对照工单；`make openapi` 进 CI；此后改接口=契约变更申请 |
| 4 | T-BE-04 ∥ 08 | 认证与配额并行；argon2、refresh 旋转重用检测、Redis 令牌桶都按工单验收 |
| 5 | T-BE-06 → 09 → 10 | SSE 历史+增量缝合是前端体验关键；evidence 端点喂前端 T-FE-07 |
| 6 | T-BE-05（W3 才收尾） | worker 内 `assemble_pipeline` + EventPort 双写（DB+Redis）；取消/清扫测试 |
| 7 | T-BE-07 | presigned 分发；跨用户 404 不 403 |

## 接口承诺
- `schemas/openapi/openapi.json`：前端官与 CLI 生成码唯一来源；每次合入前 `git diff --exit-code` 自检。
- 事件序列化单函数复用（T-BE-06 的 `event_bus.py`），worker 与 SSE 两端不得各写一份。

## 完成定义
- [ ] 10 条工单验收输出齐；`uv run pytest tests/integration/api -q`（含 requires_docker）全绿
- [ ] 一次真 job（fake LLM + 真沙箱）经 API 提交→SSE 收全 16 类事件→下载胶囊
- [ ] 攻击面初检：未鉴权 401、越权 404、私网 URL 400（为生产化官 T-PRD-02 铺好测试床）

## 禁止
- 禁止路由内业务逻辑；禁止 API 进程执行用户代码或克隆仓库（一律 worker/沙箱）；禁止返回体内嵌密钥或仓库原文。
