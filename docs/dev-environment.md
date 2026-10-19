# ReviveOS 开发环境（Windows 本机实测版）

> 适用对象：在本仓库工作的所有人 / LLM Agent。
> 本文只写**本机实测过的事实**。凡是「理论上」「一般情况」的内容，均已标注。
> 相关脚本：[`tools/dev_env.ps1`](../tools/dev_env.ps1)（**已存在，请勿覆盖**）。

---

## 0. 一分钟上手（结论先行）

```powershell
# 1) 进入仓库
cd C:\Users\<you>\Desktop\WildProject\ReviveOS

# 2) 注入工具链（git / uv / pnpm 路径 + uv 缓存目录）
. .\tools\dev_env.ps1

# 3) 建/更新虚拟环境（首次或依赖变更后）
& "$env:USERPROFILE\.local\bin\uv.exe" sync --all-packages

# 4) 跑质量闸门（等价于 CI）
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe tools\check_contracts.py
.venv\Scripts\python.exe tools\check_global_rules.py .
```

> **本机没有安装 `make`**（`Get-Command make` 为空）。`Makefile` 是统一入口契约，
> 但在这台机器上请直接运行下面对应的命令，或先自行安装 GNU Make。
> 每个 `make` 目标对应的真实命令见 §6。

---

## 1. Python：.venv 是唯一解释器

| 项目 | 实测值 |
| --- | --- |
| 解释器 | `.venv\Scripts\python.exe` |
| 版本 | CPython **3.11.16**（`.python-version` 锁定 3.11） |
| 包管理 | `uv` workspace（根 `pyproject.toml` + `uv.lock`） |
| 子包 | `packages/core`、`cli`、`agents`、`apps/api` |

**必须用 venv 里的解释器**，不要用系统 `python`：

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy packages/core/src cli/src agents/src apps/api/src
.venv\Scripts\python.exe -m pre_commit run --all-files
```

`Makefile` 已用 `PYTHON ?= $(if $(wildcard .venv/Scripts/python.exe),...)` 自动选择
Windows/POSIX 解释器，并把 `.venv/Scripts` 前置到 `PATH`，使 pre-commit 的
`language: system` hook 与 `$(PYTHON)` 用同一个解释器。

### 1.1 pytest 的缓存开关

根 `pyproject.toml` 里设置了 `addopts = "-p no:cacheprovider"`：
DSH 沙箱拒绝 pytest 缓存使用的「临时目录原子改名」，否则每次运行都会刷一屏
`WinError 5` 警告。沙箱遗留的 `pytest-cache-files-*` 目录 ACL 不可读（连
`Remove-Item` 都被拒绝），因此它们已被 `.gitignore` 与 ruff 的
`extend-exclude` 排除——ruff 一旦走进这些目录会直接 panic。

---

## 2. uv：不在 PATH，需要显式调用

| 项目 | 实测值 |
| --- | --- |
| 可执行文件 | `C:\Users\<you>\.local\bin\uv.exe`（本机为 `C:\Users\Wildcreator\.local\bin\uv.exe`） |
| 是否在 PATH | **否** |
| 已验证命令 | `uv sync --all-packages` 退出码 0 |

在沙箱内使用 uv 前必须设置三个变量，否则 uv 会尝试写用户级缓存（可能被拒）或走
硬链接（跨盘/沙箱场景容易失败）：

```powershell
$env:UV_CACHE_DIR        = "$PWD\.uv-cache"
$env:UV_PYTHON_INSTALL_DIR = "$PWD\.uv-python"
$env:UV_LINK_MODE        = "copy"

& "$env:USERPROFILE\.local\bin\uv.exe" sync --all-packages
```

`.uv-cache\`、`.uv-python\` 已在 `.gitignore` 中；`uv.toml` 里固定
`link-mode = "copy"`。**不要**把各包 `pyproject.toml` 的依赖改回空列表，也不要手改
`uv.lock`（`.venv` 与 lock 由 uv 维护）。

`Makefile` 的 `sync` 目标默认 `UV ?= uv`；本机请这样跑：

```powershell
make sync UV="$env:USERPROFILE\.local\bin\uv.exe"
```

---

## 3. git：便携版 + `REVIVE_GIT_BIN`

| 项目 | 实测值 |
| --- | --- |
| 系统 git | **未安装**（`Get-Command git` 为空） |
| 便携版 MinGit | `.tools\git\cmd\git.exe`，版本 **2.47.1.windows.1** |
| 环境变量 | `REVIVE_GIT_BIN` 指定 git 可执行文件 |

`tools/dev_env.ps1` 会在检测到便携版后自动设置 `REVIVE_GIT_BIN`。

**代码侧契约**：`revive_core.gitutil` 是唯一解析 git 的入口。

- `GIT_BIN_ENV = "REVIVE_GIT_BIN"`；
- 解析顺序：`REVIVE_GIT_BIN` → `PATH` → 仓库旁 `.tools/git/...`；
- 全部找不到时抛 `GitUnavailableError`，带可操作提示（提示设置 `REVIVE_GIT_BIN` 或
  安装便携版），**不会**让裸 `FileNotFoundError` 冒出来；
- 调用统一走 `run_git(...)`（`shell=False`、UTF-8、超时、可 `check`）。

手工验证：

```powershell
$env:REVIVE_GIT_BIN = "$PWD\.tools\git\cmd\git.exe"
.venv\Scripts\python.exe -c "from revive_core.gitutil import find_git; print(find_git())"
```

> 已知缺口（截至本机 2026-10-06）：`packages/core/src/revive_core/archaeology/fetcher.py`
> 仍直接调用裸 `git`。`gitutil` 已经提供正确入口，等 core 栈重写 fetcher 时接上即可。

---

## 4. 网络：哪些走得通，哪些被沙箱拦

| 目标 | 结果 |
| --- | --- |
| Python `urllib` 的 TLS | **可出网**（下载/抓取请用它） |
| `uv` 的 TLS | **可出网** |
| `registry.npmmirror.com` | **可达**（node fetch 实测 200） |
| `registry.npmjs.org` | **不可达** |
| `curl` / `Invoke-WebRequest` / `certutil` | **被沙箱拦截** |
| `node` 的 fetch 到 npmjs | **被沙箱拦截** |

### 4.1 npm / pnpm 镜像

仓库根已有 `.npmrc`：

```ini
registry=https://registry.npmmirror.com
```

**不要删除它。** 没有它，任何 npm 系安装都会卡在不可达的 npmjs。

### 4.2 pnpm 不在 PATH

协调者用 npm 把 pnpm 装到工作区内，调用方式是**用 node 跑 pnpm.cjs**：

```powershell
node .tools\pnpm\node_modules\pnpm\bin\pnpm.cjs install
```

`tools/dev_env.ps1` 会注册一个 `pnpm` 函数指向同一路径。
`Makefile` 变量：

```makefile
PNPM ?= node .tools/pnpm/node_modules/pnpm/bin/pnpm.cjs
```

因此 `make web-install`（= `$(PNPM) install`）无需全局 pnpm。

### 4.3 OpenAI 思考强度

OpenAI 与 OpenAI-compatible 适配器支持调用级 `reasoning_effort`，取值为 `low`、`medium` 或 `high`。默认值可以通过 `REVIVE_LLM__REASONING_EFFORT` 设置，非法值会在 Provider 工厂层拒绝。Anthropic 和 fake Provider 接受同一协议参数，但不会把 OpenAI 专用字段发送到 Anthropic。

```powershell
$env:REVIVE_LLM__PROVIDER = "openai"
$env:REVIVE_LLM__MODEL = "gpt-6.1-sol"
$env:REVIVE_LLM__API_KEY = "<your-key>"
$env:REVIVE_LLM__REASONING_EFFORT = "high"
```

代码入口为 `agents/src/revive_agents/llm/openai_adapter.py`，请求体透传 OpenAI Chat Completions 的 `reasoning_effort` 字段；测试使用 `httpx.MockTransport`，不会访问真实 API。

---

## 5. Docker：CLI 在，daemon 连不上

| 项目 | 实测值 |
| --- | --- |
| `docker` CLI | `C:\Program Files\Docker\Docker\resources\bin\docker.exe` |
| daemon | **连不上**：DSH 沙箱禁止访问 Windows 命名管道 |
| 结论 | 所有需要 daemon 的命令（`up`/`exec`/`ps`/`pull`）在沙箱内必然失败 |

因此本仓库规定：

- 任何需要 Docker 的测试必须打 `@pytest.mark.requires_docker`；
- `tests/conftest.py` 在未设置 `REVIVE_DOCKER_AVAILABLE=1` 时**自动 skip** 这些
  用例，并在跳过原因里写明「沙箱禁止命名管道」；
- **禁止伪造通过**：不许把 `requires_docker` 用例改成 `pass`，也不许把 skip 变成
  「已验证」。

---

### 5.1 在沙箱外的终端跑 Docker 验收（推荐流程）

1. 打开一个**不受 DSH 沙箱限制**的终端（普通 PowerShell / Windows Terminal）。
2. `cd C:\Users\<you>\Desktop\WildProject\ReviveOS`。
3. `. .\tools\dev_env.ps1`（可选）；确认 daemon：
   `docker version` 能打印 Server 段，`docker info` 不报管道错误。
4. 起三件套：
   `docker compose -f infra/compose/dev.docker-compose.yml up -d`
5. 等 health：`docker compose -f infra/compose/dev.docker-compose.yml ps`
   —— `postgres` / `redis` / `minio` 都应为 `healthy`。
6. 冒烟 SQL：
   `docker compose -f infra/compose/dev.docker-compose.yml exec postgres psql -U revive -c "select 1"`
   —— 应返回 `1`。
7. 初始化桶（`capsules` / `artifacts`）：
   `docker compose -f infra/compose/dev.docker-compose.yml run --rm minio-init`
   验证：`docker compose ... exec minio mc ls local`
   （MinIO 发行镜像同时带 `mc` 与静态 `curl`，见 §5.2）。
8. 在该终端跑 Docker 相关测试：
   `$env:REVIVE_DOCKER_AVAILABLE = "1"; .venv\Scripts\python.exe -m pytest -q tests -m requires_docker`
9. 收尾：`docker compose -f infra/compose/dev.docker-compose.yml down`（加 `-v` 连卷一起删）。

`make dev` / `make dev-down` / `make dev-ps` / `make dev-logs` 对应同样的 compose 命令。

### 5.3 跑 Celery worker 与端到端冒烟（实测流程）

worker 与 API 是两个进程，都要有 `DATABASE_URL` 和 `REDIS_URL`。
默认 prefork 池实测可用（celery 5.6.3 / billiard 会 `SpawnPoolWorker-N` 起子进程）；
想少一堆子进程、日志更好读，就加 `--pool=solo`（下文用 solo）。

```powershell
# 终端 A：迁移 + worker
$env:DATABASE_URL = "postgresql+asyncpg://revive:revive@localhost:5432/revive"
$env:REDIS_URL    = "redis://localhost:6379/0"
.venv\Scripts\python.exe -m alembic -c apps\api\alembic.ini upgrade head
.venv\Scripts\python.exe -m celery -A revive_api.celery_app worker -l info --pool=solo -Q revive

# 终端 B：提交一个真 job 并断言「入库 + 上 Redis + 终态」
.venv\Scripts\python.exe tools\verify_worker_smoke.py
```

看到 `status=... persisted_events=N redis_events=N` 且退出 0 即通过。本机若 Docker 不可达，
worker 会走 `SandboxUnavailableError` 拒绝路径，终态是 `failed`（reason `worker_error`），
冒烟工具对此判定为通过——它验的是 broker/持久化/事件传输，不是沙箱本身。
没有 worker 进程时，任务会滞留在 broker 队列里，`verify_worker_smoke.py` 会超时并退出 1。

测试默认走 inline 执行器（`MemoryStore.durable = False`），不需要 Redis/Celery；
显式强制：`$env:REVIVE_WORKER__INLINE = "1"`。

### 5.2 dev compose 的设计取舍（实测/查证结论）

- 服务名与端口固定：`postgres:5432`、`redis:6379`、`minio:9000/9001`；
- `postgres` 用 `pgvector/pgvector:pg16`；`minio` 默认桶 `capsules`、`artifacts`；
- 三件套各有 healthcheck；`minio-init` 是**一次性**桶初始化容器，挂在
  `bootstrap` profile 下，所以裸 `docker compose up -d` 仍然只起三个服务；
- **不得**加 `privileged: true` / `cap_add: [SYS_ADMIN]`，也不挂宿主绝对路径；
- MinIO 的 healthcheck 用 `curl -f http://localhost:9000/minio/health/live`。
  查证结论：MinIO **曾经移除** curl（issue #18371），随后在 release 镜像里通过
  `download-static-curl` 又把静态 `curl` 拷进 `/usr/bin/`（同时还有 `mc`）。
  所以必须用**较新的镜像 tag**；如果用 2023 年的旧 tag，healthcheck 会一直失败。
  不要换成 `mc ready local`：那需要一个镜像没有设置的 alias。

### 5.4 生产栈验收（沙箱外必跑）

```powershell
# 1) 静态解析（不需要 daemon；提供占位值即可，禁止用于真实部署）
$env:API_DIGEST=('a'*64); $env:WORKER_DIGEST=('b'*64); $env:WEB_DIGEST=('c'*64)
$env:POSTGRES_DIGEST=('d'*64); $env:REDIS_DIGEST=('e'*64); $env:CADDY_DIGEST=('f'*64)
$env:REVIVE_API_IMAGE='ghcr.io/you/reviveos-api'; $env:REVIVE_WORKER_IMAGE='ghcr.io/you/reviveos-worker'
$env:REVIVE_WEB_IMAGE='ghcr.io/you/reviveos-web'; $env:REVIVE_DOMAIN='localhost'
$env:POSTGRES_PASSWORD=('a'*64); $env:REDIS_PASSWORD=('b'*64)
$env:REVIVE_WORKER_TOKEN='c'; $env:DOCKER_GID='999'
docker compose -f infra/compose/prod.docker-compose.yml config --no-env-resolution --quiet

# 2) 跨进程持久化验收（需要可用的 PostgreSQL + 已迁移的表）
$env:DATABASE_URL = "postgresql+asyncpg://revive:revive@localhost:5432/revive"
.venv\Scripts\python.exe -m pytest -q tests\integration\api\test_api_persistence.py
```

第 2 步是「API 不再退回进程内内存」的硬验收：它用两个独立 app 实例证明
一个实例写入的项目能被另一个实例读到。在 DSH 沙箱内该用例必然 skip（无 daemon），
**不要**把它当成通过。

### 5.5 `next build` 无法在沙箱内执行（根因已定位）

`next build` 报 `spawn EPERM` 的根因不是配置问题：Next 14.2.35 内置的
`jest-worker` 产物里**没有** `NodeThreadWorker`（只有 `ChildProcessWorker`），
因此 `experimental.workerThreads` 开关无法避免 fork；而 DSH 沙箱禁止 `fork`。
`option cpus` / `workerThreads` 实验项已实测无效。

结论：Web 生产构建与 Electron 打包必须在沙箱外或 CI/容器中执行：

```powershell
$env:NEXT_PUBLIC_REVIVE_API_URL = "/"   # 生产同源；桌面端由 Electron 注入绝对地址
node_modules\.bin\next build            # 或 pnpm --filter web build
```

替代验证（沙箱内可做）：`pnpm --filter web typecheck` + `next lint`，
以及 `tests/unit/api/test_compose_config.py` 对构建输入的一致性检查。

---

## 6. Makefile 目标 ↔ 真实命令

| 目标 | 真实命令（Windows） |
| --- | --- |
| `make sync` | `uv sync --all-packages`（需 `UV=` 指向 uv.exe） |
| `make test` | `.venv\Scripts\python.exe -m pytest -q` |
| `make unit` | `.venv\Scripts\python.exe -m pytest -q tests -m "not requires_docker"` |
| `make contracts` | `.venv\Scripts\python.exe tools\check_contracts.py` |
| `make check-rules` | `.venv\Scripts\python.exe tools\check_global_rules.py .` |
| `make lint` | `ruff check .` + `ruff format --check .` |
| `make fmt` | `ruff format .` + `ruff check --fix .` |
| `make typecheck` | `mypy packages/core/src cli/src agents/src apps/api/src` |
| `make pre-commit` | `.venv\Scripts\python.exe -m pre_commit run --all-files` |
| `make dev` | `docker compose -f infra/compose/dev.docker-compose.yml up -d` + `run --rm minio-init` |
| `make dev-down` | `docker compose -f infra/compose/dev.docker-compose.yml down` |
| `make web-install` | `node .tools/pnpm/node_modules/pnpm/bin/pnpm.cjs install` |
| `make migrate` | 先 `set DATABASE_URL=postgresql+asyncpg://revive:revive@localhost:5432/revive`，再 `.venv\Scripts\python.exe -m alembic -c apps\api\alembic.ini upgrade head`（`alembic.ini` 里不放连接串，缺 `DATABASE_URL` 直接报错；迁移用 psycopg 同步驱动，env.py 自动把 `+asyncpg` 换掉） |
| `make migrate-rollback` | 同上，把 `upgrade head` 换成 `downgrade base` |
| `make web-check` | `pnpm --filter web typecheck` + `pnpm --filter web lint`（沙箱内可跑） |
| `make web-build` | 上面两条 + `pnpm --filter web build`（**沙箱内必失败**，见 §5.5） |
| `make ci` | `lint` → `typecheck` → `unit` → `contracts` → `check-rules` → `web-check`，等价于 `.github/workflows/ci.yml` |
| `make prod-check` | `tools/image_digests.py` + 导出 OpenAPI 并与 `schemas/openapi/openapi.json` 比对（漂移即失败） |

`pre-commit` 的 6 个 hook 与 CI 完全一致（ruff → ruff format → mypy → pytest →
jsonschema 契约 → global rules）。全部是 `repo: local` + `language: system`：
沙箱没有外网去 clone hook 环境，所以刻意不依赖任何远程 hook 仓库。

---

## 7. WSL2 路径挂载坑（本机相关的至少 4 条）

1. **`/mnt/c/...` 与 `/c/...` 不是一回事。**
   WSL2 里 Windows 盘挂载点是 `/mnt/c/Users/...`；Git-Bash/MSYS 风格是
   `/c/Users/...`。在 WSL 里写 `/c/Users/...` 会得到一个**空目录**（或直接 ENOENT），
   compose 不会报错，容器里却什么都看不到。统一用 `/mnt/c/...`。
2. **跨文件系统（drvfs）IO 慢且没有 inotify。**
   把仓库放在 `/mnt/c` 下时，`uvicorn --reload`、Next.js HMR、pytest-watch
   都不会触发（或延迟数秒）。重任务建议把仓库 clone 进 WSL 自己的文件系统
   （如 `~/reviveos`），或在容器里用 named volume 存 `node_modules` / `.venv`。
3. **CRLF 会杀掉 shell 入口脚本。**
   Windows 检出默认可能带 CRLF；Linux 容器里执行挂载进来的 `.sh` 会报
   `bad interpreter: ...^M`。挂载 shell 脚本前先 `dos2unix`，或统一
   `git config core.autocrlf input` + `.gitattributes`。
4. **权限元数据默认关闭。**
   `/mnt/c` 默认不启用 metadata，容器里看到的权限往往是 `0777`/`0755` 一刀切；
   SSH key、凭据文件无法收紧为 `0600`。需要时用
   `/etc/wsl.conf` 的 `[automount] options = "metadata"`（改完 `wsl --shutdown`）。
5. **大小写不敏感 + 保留名。**
   `/mnt/c` 默认大小写不敏感，且 `CON`/`AUX`/`NUL` 等 Windows 保留名会导致
   容器内 `mkdir CON` 之类的操作诡异失败。构建产物命名避开这些。

## 8. `:ro` 只读挂载坑（至少 4 条）

1. **`:ro` 是「整棵子树只读」，不是「源文件只读」。**
   容器里任何要写同目录缓存的步骤都会失败：`pip` 写 `~/.cache/pip`、
   pytest 写 `.pytest_cache`、Node 写 `node_modules`/ `.next` 都会得到
   `EROFS`/`EACCES`。做法：源码 `:ro`，缓存和产物挂**可写的 named volume**。
2. **路径不存在时 Docker 会创建一个空目录（即使带 `:ro`）。**
   挂载路径写错不会报错，只会得到一个空的只读目录，程序看到「工作区是空的」。
   挂载前先确认宿主路径存在，并用绝对路径。
3. **`:ro` 挂单个文件时，宿主文件必须已经存在。**
   若文件不存在，Docker 会**创建一个同名目录**，容器里那个「配置文件」其实是个目录，
   读取直接失败（经典事故）。
4. **改了宿主文件但容器里还是旧内容/仍只读。**
   Windows + WSL2 下 bind mount 偶发缓存陈旧；先 `docker compose restart <svc>`，
   仍不行就 `down` 再 `up -d`，必要时重启 Docker Desktop。
5. **沙箱内额外注意**：仓库里已有 `.tools\git`、`.venv\` 等庞大目录，
   不要把它们整体 `:ro` 挂进容器当工作区——容器只需要被复生项目的 workspace。

---

## 9. 常见故障速查

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| `Get-Command make` 为空 | 本机没装 GNU Make | 直接跑 §6 的真实命令 |
| `uv` 找不到 | 不在 PATH | 用 `%USERPROFILE%\.local\bin\uv.exe`，并设置 §2 三个变量 |
| `git` 找不到 | 系统未安装 | `. .\tools\dev_env.ps1`，或用 `REVIVE_GIT_BIN` 指向 `.tools\git\cmd\git.exe` |
| `GitUnavailableError` | 三处都没有 git | 按异常提示设置 `REVIVE_GIT_BIN` 或安装便携版 |
| npm 安装卡死/超时 | npmjs 不可达 | 确认 `.npmrc` 存在且指向 registry.npmmirror.com |
| docker 报管道/连接错误 | 在沙箱内 | 换沙箱外终端，见 §5.1 |
| 一屏 `WinError 5` pytest 缓存警告 | 沙箱拒绝临时目录改名 | 已用 `-p no:cacheprovider` 关闭 |
| ruff 直接 panic | 走进了不可读的 `pytest-cache-files-*` | 已在 ruff `extend-exclude` 排除 |
| pre-commit 说 `not a git repository` | 工作区还没 `git init` | 在沙箱外 `.tools\git\cmd\git.exe init` |

---

## 10. 交付前的自检清单

```powershell
.venv\Scripts\python.exe -m pytest -q                                   # 单元 + 契约
.venv\Scripts\python.exe tools\check_contracts.py                       # schema 契约
.venv\Scripts\python.exe tools\check_global_rules.py .                  # 全局红线
.venv\Scripts\python.exe -m ruff check .                                 # lint
.venv\Scripts\python.exe -m mypy packages/core/src cli/src agents/src apps/api/src
.venv\Scripts\python.exe -m pre_commit run --all-files                   # 与 CI 同闸门
```

Docker 三件套的验收必须在**沙箱外**终端按 §5.1 执行，并把真实输出贴进交付说明。
