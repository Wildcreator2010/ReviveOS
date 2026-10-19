# 06 · 前端 Web 控制台（TypeScript / Next.js 14 App Router，前缀 T-FE）

> 产品形态定位"Software ICU"（软件重症监护室）：不是 CRUD 后台，而是过程可视化。视觉基调：深底、状态色语义固定（绿=ALIVE、琥珀=PARTIAL、红=DEAD、蓝=进行中）、等宽字体展示日志与 diff。所有数据来自生成后的 OpenAPI 类型，禁止手写接口类型。

### T-FE-01 应用脚手架与设计系统基座
- 背景：建立 `apps/web` 工程与全局 shell（顶栏/侧导航/状态色 tokens/字体）。
- 涉及文件：`apps/web/package.json`、`pnpm-workspace.yaml`（root 纳入 web）、`apps/web/app/layout.tsx`、`apps/web/app/globals.css`、`apps/web/tailwind.config.ts`、`apps/web/components/ui/*`（shadcn/ui 初始化集：button/card/tabs/badge/dialog/table）、`apps/web/lib/tokens.ts`。
- 输入/输出契约：TS `strict: true` + `noUncheckedIndexedAccess`；状态色 CSS 变量 `--state-alive/partial/dead/running` 全站唯一来源；导航固定五项：`/`（提交）、`/projects`、`/jobs/:id`、`/capsules`、`/settings`；ESLint 接 prettier；Next.js 14 App Router，全部交互页标 `"use client"` 的最小化原则（Server Component 默认）。
- 验收：`pnpm --filter web lint && pnpm --filter web build` 退出 0；`pnpm --filter web exec tsc --noEmit` 0 错误；人工检查：暗色主题下四类状态色对比度 ≥ 4.5:1（记入 PR 描述）。
- 禁止：禁止引入 Redux/MobX（服务端状态一律 TanStack Query）；禁止 any。
- 依赖：T-INIT-01。

### T-FE-02 OpenAPI 类型与客户端代码生成
- 背景：后端每冻结一版 `schemas/openapi/openapi.json`，前端再生成类型化客户端，防接口漂移。
- 涉及文件：`apps/web/src/api/{types.gen.ts,client.ts}`（生成物与薄封装）、`apps/web/scripts/gen-api.mjs`、`Makefile`（`make gen-web`）。
- 输入/输出契约：`openapi-typescript` 生成类型 + 手写 60 行 fetch wrapper（baseURL、credentials、401→refresh→重放、错误体 `{error}` 解析为 `ApiError{code,status,details}`）；生成文件头带 `// GENERATED FROM schemas/openapi/openapi.json — DO NOT EDIT`；CI 校验：重新生成后 `git diff --exit-code`。
- 验收：`make gen-web && git diff --exit-code apps/web/src/api` 退出 0；`pnpm --filter web build` 绿。
- 禁止：禁止在业务代码手写 `fetch("/api/v1/...")` 裸字符串路径（一律经 client）。
- 依赖：T-FE-01、T-BE-03。

### T-FE-03 认证流程与会话管理
- 背景：登录/注册/退出；令牌策略：access（内存态）+ refresh（httpOnly cookie，后端设置），防 XSS 落盘。
- 涉及文件：`apps/web/app/(auth)/{login,register}/page.tsx`、`apps/web/src/api/session.ts`、`apps/web/components/auth/SessionGate.tsx`、`apps/web/middleware.ts`。
- 输入/输出契约：`SessionGate` 未登录跳 `/login?next=`；`middleware.ts` 对 `/projects|/jobs|/capsules|/settings` 无 cookie 即重定向（仅粗筛，真校验在后端）；401 时单飞 refresh（并发请求共享一个刷新 Promise）；API Key 页只显前缀。
- 验收：`pnpm --filter web exec playwright test tests/e2e/auth.spec.ts` 绿（本地起 mock server：登录→受保护页→过期→自动续期→退出全链路）；localStorage 断言不含 token 字符串。
- 禁止：禁止把 token 写入 cookie 以外的持久存储；禁止在 URL query 传 token。
- 依赖：T-FE-02、T-BE-04。

### T-FE-04 项目列表与详情
- 背景：核心资产管理：项目卡片（repo、最后活跃、最新 score 徽章、状态色）+ 详情页（时间线：历次 job 与胶囊）。
- 涉及文件：`apps/web/app/projects/{page.tsx,[id]/page.tsx}`、`apps/web/src/features/projects/*`、`tests/e2e/projects.spec.ts`。
- 输入/输出契约：列表游标分页 + 骨架屏；空状态给出"粘贴 GitHub URL"引导（禁止死白板）；详情页 tab：Overview/Genome/Patches/Behavior/Capsules（后四个 tab 数据端点在 T-BE-09/03，缺数据时显示"原因+下一步建议"而非空白）。
- 验收：`pnpm --filter web exec playwright test tests/e2e/projects.spec.ts` 绿（MSW mock：满页/空页/错误页三态）；人工检查：4xx 错误文案引用 `error.code` 映射表，无裸英文枚举直接示人。
- 禁止：禁止前端过滤代替后端分页参数。
- 依赖：T-FE-03。

### T-FE-05 Resurrect 提交向导（首页 ICU 面板）
- 背景：产品的"一键复生"入口：贴 URL → 选项（预算上限/超时/是否允许离线分析）→ 提交 → 跳转任务直播页。
- 涉及文件：`apps/web/app/page.tsx`（重写）、`apps/web/src/features/submit/*`、`tests/e2e/submit.spec.ts`。
- 输入/输出契约：URL 即时校验（正则 github.com 三段式）与 `POST /projects` 409（已存在）→ 提示"项目已存在，直接新建任务或查看历史"；配额 429 → 显示 `Retry-After` 倒计时；成功 302 到 `/jobs/:id`。
- 验收：`pnpm --filter web exec playwright test tests/e2e/submit.spec.ts` 绿（覆盖：合法/非法 URL、409、429、成功跳转）。
- 禁止：禁止提交后不清空/不锁定导致重复下单（提交中按钮禁用 + 幂等由后端去重兜底）。
- 依赖：T-FE-04。

### T-FE-06 任务直播页（SSE 事件时间线，M4 核心）
- 背景：15 类 `job-event` 的实时可视化，是"Software ICU"的心电图。断线自动重连（Last-Event-ID）、事件折叠、原始 JSON 可查。
- 涉及文件：`apps/web/app/jobs/[id]/page.tsx`、`apps/web/src/features/live/{useEventStream.ts,Timeline.tsx,NodeCard.tsx}`、`tests/e2e/live.spec.ts`。
- 输入/输出契约：`useEventStream(jobId)` hook：EventSource + 指数退避重连 ≤5 次后降级轮询 `GET /jobs/{id}`；事件→分节卡片（考古/环境/构建/修复/测试/行为/评分/胶囊）按类型分组聚合；`build.failed` 卡片内联 stderr excerpt 与 `error_fact.signature`；终态事件关闭流并渲染汇总条。
- 验收：`pnpm --filter web exec playwright test tests/e2e/live.spec.ts` 绿（MSW SSE mock：乱序 id 自动整理、断线重连不重复渲染、失败→修复→成功剧本动画终态正确）；人工检查：kill worker 后前端 ≤20s 显示降级态而非永久转圈。
- 禁止：禁止 setInterval 轮询事件流（那是重连失败后的兜底且需标注）；禁止无上限追加 DOM（>500 事件虚拟滚动）。
- 依赖：T-FE-03、T-BE-06。

### T-FE-07 考古证据视图（Genome + Evidence 链）
- 背景：展示"推断有证据、信心有出处"：genome 字段行（版本+置信度条）+ 点击展开该字段的 EvidenceItem 列表（文件/行/commit 引用）。
- 涉及文件：`apps/web/src/features/genome/*`、`tests/e2e/genome.spec.ts`。
- 输入/输出契约：confidence<0.7 字段琥珀标注并聚合到页顶"低置信项 N 个待确认"；`source_kind=inference` 的证据条目视觉区分（虚线边框 + note 必显）；提供"复制 genome.json"（走 schemas 序列化）。
- 验收：`pnpm --filter web exec playwright test tests/e2e/genome.spec.ts` 绿（fixture 数据含冲突证据 → note 显示）；人工检查：屏幕阅读器朗读 confidence 有文本替代（非仅颜色）。
- 禁止：禁止把 LLM 补强结果与规则引擎结果混同展示（`llm_reason` 字段必须带 "AI 补强" 徽章）。
- 依赖：T-FE-04、T-BE-09。

### T-FE-08 修复过程视图（Patch 序列与 Diff）
- 背景：让人看清"AI 动了什么、为什么、有没有回滚"：patch 列表（序号/风险/结果）+ unified diff 渲染 + 回滚态标记。
- 涉及文件：`apps/web/src/features/patches/*`、`tests/e2e/patches.spec.ts`。
- 输入/输出契约：diff 渲染用 `@types/diff` 解析 + 自绘（无重量级编辑器依赖）；每条 patch 显示 rationale 摘要与 `error_fact.signature` 触发链；`rolled_back=true` 的尝试保留显示并划删除线（失败尝试也是证据）；超限拒绝（`Refused`）显示权限上限文案（5/10/300）。
- 验收：`pnpm --filter web exec playwright test tests/e2e/patches.spec.ts` 绿（含成功/回滚/拒绝三态 fixture）；人工检查：3000 行 diff 渲染 <1s（虚拟列表）。
- 禁止：禁止提供"前端一键合并 patch 到目标仓库"（复生不改上游是产品原则）。
- 依赖：T-FE-06。

### T-FE-09 行为报告与 Resurrection Score
- 背景：九宫格式体检单：总分大数字 + 六分量条形（权重 tooltip）+ 行为兼容率 + 逐用例漂移明细；`compatibility=null` 必须诚实显示"无行为基线"及其原因。
- 涉及文件：`apps/web/src/features/report/*`、`tests/e2e/report.spec.ts`。
- 输入/输出契约：分数渲染只读 `resurrection-score` 契约实例（前端零重算，显示值==API 值）；numeric 容差的用例展示 `|a-b| ≤ eps` 计算式；"状态判定"徽章按 T-CAP-01 映射（alive/partial/dead），tooltip 列出触发降级的分量。
- 验收：`pnpm --filter web exec playwright test tests/e2e/report.spec.ts` 绿（含 null 基线与 dead 判定剧本）；人工检查：score 断言与 API 返回值严格相等（无前端四舍五入偏差 >0.05）。
- 禁止：禁止用颜色单独承载信息（同 T-FE-07 无障碍原则）。
- 依赖：T-FE-06、T-CAP-01。

### T-FE-10 胶囊页与用户设置
- 背景：胶囊详情（manifest 树、各文件 sha256、SBOM 摘要、provenance 阅读视图、presigned 下载）；设置页（个人资料、API Key 增删、当前配额展示）。
- 涉及文件：`apps/web/app/capsules/{page.tsx,[id]/page.tsx}`、`apps/web/app/settings/page.tsx`、`tests/e2e/capsules.spec.ts`。
- 输入/输出契约：manifest 树渲染读 `revive-manifest` schema 结构（不解析 tar 内容——列表来自 API）；下载按钮走 `GET /capsules/{id}/download`；API Key 创建后明文只显示一次+复制按钮；404/软删态友好页。
- 验收：`pnpm --filter web exec playwright test tests/e2e/capsules.spec.ts` 绿；人工检查：胶囊 provenance 视图能回答"哪个证据支撑哪个版本决策"。
- 禁止：禁止在前端拼 presigned URL。
- 依赖：T-FE-04、T-BE-07。

### T-FE-11 响应式与无障碍收口 + E2E 冒烟套件
- 背景：全链路 E2E（真后端 dev compose）+ 移动端宽度 375px 可用性 + 键盘全可达 + 焦点管理。
- 涉及文件：`tests/e2e/smoke-full.spec.ts`（标记 `against_live`）、`apps/web/tests/a11y/*`（axe-core 扫描各页）、`docs/web-qa-checklist.md`。
- 输入/输出契约：冒烟剧本=真实提交 fixture 仓库→直播页→报告页→下载胶囊全绿；a11y：每页 axe 严重违规 0；键盘 Tab 序可达所有动作按钮并可见焦点环；`prefers-reduced-motion` 时事件流动画降级为静态列表。
- 验收：`pnpm --filter web exec playwright test tests/e2e/smoke-full.spec.ts --project=chromium` 对 dev compose 全绿；axe 报告 0 critical；375px 宽截图贴 PR。
- 禁止：禁只用 hover 承载功能（触屏无 hover）。
- 依赖：T-FE-06..10、T-BE-07。
