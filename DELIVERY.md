# ReviveOS 交付说明（DELIVERY）

> 本文件是「可直接投入生产环境」这一目标的收口证据表。凡标 **已验证** 的项，均在本机
> 实测通过；凡标 **待沙箱外验证** 的项，本机环境（DSH 沙箱）在物理上无法执行，命令已给出，
> 必须在目标机/CI 上跑过一次才算完成。**不要把「待验证」当「已验证」。**

## 1. 交付物构成

| 形态 | 位置 | 状态 |
| --- | --- | --- |
| Web 控制台（Next.js 静态导出，Software ICU） | `apps/web` | 已验证（typecheck / lint / OpenAPI 类型生成） |
| 桌面软件（Electron 壳 + 托盘/设置/静态服务） | `apps/desktop` | 已验证（`tsc` 编译）；安装包待沙箱外打包 |
| CLI（analyze / resurrect / verify / replay / login / download / jobs） | `cli` | 已验证（`--help` 与命令注册） |
| 后端控制面（FastAPI） | `apps/api` | 已验证（371 项测试；72 个操作/58 条路径） |
| 核心引擎（考古、环境推断、沙箱、评分、胶囊） | `packages/core` | 已验证（单元/契约测试） |
| 智能体（LLM provider、prompt、supervisor 图） | `agents` | 已验证（含 prompt 黄金哈希） |
| 契约（4 个 JSON Schema + OpenAPI 快照） | `schemas` | 已验证（含漂移测试） |
| 生产镜像与编排 | `Dockerfile.*`、`infra/compose` | 待沙箱外验证（CI 会构建+冒烟） |
| 迁移 | `apps/api/alembic` | 已验证（链 0001→0004）；执行待真实 PG |
| 可观测性 | `GET /metrics`、`infra/observability` | 已验证（Prometheus 文本） |

规模：384 个受版本控制文件；Python ≈21.0k 行、TS/TSX ≈7.7k 行。

## 2. 生产架构（已实现的部分）

```
Browser / Desktop / CLI
        │  HTTPS (Caddy: /api/* → API，其余 → 静态控制台)
        ▼
   API (FastAPI)  ── request-scoped SQLAlchemy UoW（成功 commit / 失败 rollback）
        │                 ├─ 认证：JWT access+refresh（旋转+重用检测）
        │                 ├─ API Key（哈希校验，按用户查询/撤销）
        │                 ├─ 配额/维护开关（runtime_settings 表，跨副本共享）
        │                 ├─ 就绪探针：postgres / redis / object_storage
        │                 └─ 指标：/metrics（内部，不进 OpenAPI）
        ├── PostgreSQL（projects/jobs/events/evidence/artifacts/capsules/audit…）
        ├── Redis（事件总线 + 登录限流）
        ├── S3/MinIO（.revive 胶囊正文，SigV4，trust_env=False）
        └── Celery worker（唯一执行用户代码的进程；Docker 沙箱）
```

生产启动是 **fail closed** 的：`REVIVE_ENV=prod` 时，缺少 `DATABASE_URL`、`REDIS_URL`、
`S3_*`、durable 限流/事件/存储适配器，任一不满足即 `ConfigurationError`，绝不静默退回内存。

## 3. 已验证证据（本机实测）

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 全量测试 | `.venv\Scripts\python.exe -m pytest -q` | **371 passed, 20 skipped**（skip 全部为 `requires_docker`） |
| Lint | `ruff check <PY_PATHS>` | All checks passed |
| 格式 | `ruff format --check <PY_PATHS>` | 200 files already formatted |
| 类型 | `mypy packages/core/src cli/src agents/src apps/api/src` | Success: 113 source files |
| Schema 契约 | `python tools/check_contracts.py` | OK (5 schemas, 10 fixtures) |
| 红线规则 | `python tools/check_global_rules.py .` | OK（无密钥、修复上限完好） |
| OpenAPI 漂移 | `pytest tests/unit/api/test_openapi_contract.py` | 快照 == 运行时（58 路径 / 72 操作） |
| 镜像 digest 占位符 | `python tools/image_digests.py` | 通过（无全零占位） |
| 生产栈构造 | `pytest tests/unit/api/test_app_lifespan.py ...` | UoW/engine/事件/限流/存储装配正确 |
| 对象存储往返 | `pytest tests/unit/api/test_capsule_storage_http.py` | 真实 HTTP PUT/GET/DELETE + SigV4 头 |
| 就绪语义 | `pytest tests/unit/api/test_readiness_probes.py` | 200/403 就绪、503/不可达不就绪 |
| 迁移链 | `python -m alembic -c apps/api/alembic.ini history` | `<base>→0001→0002→0003→0004 (head)` |
| 前端类型 | `pnpm --filter web typecheck` | 通过 |
| 前端 lint | `pnpm --filter web lint` | No ESLint warnings or errors |
| 桌面壳编译 | `pnpm --filter desktop build` | 通过 |
| pre-commit | `python -m pre_commit run --all-files` | 6/6 hooks Passed |

## 4. 待沙箱外验证（必须跑完才算生产验收）

本沙箱的两个硬限制（已实测、非配置问题）：

1. **Docker daemon 不可达**：`docker info` 报命名管道缺失 → 一切 `requires_docker` 用例 skip。
2. **无法创建子进程（`spawn EPERM`）**：`next build` / `next dev` / Electron 打包都要 fork；
   Next 14.2.35 内置 jest-worker 只有 `ChildProcessWorker`，`experimental.workerThreads` 无效。

请在普通终端 / CI 执行：

```powershell
# 1) 起依赖
docker compose -f infra/compose/dev.docker-compose.yml up -d
docker compose -f infra/compose/dev.docker-compose.yml run --rm minio-init

# 2) 迁移
$env:DATABASE_URL="postgresql+asyncpg://revive:revive@localhost:5432/revive"
.venv\Scripts\python.exe -m alembic -c apps/api/alembic.ini upgrade head

# 3) 跨进程持久化验收（最关键：证明 API 不是内存栈）
.venv\Scripts\python.exe -m pytest -q tests\integration\api\test_api_persistence.py

# 4) 其余 Docker 门禁
$env:REVIVE_DOCKER_AVAILABLE="1"
.venv\Scripts\python.exe -m pytest -q tests -m requires_docker

# 5) Web 生产构建 + 桌面安装包
pnpm --filter web build
pnpm --filter desktop dist

# 6) 生产拓扑静态校验
$env:API_DIGEST=('a'*64); $env:WORKER_DIGEST=('b'*64); $env:WEB_DIGEST=('c'*64)
$env:POSTGRES_DIGEST=('d'*64); $env:REDIS_DIGEST=('e'*64); $env:CADDY_DIGEST=('f'*64)
$env:REVIVE_API_IMAGE='ghcr.io/you/reviveos-api'; $env:REVIVE_WORKER_IMAGE='ghcr.io/you/reviveos-worker'
$env:REVIVE_WEB_IMAGE='ghcr.io/you/reviveos-web'; $env:REVIVE_DOMAIN='localhost'
$env:POSTGRES_PASSWORD=('a'*64); $env:REDIS_PASSWORD=('b'*64)
$env:REVIVE_WORKER_TOKEN='c'; $env:DOCKER_GID='999'
docker compose -f infra/compose/prod.docker-compose.yml config --no-env-resolution --quiet
```

CI（`.github/workflows/ci.yml`）已编排：质量门禁 → Web 构建 → 三镜像构建 + API `/healthz` 与
Web 首页冒烟。tag 触发的 `release.yml` 负责 GHCR 发布、Trivy 门禁、CycloneDX SBOM 与 digest 记录。

## 5. 上线前仍需人工完成

1. 第一次 tag 发布，确认 `release.yml` 全绿并记录三镜像 digest。
2. 解析并审核 Postgres/Redis/Caddy 基础镜像 digest，填入 `infra/envs/compose.env.template`。
3. 用 secret manager 生成 `infra/envs/revive.prod.env`（S3/LLM/JWT/worker token/DB 口令）。
4. 配置域名与 TLS；仅暴露 80/443。
5. 演练 `infra/backup/` 的备份与**恢复**（需要离机保留）。
6. worker 挂载 Docker socket 等价于宿主 root：必须专用隔离主机。
7. 若需“构造即复现”的镜像，把 Dockerfile 切到 `uv sync --frozen` 并 digest 锁定基础镜像
   （当前从 `pyproject.toml` 安装、基础镜像为 tag）。

## 6. 已知限制与取舍（诚实清单）

- Web 控制台是**纯客户端** SPA：所有数字来自 API，前端不重算评分；缺失字段显示“未知/待测”，
  不填充示例数据。
- 内存后端（`MemoryStore` / `MemoryCapsuleStorage` / `MemoryLoginThrottle`）只用于 dev 与测试；
  生产路径有静态护栏测试（`test_no_memory_fallback.py`）防止回流。
- 登录限流用 Redis 计数，语义是“窗口内失败次数 + 锁定 TTL”，非精确滑动窗口。
- 取消是**协作式**：API 写 `cancel_requested`，worker 在阶段边界检查；不保证立即杀死进程。
- `revivebench` 的数字必须来自真实运行；未跑过的格子写“待测”，仓库内无编造数据。
