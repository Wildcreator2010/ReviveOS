# Agent 工作包 01 · 基建契约官（Infra & Contract Officer）

- **Wave**：W1（全局最先，其他所有 Agent 等你）
- **负责栈**：`docs/tasks/01-基础设施与契约.md`（T-INIT-01…04）
- **你的使命**：把仓库骨架、四大 JSON Schema 契约、CI 红线闸门、Windows+Docker 开发环境一次性立起来。契约质量决定后面 7 个 Agent 会不会打架。

## 投喂清单（派发时一并给到该 Agent）
1. `docs/agents/agent-01-infra.md`（本文件）
2. `docs/tasks/00-总览与派发指南.md`（§1 决策表、§4 契约表、§6 红线、§7 环境变量必须逐字遵守）
3. `docs/tasks/01-基础设施与契约.md`（工单正文）
4. `research/ReviveOS市场调研报告.md` 仅 §十一台账中 D08/D13/D16 三条（了解品类难度，非必读）

## 执行顺序与要点
| 序 | 工单 | 你额外要注意的 |
|---|---|---|
| 1 | T-INIT-01 | uv workspace 四包 + Makefile 目标名不得自创 |
| 2 | T-INIT-02 | **最关键工单**：写 schema 时同时写正反例夹具；`job-event` 15 类 type 一字不差；score 权重 20/20/15/15/20/10 写进 `x-weights`；拿不准的字段宁缺毋滥（additionalProperties:false） |
| 3 | T-INIT-03 | `check_global_rules.py` 的密钥正则、修复上限常量扫描都要做"故意违反→必须红"的自证测试 |
| 4 | T-INIT-04 | WSL2 路径挂载坑写实机经验；compose 三件套 + 桶初始化 |

## 完成定义（你对协调者出示的全部证据）
- [ ] 4 条工单各自「验收」命令的真实输出贴文
- [ ] `make dev` 后 `docker compose ps` 三容器 healthy
- [ ] `uv run pytest tests/contracts -q` 全绿
- [ ] `tools/check_global_rules.py` 的故意违规自测（红→还原→绿）录屏或输出
- [ ] 提交合入 main，打 tag `contracts-frozen`

## 交接给下游的承诺（写进 PR 描述）
- `schemas/` 自此冻结：任何 Agent 想改字段须走"契约变更申请"，不得直接改文件。
- 你产出的 CI 绿基线是后续所有 Agent 合并的前提。

## 禁止
- 禁止实现任何业务逻辑（哪怕"顺手写个 fetcher"）；你的产物只有骨架/契约/闸门/环境。
