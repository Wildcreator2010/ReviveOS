# 05 · 后端 API 与数据层（Python `apps/api`，FastAPI/PostgreSQL/Redis/Celery，前缀 T-BE）

> 后端只做控制面：编排、持久化、鉴权、事件、存储。一切用户代码执行发生在 worker 经 ExecutionPort 拉起的沙箱里。REST 前缀统一 `/api/v1`；所有响应模型即 OpenAPI 契约（前端/CLI 生成码的唯一来源）。

### T-BE-01 FastAPI 应用骨架
- 背景：控制面进程入口：app 工厂、配置注入、结构化日志、全局异常面、请求 ID。
- 涉及文件：`apps/api/src/revive_api/{main.py,deps.py,middleware.py}`、`tests/unit/api/test_app.py`。
- 输入/输出契约：`create_app(config: Config) -> FastAPI`；中间件：request_id 生成并回写 `X-Request-Id`、structlog 绑定（request_id/job_id/user_id）、CORS 白名单来自配置；`GET /healthz`（liveness）与 `GET /readyz`（检查 PG/Redis 连接，任一失败 503 且体给出组件名）；未处理异常统一 500 面 `{error:{code:"internal", request_id}}`，禁止泄漏堆栈。
- 验收：`uv run pytest tests/unit/api/test_app.py -q` 绿；`uv run uvicorn revive_api.main:app` 起服后 `curl -s localhost:8000/readyz` 在 dev compose 下返回 `{"status":"ok"}`；日志一行 JSON 且含 request_id。
- 禁止：路由文件里禁止出现业务逻辑（一律 service 层）；禁止全局单例 app 直连配置（工厂模式）。
- 依赖：T-INIT-04、T-CORE-01。

### T-BE-02 数据模型与迁移（13 张核心表）
- 背景：落全部持久化模型。表：`users, api_keys, projects, repositories, evidence_items, genomes, jobs, build_attempts, patches, behavior_runs, fingerprints, capsules, llm_calls, job_events`（后加 `case_memory` pgvector 扩展表）。
- 涉及文件：`apps/api/src/revive_api/db/{models.py,session.py}`、`apps/api/src/revive_api/db/migrations/versions/0001_init.py`（Alembic）、`tests/unit/api/test_models.py`。
- 输入/输出契约：SQLAlchemy 2.x typed Declarative；主键统一 `id: str`（`rev_<entity>_<ulid>`）；外键关系按《方案 §18》树（Project→Repository/Job→…→Capsule）；`job_events.payload` 用 JSONB 且入库前过 schema 校验（应用层）；`case_memory.embedding vector(1536)` 与 HNSW 索引在 0002 迁移；时间全部 UTC timestamptz；软删除仅 `projects/capsules`（`deleted_at`）。
- 验收：`uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head` 三连在 dev compose 退出 0；`uv run pytest tests/unit/api/test_models.py -q` 绿（含关系级联删除断言）。
- 禁止：禁止在模型里写查询逻辑；禁止手改已合并迁移（新变更新文件）。
- 依赖：T-BE-01。

### T-BE-03 项目/任务 REST API 与 OpenAPI 快照
- 背景：对外接口冻结点——前端与 CLI 都从这份快照生成类型。路由：`POST /projects`（提交 repo_url）、`GET /projects/{id}`、`POST /projects/{id}/resurrect`（返回 job_id）、`GET /jobs/{id}`、`GET /jobs?project_id=`、`POST /jobs/{id}/cancel`、`GET /projects/{id}/genome|builds|patches|behavior|score`（读持久化产物）、`DELETE /projects/{id}`。
- 涉及文件：`apps/api/src/revive_api/routers/{projects.py,jobs.py}`、`apps/api/src/revive_api/services/{project_service.py,job_service.py}`、`schemas/openapi/openapi.json`（导出物）、`Makefile`（`make openapi`）、`tests/integration/api/test_projects.py`。
- 输入/输出契约：全部响应 model 用 pydantic（引用 T-CORE-01 域模型）；`POST /projects` 校验 URL 仅 github.com 白名单且去重（同 owner/repo+user 返回既有项目 409 带 `detail.existing_id`）；分页统一 `?limit<=100&cursor=`；错误体统一 `{error:{code,message,details?}}` 且 code 是稳定枚举（`repo_not_found/forbidden/quota_exceeded/…`）；`make openapi` = 启动 app 导出 `openapi.json` 并 `jsonschema` 自检 + git diff 检查（变更需在同一 PR 提交快照）。
- 验收：`uv run pytest tests/integration/api/test_projects.py -q` 绿（TestClient + db）；`make openapi && git diff --exit-code schemas/openapi` 在无接口改动时退出 0；人工检查：非白名单 URL 返回 400 `code="repo_url_not_allowed"`。
- 禁止：本工单不得实现真实执行（建 job 记录后置 `queued` 即返回，执行在 T-BE-05）。
- 依赖：T-BE-02。

### T-BE-04 认证与 API Key
- 背景：注册/登录/JWT 双 token/API Key（CLI、CI 用）/角色控制。
- 涉及文件：`apps/api/src/revive_api/{routers/auth.py,security.py,services/user_service.py}`、`tests/integration/api/test_auth.py`。
- 输入/输出契约：`POST /auth/register|login|refresh`、`POST /auth/api-keys`（返回明文一次，库存 `argon2` 哈希 + 前 8 位前缀用于展示）、`Authorization: Bearer` 与 `X-Revive-Key` 双通道；密码 argon2id；JWT HS256 + `REVIVE_JWT__SECRET`，access 15min/refresh 7d（refresh 旋转 + 重用检测：旧 refresh 再使用→吊销整个族）；`require_role("admin")` 依赖；登录限速见 T-BE-08。所有业务路由强制鉴权（除 health）。
- 验收：`uv run pytest tests/integration/api/test_auth.py -q` 绿（含：过期 access 401、refresh 重用吊销、API Key 认证访问 `/projects` 通过、密钥明文不出现在任何日志行断言）。
- 禁止：禁止自实现 JWT 库；禁止把 secret 写进 compose 明文（env 注入，dev 用占位并在启动时警告）。
- 依赖：T-BE-03。

### T-BE-05 Celery 任务管线（worker 即流水线宿主）
- 背景：`resurrect` job 的真实执行体：worker 内装配 LangGraph supervisor + 本机 Docker ExecutionPort + Redis EventPort；含取消、超时、孤儿沙箱清扫。
- 涉及文件：`apps/api/src/revive_api/tasks/{celery_app.py,pipeline.py,sweeper.py}`、`infra/compose` worker 服务定义、`tests/integration/api/test_pipeline.py`（`requires_docker`）。
- 输入/输出契约：`celery_app` 任务 `run_resurrection_job(job_id)`；worker 启动时 `acks_late=True, worker_max_tasks_per_child=10`，任务幂等（job 状态机 `queued→running→succeeded|failed|cancelled`，重复投递直接跳过）；supervisor 的 `EventPort` 实现在这里（写 `job_events` 表 + Redis publish 双路）；取消：`POST /jobs/{id}/cancel` → 置 `cancel_requested` + `celery revoke(terminate)` 兜底 + 每节点入口检查取消位；`sweeper`：beat 每 10min 按 label 清孤儿容器（`revive.job_id` 且对应 job 已终态）。
- 验收：`uv run pytest tests/integration/api/test_pipeline.py -q` 绿：fixture 项目走通 job 全生命周期（fake LLM provider），事件表与 Redis 频道都收到终态；取消一个正在 build 的 job → 10s 内沙箱销毁且状态 `cancelled`。
- 禁止：worker 禁止持有 LLM key 之外的额外云凭据；禁止在任务里 import `revive_api.routers`。
- 依赖：T-BE-03、T-AG-06、T-SB-02。

### T-BE-06 事件总线与 SSE 端点
- 背景：把流水线过程实时推给 CLI/Web：`GET /jobs/{id}/events/stream`（SSE），支持 `Last-Event-ID` 断线重放（先补历史再订阅）。
- 涉及文件：`apps/api/src/revive_api/routers/events.py`、`apps/api/src/revive_api/services/event_bus.py`、`tests/integration/api/test_events_sse.py`。
- 输入/输出契约：SSE `data:` 行即 `job-event.schema.json` 实例；历史从 `job_events` 表按 (id 游标) 回放，增量从 Redis Pub/Sub 频道 `revive:events:{job_id}`；心跳注释帧 15s；终态后服务端关闭流；事件写入方（T-BE-05）与读取方共用 `event_bus.py` 序列化函数（禁止两处手拼 JSON）。
- 验收：`uv run pytest tests/integration/api/test_events_sse.py -q` 绿（httpx-sse：完整流事件序列 == DB 序列；模拟断线带 Last-Event-ID 重连无缺失无重复——以 event.id 单调断言）。
- 禁止：禁止轮询 DB 实现流；事件负载禁止 >64KB（日志截断引用 artifacts）。
- 依赖：T-BE-05。

### T-BE-07 胶囊存储与下载 API
- 背景：worker 产出的 `.revive` 上传 MinIO；提供列表/详情/presigned 下载/删除（软删+保留期）。
- 涉及文件：`apps/api/src/revive_api/{routers/capsules.py,services/storage.py}`、`tests/integration/api/test_capsules.py`。
- 输入/输出契约：`POST /jobs/{id}/capsule`（worker 内部端点，凭 worker 内部 token）、`GET /capsules/{id}`（manifest 摘要）、`GET /capsules/{id}/download`（302 presigned，60s TTL）、`GET /projects/{id}/capsules`、`DELETE /capsules/{id}`（软删，30 天后 beat 真删）；对象 key 固定 `capsules/{user_id}/{capsule_id}.revive`；上传即算 sha256 与 manifest 内 digest 比对，不一致拒收 422。
- 验收：`uv run pytest tests/integration/api/test_capsules.py -q` 绿；跨用户访问返回 404（非 403，防枚举）；presigned URL 直接 curl 可下载且 sha256 匹配。
- 禁止：禁止把 MinIO 桶配置成 public-read；禁止 API 进程流式中转大文件（一律 presigned）。
- 依赖：T-BE-04、T-CAP-02。

### T-BE-08 配额、限流与滥用防护
- 背景：生产系统要挡住"把服务器当免费算力"的场景：并发 job 数、日提交数、登录爆破、repo 体积上限。
- 涉及文件：`apps/api/src/revive_api/services/{quota.py,rate_limit.py}`、`tests/integration/api/test_quota.py`。
- 输入/输出契约：配置化默认值 `REVIVE_QUOTA__MAX_CONCURRENT_JOBS=2, MAX_JOBS_PER_DAY=20, MAX_REPO_MB=200`；超限 429/403 带 `Retry-After`；限流键：认证用户维度（匿名只有登录/注册端点）；clone 前用 GitHub API 查仓库体积，clone 时 `--depth` 不适用（历史是证据）但按对象计数超限中止并清缓存；admin 可调（存 DB 覆盖配置）。
- 验收：`uv run pytest tests/integration/api/test_quota.py -q` 绿（并发第 3 个 job 被拒；日配额耗尽后 429；登录 5 连败锁 15min）。
- 禁止：禁止仅内存限流（多 worker 失真——必须 Redis 令牌桶）。
- 依赖：T-BE-04。

### T-BE-09 考古产物持久化与证据检索 API
- 背景：genome/evidence/timeline 落库（含 pgvector 摘录向量），`GET /projects/{id}/evidence?source_kind=` 过滤查询；为前端证据视图提供数据。
- 涉及文件：`apps/api/src/revive_api/{routers/evidence.py,services/evidence_service.py}`、`tests/integration/api/test_evidence.py`。
- 输入/输出契约：入库时机在 T-BE-05 pipeline 的 analyze 节点后；`evidence_items` 行含 `project_id, source_kind, reference, facts(jsonb), excerpt_hash`；摘录 embedding 走 `REVIVE_LLM__EMBED_*`（未配置则跳过向量列，功能降级与 T-AG-08 一致）；查询端点返回按 confidence 降序 + 分页。
- 验收：`uv run pytest tests/integration/api/test_evidence.py -q` 绿；对 fixture 项目：`curl .../evidence?source_kind=manifest_file` 只返回清单类证据。
- 禁止：本端点禁止暴露仓库源码原文（只回 reference 与 facts）。
- 依赖：T-BE-03、T-CORE-04、T-CORE-06。

### T-BE-10 管理端点与成本汇总
- 背景：运营视角：用户/任务全局列表、kill switch（暂停接单）、LLM 成本日报聚合。
- 涉及文件：`apps/api/src/revive_api/routers/admin.py`、`tests/integration/api/test_admin.py`。
- 输入/输出契约：仅 `require_role("admin")`：`GET /admin/jobs?status=`、`POST /admin/jobs/{id}/kill`（复用 cancel + 标记 admin_killed）、`GET /admin/costs/daily`（聚合 `llm_calls.usage`）、`POST /admin/maintenance {accepting_jobs: bool}`（关闸后新 `POST /resurrect` 返回 503 `code="maintenance"`）；状态变更全部写审计行（`admin_audit` 表，含 who/when/what/before/after）。
- 验收：`uv run pytest tests/integration/api/test_admin.py -q` 绿（普通用户 403、审计行存在）。
- 禁止：admin 端点禁止返回用户密码哈希/API Key 任何片段。
- 依赖：T-BE-04、T-BE-05。
