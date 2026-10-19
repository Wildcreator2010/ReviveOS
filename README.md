# ReviveOS

软件运行时复生与可复现基础设施。目标：把已经"死掉"的软件（作者失联、没有测试基线、依赖版本断裂、运行环境消失）
在真实历史环境里重新构建、修复、验证行为，并产出一份可长期复现的 `.revive` 胶囊。

## 一、这是什么形态的产品？

**它是一套软件，而不是一个网站。** Web 控制台只是它的一种界面。完整形态：

| 形态 | 说明 | 目录 |
| --- | --- | --- |
| 桌面软件 | Windows 可安装程序（Electron 壳 + 打包后的控制台 UI），双击即用，可连本地或远端后端 | `apps/desktop` |
| Web 控制台 | 同一套 UI，"Software ICU" 过程可视化；可作为浏览器界面使用 | `apps/web` |
| CLI | `revive analyze / resurrect / verify / replay` 等命令，本地与服务器两种模式 | `cli` |
| 后端控制面 | FastAPI + PostgreSQL + Redis + Celery：编排、鉴权、事件、存储 | `apps/api` |
| 核心引擎 | 考古引擎、环境推断、沙箱执行、行为指纹、评分、胶囊 | `packages/core` |
| 智能体 | LangGraph 编排的考古补强 / 修复 / 行为采集 Agent | `agents` |

数据流：

```
CLI / 桌面软件 / 浏览器
        |
        v
后端控制面 (FastAPI, /api/v1, SSE 事件流)
        |
        v
Celery worker -> LangGraph supervisor -> LLM Provider (fake/openai/anthropic/custom)
        |
        v
沙箱 (Docker) -> 历史镜像 -> 依赖回溯安装 -> build/test -> patch 回滚 -> 行为指纹
        |
        v
Resurrection Score + .revive 胶囊 (manifest + genome + sbom + provenance)
```

## 二、仓库结构

```
packages/core/     revive_core：域模型、配置、考古引擎、环境推断、错误分类、评分
agents/            revive_agents：LLM Provider、prompt 注册表、节点、supervisor
cli/               revive_cli：命令行入口
apps/api/          revive_api：FastAPI 控制面
apps/web/          Next.js 14 控制台（Software ICU）
apps/desktop/      Electron 桌面壳（Windows 安装包）
schemas/           四个核心 JSON Schema（唯一事实来源）
infra/             dev/prod compose、可观测性
benchmarks/        ReviveBench 数据集、runner、报告、demo
tools/             开发环境脚本与全局规则检查
tests/             单元 / 集成 / 契约测试
docs/              设计与工单文档（单一事实来源）、运行手册
```

## 三、本机开发环境（已实测）

本机（Windows）已就绪的完整工具链：

| 组件 | 位置 / 版本 | 说明 |
| --- | --- | --- |
| Python | `.venv`（CPython 3.11.16） | 由 uv 创建；`uv run pytest` 可直接用 |
| uv | `%USERPROFILE%\.local\bin\uv.exe`（0.12.10） | 不在 PATH；仓库内 `.tools/bin/uv.cmd` 提供同名 shim |
| git | `.tools/git/cmd/git.exe`（2.47.1） | 系统未装 git，使用便携版；`REVIVE_GIT_BIN` 指向它 |
| Node.js | 系统安装（v24） | 前端与桌面壳构建 |
| pnpm | `.tools/pnpm/node_modules/pnpm`（9.12.3） | 通过 `tools/dev_env.ps1` 注册为函数 |
| Docker | Docker Desktop 29.8 | **沙箱内无法访问 daemon**，见下 |

一次性引导（Windows PowerShell 5.1 默认禁止未签名脚本，需先放开进程级执行策略）：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
. .\tools\dev_env.ps1
```

该脚本会注入 git / uv / pnpm 到 PATH，设置 `REVIVE_GIT_BIN`，并把 uv、pnpm、electron 的缓存目录全部
指向工作区内（沙箱只允许写工作区）。

常用命令：

```powershell
uv sync --all-packages                      # 安装/更新全部 Python 依赖
uv run pytest -q                            # 全量测试
uv run pytest tests/unit/core -q            # 只跑核心引擎
uv run ruff check . && uv run ruff format --check .
uv run python tools/check_global_rules.py . # 全局红线检查（密钥、修复上限常量）
pnpm install                                # 前端依赖（走 .npmrc 的镜像源）
pnpm --filter web typecheck                 # 控制台类型检查（生成的 API 类型）
pnpm --filter web lint                      # 控制台 ESLint
pnpm --filter web build                     # 生产构建（需能 fork 子进程的环境）
pnpm --filter desktop dist                  # 打包 Windows 桌面安装程序
docker compose -f infra/compose/dev.docker-compose.yml up -d   # 需在沙箱外终端执行
```

一次跑完与 CI 等价的门禁：`make ci`（Windows 未装 make 时，按 [docs/dev-environment.md](docs/dev-environment.md) §6 逐条执行）。
生产前的静态检查：`make prod-check`（镜像 digest 占位符 + Compose 定义 + OpenAPI 快照漂移）。

### 已知环境限制（重要）

1. **Docker 在 DSH 沙箱内不可用**：沙箱禁止访问命名管道，`docker info` 报 permission denied。
   所有带 `requires_docker` 标记的集成测试在本会话中会被跳过；请在**沙箱外的普通终端**执行。
   这包括新增的跨进程持久化验收 `tests/integration/api/test_api_persistence.py`。
2. **`next build` / `next dev` 在沙箱内不可用**：Next 14 内置 jest-worker 只有
   `ChildProcessWorker`（无线程实现），必须 fork，而沙箱禁止 spawn（`EPERM`）。
   Web/Electron 构建请在沙箱外或 CI 执行；沙箱内可跑 `web typecheck`、`web lint`。
3. **registry.npmjs.org 不可达**，但 `registry.npmmirror.com` 可达；仓库根 `.npmrc` 已固定镜像源。
4. **Windows 原生 TLS 栈（curl / Invoke-WebRequest / certutil）被拦截**，下载请用 Python+urllib 或 uv。
   大文件需使用分块 Range 下载（见 `tools/fetch_git_range.py` 的做法）。
5. **npm/uv/pnpm 的默认用户级缓存目录不可写**，必须使用工作区内缓存目录（`dev_env.ps1` 已处理）。

详见 [docs/dev-environment.md](docs/dev-environment.md)。

## 三·五、交付状态

**[DELIVERY.md](DELIVERY.md)** 是本仓库的交付收口证据表：已验证门禁、待沙箱外验证项（含精确命令）、
上线前人工清单、以及已知限制。阅读顺序建议：本文件 → DELIVERY → [生产就绪](docs/production-readiness.md)。

## 四、设计原则（不得违反）

- **Evidence First, AI Second**：考古引擎不调用任何 LLM 也能产出环境基因；LLM 只做补强，且幻觉证据必须被拦截。
- **AI 不直接落地修改**：所有 Patch 必须过 校验 → 沙箱 Build → Test 三环，失败回滚。
- **目标代码只存在于沙箱容器内**：运行期禁网、非 root、no-new-privileges、tmpfs、超时清扫。
- **契约先行**：`schemas/` 与 OpenAPI 快照是唯一事实来源，变更必须同 PR 提交。
- **数字必须来自真实运行**：Benchmark 未跑出的格子写"待测"，禁止编造。
- **代码中禁止出现真实密钥**：全部走 `REVIVE_*` 环境变量。

## 五、文档索引

- [总览与派发指南](docs/tasks/00-总览与派发指南.md)
- [01 基础设施与契约](docs/tasks/01-基础设施与契约.md) · [02 核心域与考古引擎](docs/tasks/02-核心域与考古引擎.md) · [03 智能体与模型接入](docs/tasks/03-智能体与模型接入.md) · [04 沙箱与复生流水线](docs/tasks/04-沙箱与复生流水线.md) · [05 后端 API 与数据层](docs/tasks/05-后端API与数据层.md) · [06 前端 Web 控制台](docs/tasks/06-前端Web控制台.md) · [07 生产化安全与部署](docs/tasks/07-生产化安全与部署.md) · [08 ReviveBench 与 Demo 交付](docs/tasks/08-ReviveBench与Demo交付.md)
- [Agent 工作包索引](docs/agents/README.md)
- [开发环境](docs/dev-environment.md) · [桌面软件](docs/desktop-app.md)
- [市场调研报告](research/ReviveOS市场调研报告.md)
