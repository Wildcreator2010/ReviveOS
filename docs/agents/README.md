# Agent 工作包总索引（多 Agent 并行派发编排）

> 用法：每个 `agent-0X-*.md` 是一个独立执行者的工作包。派发某 Agent 时，把「工作包文件 + 它 §投喂清单 里列的文件」一起给它，即可开工。
> 工单单一事实来源仍在 `docs/tasks/0X-*.md`；工作包只定义角色、顺序、接口与验收，不重复工单正文。

## 一、Agent 分工与波次（Wave）

| Wave | Agent | 工作包 | 负责栈（工单数） | 前置 |
|---|---|---|---|---|
| W1 | 基建契约官 | [agent-01-infra.md](./agent-01-infra.md) | T-INIT（4） | 无，最先开工 |
| W2 | 考古引擎官 | [agent-02-core-archaeology.md](./agent-02-core-archaeology.md) | T-CORE（9） | W1 完成 |
| W2 | 后端平台官 | [agent-05-backend.md](./agent-05-backend.md) | T-BE（10） | W1 完成（与 W2 考古并行） |
| W3 | 智能体官 | [agent-03-agents-llm.md](./agent-03-agents-llm.md) | T-AG（8） | W2 |
| W3 | 沙箱流水线官 | [agent-04-sandbox-pipeline.md](./agent-04-sandbox-pipeline.md) | T-SB/T-CAP/T-CLI（11） | W2（与 T-AG 接口约定后可并行到 T-SB-05） |
| W4 | 前端控制台官 | [agent-06-frontend.md](./agent-06-frontend.md) | T-FE（11） | W2 后端 OpenAPI 快照冻结 |
| W5 | 生产化官 | [agent-07-prod-devops.md](./agent-07-prod-devops.md) | T-PRD（9） | W3/W4 主体完成 |
| W6 | 基准演示官 | [agent-08-benchmark-demo.md](./agent-08-benchmark-demo.md) | T-BM（6） | M3 达成 |

```text
W1 ──► W2(考古 ∥ 后端) ──► W3(智能体 ∥ 沙箱) ──► W4(前端) ──► W5(生产化) ──► W6(基准/演示)
```

## 二、跨 Agent 接口契约（最容易打架的 5 个点，双方工作包里都有重申）

| 接口 | 提供方 → 消费方 | 冻结物 |
|---|---|---|
| `ExecutionPort` 协议 | 智能体官（定义于 T-AG-06）→ 沙箱官（实装 T-SB-02） | 方法签名 5 个 + 返回类型，写在 `agents/src/revive_agents/ports.py`，沙箱只准实现不得改签名 |
| `EventPort` / 16 类事件 | 沙箱官+智能体官（产生）→ 后端官（落库/转发）→ 前端官（渲染） | `schemas/job-event.schema.json` |
| OpenAPI 快照 | 后端官（T-BE-03 导出）→ 前端官（T-FE-02 生成码）、CLI 官（T-CLI-01） | `schemas/openapi/openapi.json`，变更须同 PR 提交 |
| genome / score / manifest | 考古官、流水线官（产出）→ 后端持久化、前端渲染、基准统计 | `schemas/*.schema.json` 三份 |
| fixture 死项目集 | 考古官（T-CORE-08 建 9 夹具）→ 沙箱/智能体/基准三栈复用 | `tests/fixtures/dead_projects/manifest.json` |

## 三、里程碑归属（验收时按此点名对应的 Agent）

| 里程碑 | 判定命令 | 负责 Agent |
|---|---|---|
| M1 考古可演示 | `revive analyze <fixture> --offline` | 考古官 |
| M2 修复环路 | `revive resurrect --local` 红转绿 | 智能体官 ∥ 沙箱官 ∥ CLI |
| M3 胶囊闭环 | `revive verify out.revive` 退出 0 | 沙箱流水线官 |
| M4 Web 全链路 | 前端冒烟 `smoke-full.spec.ts` | 前端官 ∥ 后端官 |
| M5 生产就绪 | prod compose up + 攻击用例全拒 | 生产化官 |
| M6 基准出数 | `revivebench run --dataset pilot30` 真实 results.jsonl | 基准演示官 |

## 四、给人类协调者的规则

1. **同一文件栈只允许一个 Agent 写**；跨栈并行时，任何一方需要改冻结契约 → 停下来提"契约变更申请"，由你裁定后先改 `schemas/`，再放行。
2. 每个 Agent 交付顺序：工单分支 `task/<ID>` → 自跑验收命令贴输出 → `make lint && make test` 全绿 → 你合并。
3. 接口怀疑漂移时跑契约测试（`tests/contracts/`）裁决，它永远先于口头约定。
4. 冲突仲裁与全局决策以 `docs/tasks/00-总览与派发指南.md §1/§6` 为准。
