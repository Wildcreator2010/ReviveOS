# Agent 工作包 02 · 考古引擎官（Core & Archaeology Officer）

- **Wave**：W2（与后端平台官并行，互不触碰对方文件）
- **负责栈**：`docs/tasks/02-核心域与考古引擎.md`（T-CORE-01…09），产出物全部在 `packages/core/` + `tests/` + CLI 的 `analyze`
- **你的使命**：实现"Evidence First, AI Second"的软件考古引擎——不调用任何 LLM 也能从仓库历史证据推断出可信的环境基因。**M1 里程碑归你。**

## 投喂清单
1. 本文件
2. `docs/tasks/00-总览与派发指南.md`（§4 契约表、§6 红线）
3. `docs/tasks/02-核心域与考古引擎.md`（工单正文）
4. `schemas/environment-genome.schema.json`、`schemas/job-event.schema.json`（tag `contracts-frozen` 版本，只读）

## 执行顺序与要点
| 序 | 工单 | 额外注意 |
|---|---|---|
| 1 | T-CORE-01 | 模型与 schema 的 diff 测试必须 CI 常驻 |
| 2 | T-CORE-08（提前穿插） | 夹具是 C03–C06 验收的前置；先做 `py27-flask/three-era-deps/healthy-baseline` 三个最小集 |
| 3 | T-CORE-02 | github.com 白名单 + token 不落 URL/git config |
| 4 | T-CORE-03 ∥ 04 ∥ 05 | 可内部并行；extractor 每类 ≥3 夹具；timeline 用固定 GIT_AUTHOR_DATE 保可复现；pypi client 全 mock 测试 |
| 5 | T-CORE-06 | **规则表即产品灵魂**：优先级顺序不得自行调整；每条结论 ≥1 证据、低置信必带冲突 note |
| 6 | T-CORE-07 | signature 命名当合同对待，定稿后不许改 |
| 7 | T-CORE-09 | `revive analyze` 退出码 0/2/3 三态齐全 = M1 达成 |

## 接口承诺（向下游交付）
- `revive_core` 公开 API：`fetch_repo / extract_evidence / build_timeline / infer_genome / classify / PypiClient`——沙箱官（T-SB-03 用 PypiClient）、智能体官（T-AG-03/04 消费 genome 与 ErrorFact）、后端官（T-BE-09 持久化 EvidenceItem）都以你的签名为准；如需变更走契约申请。
- `tests/fixtures/dead_projects/manifest.json` 是全局夹具台账，沙箱/智能体/基准三栈直接引用。

## 完成定义
- [ ] 9 条工单验收输出齐
- [ ] `revive analyze py27-flask --offline` 终端实拍（M1）
- [ ] `infer_genome` 对 9 夹具全通过预期断言；`make lint && make test` 绿
- [ ] 零 LLM import 出现在 `packages/core/`（grep 自证）

## 禁止
- 禁止在 core 里 import `revive_agents` 或任何 LLM SDK；禁止为了跑通夹具而硬编码夹具名特例。
