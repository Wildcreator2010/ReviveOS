# Agent 工作包 06 · 前端控制台官（Frontend Officer）

- **Wave**：W4（后端 OpenAPI 快照冻结后即可开工；T-FE-01/02 可与 W3 提前启动）
- **负责栈**：`docs/tasks/06-前端Web控制台.md`（T-FE-01…11），产出物全部在 `apps/web/`
- **你的使命**："Software ICU" 控制台：从提交到胶囊下载的全视觉旅程，核心是 16 类事件的实时可视化。**M4 归你（与后端官合签）。**

## 投喂清单
1. 本文件
2. `docs/tasks/00-总览与派发指南.md`（§1 Web 决策：Next.js 14 strict / TanStack Query / 生成码）
3. `docs/tasks/06-前端Web控制台.md`（工单正文，含 ICU 视觉基调头部）
4. `schemas/openapi/openapi.json` + `schemas/job-event.schema.json` + `schemas/resurrection-score.schema.json`（渲染数据形状的唯一依据）
5. `docs/agents/agent-05-backend.md` 的"接口承诺"一节（了解 SSE 帧格式与错误码枚举）

## 执行顺序与要点
| 序 | 工单 | 额外注意 |
|---|---|---|
| 1 | T-FE-01 | 状态色 tokens 是全站合同：alive/partial/dead/running 只从 `tokens.ts` 出 |
| 2 | T-FE-02 | 生成文件 DO NOT EDIT 头 + CI diff 校验，一次到位 |
| 3 | T-FE-03 | access 内存态 + refresh httpOnly cookie；401 单飞刷新防惊群 |
| 4 | T-FE-06 | **产品灵魂页**：断线重连/Last-Event-ID/虚拟滚动/降级态四件事每件都要有 Playwright 剧本 |
| 5 | T-FE-04 ∥ 05 | 列表三态（满/空/错）与向导四态（合法/非法/409/429） |
| 6 | T-FE-07 ∥ 08 ∥ 09 | 证据链、diff、评分三视图：低置信与"AI 补强"徽章、回滚删除线、null 行为基线诚实显示 |
| 7 | T-FE-10 → 11 | 胶囊页走 API 不解析 tar；最后统一收口 a11y + 375px + 全链冒烟 = M4 |

## 协作界面
- 与后端官：任何字段缺失/含义不明 → 提 issue 到对应工单分支，不得私加 mock 字段进生产代码路径。
- 与智能体官：无直接依赖（事件经契约与后端中转）。

## 完成定义
- [ ] 11 条工单验收输出齐（Playwright 各 spec + 真后端冒烟）
- [ ] `pnpm --filter web lint build` 绿；axe 0 critical；对比度实测记录
- [ ] M4 录屏：浏览器粘贴 fixture URL → 直播 → 报告 → 下载胶囊 全程无手改数据

## 禁止
- 禁止手写接口类型（只能生成码）；禁止在前端重算 score；禁止任何假数据混入 `src/`（MSW fixture 只准放测试目录）。
