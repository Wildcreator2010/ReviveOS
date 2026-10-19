# ReviveOS 桌面版（Electron + Next.js 静态导出）

> 目标形态：把 Web 控制台变成**可安装的 Windows 软件**，双击即用；后端（控制面）默认连本机
> `http://127.0.0.1:8000`，可在「设置」里改成远端地址并持久化。

## 1. 组成与数据流

```
apps/web    Next.js 14 App Router 控制台（纯客户端 SPA，output: "export" 静态导出）
apps/desktop Electron 主进程 + preload 桥（无 Node 权限的渲染进程）
    ├── 生产：把 apps/web/out 拷进 asar 的 web/ 目录，由 127.0.0.1 上的
    │        内建静态文件服务（随机端口、仅回环）加载
    ├── 开发：REVIVE_WEB_URL 指定正在跑的 next dev 服务器
    ├── 配置：%APPDATA%\ReviveOS ICU\revive-desktop.json（API 地址）
    │         %APPDATA%\ReviveOS ICU\revive-window-state.json（窗口位置/大小/最大化）
    └── 后端：探测 → 可选拉起（需显式开启）→ 失败即如实报告离线
渲染进程只通过 contextBridge 暴露的 6 个方法访问系统能力：读设置、写 API 地址、
读运行时信息、发通知、订阅后端状态、订阅菜单跳转。没有 ipcRenderer / fs / child_process。
```

为什么不在生产环境用 `file://` 直接加载导出目录：Next 导出的 HTML 用绝对路径引用
`/_next/...` 资源，`file://` 下会被跨源策略拦截。回环静态服务保持了与 Web 完全一致的
路由、RSC payload 与资源加载行为，同时渲染进程依旧没有 Node 权限。

## 2. 环境前提（本工作区实测）

| 项 | 值 |
| --- | --- |
| Node | v24.20.0（`C:\Program Files\nodejs\node.exe`） |
| pnpm | 9.12.3，工作区内置：`.tools\pnpm\node_modules\pnpm\bin\pnpm.cjs`（不在 PATH） |
| registry | `registry.npmjs.org` 在本沙箱不可达；根 `.npmrc` 固定 `registry.npmmirror.com` |
| 缓存 | 用户级 npm/pnpm 缓存目录不可写，必须用工作区内缓存（见下） |

先注入环境（会设置 `npm_config_cache`、`PNPM_STORE_DIR`、`ELECTRON_CACHE`、
`ELECTRON_BUILDER_CACHE`、便携 git、uv、pnpm 函数）：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
. .\tools\dev_env.ps1
```

Electron 二进制从 GitHub 发行版下载。Node 直连 `github.com` 在本沙箱会失败，
必须走镜像（`.tools\dev_env.ps1` 未设置 `ELECTRON_MIRROR`，需手动加）：

```powershell
$env:ELECTRON_MIRROR = "https://registry.npmmirror.com/-/binary/electron/"
```

## 3. 安装依赖

```powershell
. .\tools\dev_env.ps1
$env:ELECTRON_MIRROR = "https://registry.npmmirror.com/-/binary/electron/"
pnpm install --registry=https://registry.npmmirror.com --ignore-scripts
```

> **本沙箱已知限制（实测）**：pnpm 通过管道捕获 postinstall 输出时会触发 `spawn EPERM`
> （沙箱禁止命名管道，见工具说明），因此 `pnpm install` **不加** `--ignore-scripts` 会在
> `electron postinstall` 处报 `Error: spawn EPERM`（依赖本身已装好，链接未完成）。
> 解决办法：用 `--ignore-scripts` 完成链接，再手动执行需要的 postinstall：

```powershell
# 1) 完成依赖链接（不跑脚本）
pnpm install --registry=https://registry.npmmirror.com --ignore-scripts

# 2) 手动拉 Electron 二进制（走镜像 + 工作区缓存）
cd apps\desktop\node_modules\electron
node install.js
cd ..\..\..
Test-Path apps\desktop\node_modules\electron\dist\electron.exe   # 必须为 True
```

## 4. 常用脚本

| 命令 | 作用 |
| --- | --- |
| `pnpm dev:web` | 启动 Web 控制台开发服务器（:3000） |
| `pnpm build:web` | `next build`：lint + 类型 + 静态导出到 `apps/web/out` |
| `pnpm build:desktop` | `tsc -p apps/desktop`：编译主进程/preload 到 `apps/desktop/dist` |
| `pnpm --filter desktop dev` | 用 Electron 加载 `REVIVE_WEB_URL`（默认 http://127.0.0.1:3000） |
| `pnpm dist` | 先 `build:web` 再 `electron-builder --win nsis`，产物在 `apps/desktop/release` |
| `pnpm --filter desktop dist:dir` | 只产出免安装目录（release/win-unpacked），用于快速验证打包 |

`apps/desktop/package.json` 的 `dist` 会先把 `apps/web/out` 拷进 `apps/desktop/web/`：

```json
"dist": "pnpm run build && electron-builder --win nsis --x64 --publish never"
```

（`build` 之前必须已执行 `pnpm --filter web build`；`pnpm dist` 在根目录已串好顺序。）

## 5. 打包产物

- 输出目录：`apps/desktop/release`
- 安装包名称：`ReviveOS ICU-0.1.0-setup.exe`（NSIS，允许选择安装目录、创建桌面/开始菜单快捷方式）
- 打包内容（asar）：`dist/**`（主进程 + preload）、`web/**`（Next 静态导出）、`package.json`
- 未签名：本沙箱无法访问代码签名服务（electron-builder 需要从 GitHub 下载 `winCodeSign`，
  沙箱直连 GitHub 会失败），因此默认不签名。Windows SmartScreen 会提示未知发布者，
  正式发布时请设置 `CSC_LINK`/`CSC_KEY_PASSWORD` 或改用 Azure Trusted Signing。

如果 `electron-builder` 因无法下载工具链（winCodeSign / nsis / nsis-resources）失败，
把镜像缓存指向国内源后重试（`ELECTRON_BUILDER_CACHE` 已在 `dev_env.ps1` 内指向工作区）：

```powershell
$env:ELECTRON_BUILDER_BINARIES_MIRROR = "https://registry.npmmirror.com/-/binary/electron-builder-binaries/"
pnpm --filter desktop dist
```

## 6. 后端地址如何配置

优先级（高 → 低）：

1. 「设置」页保存的地址（桌面版由主进程写入 `%APPDATA%\ReviveOS ICU\revive-desktop.json`；
   浏览器版只写 localStorage，仅供本机使用）
2. 主进程环境变量 `REVIVE_API_URL`
3. 构建期注入的 `NEXT_PUBLIC_REVIVE_API_URL`（`next.config.mjs` 默认值）
4. 默认值 `http://127.0.0.1:8000`

设置页保存后立即对当前窗口生效（fetch 客户端的内存 override），并会重新探测新地址；
重启应用后仍然生效。设置页只显示 API Key 前缀（前 8 位），明文只在创建响应中出现一次。

### 桌面版是否会自己启动后端

默认**只连接、不启动**：`GET /healthz` 探测成功则标记 `external`。
如果探测失败并且显式设置了：

```powershell
$env:REVIVE_DESKTOP_SPAWN_BACKEND = "1"
```

主进程会尝试用工作区 venv 拉起 `uvicorn revive_api.main:app`（需要 `.venv\Scripts\python.exe`
与 `apps/api/src` 存在），启动后**再用真实探测确认**，失败就如实标记 `failed`。
打包后的安装版没有 Python 运行时，因此该开关只在开发工作区有意义。

## 7. 离线时的表现

- 顶栏状态徽章：控制面不可达 → 红色「控制面离线」；可达但 `/readyz` 503 → 琥珀「控制面降级」
  （并列出 `postgres=unavailable` 之类的组件名）。
- 每个页面：加载失败且是网络层错误时显示**离线空态**（含目标地址与「重试」按钮），
  不渲染任何伪造数据；API 可达但列表为空时显示**空态**并说明原因与下一步。
- 任务直播页：SSE 连接失败按指数退避重连最多 5 次；用尽后降级为每 5 秒轮询
  `GET /api/v1/jobs/{id}`，并显式显示「已降级为轮询」横幅（不会永久转圈）。
- 窗口关闭（点 ×）只隐藏到托盘；托盘菜单可显示窗口、打开控制面地址、退出。

## 8. 通知

任务完成通知由渲染进程的 `useJobNotifications` 触发，**只在真实 SSE 事件到达时**：
`build.failed` / `repair.applied` / `score.computed` / `capsule.created` / `job.succeeded` /
`job.failed`，并对同一阶段去重。主进程只负责 `Notification` 展示。

## 9. 已知阻塞（诚实清单）

1. **OpenAPI 生成码缺失**：`schemas/openapi/openapi.json` 尚未由后端产出，
   `apps/web/src/api/types.gen.ts` 只能是路径/方法占位（`node apps/web/scripts/gen-api.mjs`
   会以退出码 2 明确报阻塞）。领域字段通过 `src/api/readers.ts` 的运行时读取器取值，
   缺失即显示「未知 / API 未提供」。**没有手写任何业务接口类型**。
2. **SSE 路径**：任务要求写 `/api/v1/jobs/{id}/events`；后端任务书 T-BE-06 冻结的是
   `/api/v1/jobs/{id}/events/stream`。实现采用后者（与后端契约一致），并在
   `types.gen.ts` 中同时登记两条路径；若后端最终只提供前者，改一处常量即可。
3. **后端只有骨架**：`apps/api` 目前只有 `/healthz`、`/readyz`，因此除健康检查外的
   页面只能显示空态/离线态或后端错误（如 404），这是预期行为。
4. **代码签名 / 图标**：未签名，使用占位图标 `apps/desktop/icon.png`（16x16 纯色 PNG）。
