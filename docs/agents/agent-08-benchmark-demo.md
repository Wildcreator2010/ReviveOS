# Agent 工作包 08 · 基准演示官（Benchmark & Demo Officer）

- **Wave**：W6（M3 胶囊闭环后即可开工 pilot30；full100 需等 M5 生产化官的 runner 镜像）
- **负责栈**：`docs/tasks/08-ReviveBench与Demo交付.md`（T-BM-01…06），产出物在 `benchmarks/revivebench/` + `docs/demo-runbook.md`
- **你的使命**：用真实实验把产品从"想法"升级为"成果"：四臂对比（裸 Docker/人工/裸 LLM Agent/ReviveOS），每个对外数字可回溯到 `results.jsonl`。**M6 归你。**

## 投喂清单
1. 本文件
2. `docs/tasks/00-总览与派发指南.md`（§6 红线第 5 条：禁止编造数字）
3. `docs/tasks/08-ReviveBench与Demo交付.md`（工单正文）
4. `tests/fixtures/dead_projects/manifest.json`（考古官夹具规范，probe/validate 的样例基线）
5. `research/ReviveOS市场调研报告.md` §三（D08 需求锚点）与 §十（D13/D15 风险：EnvBench 难度基线与"基准会被解决"的时效教训）
6. CLI 完整体（沙箱官交付的 `revive` 命令）

## 执行顺序与要点
| 序 | 工单 | 额外注意 |
|---|---|---|
| 1 | T-BM-01 | death_reasons 必须有机器证据（PyPI 断档时间线等）；候选≠入选 |
| 2 | T-BM-02 | pilot30 逐条 commit 锚定 + license 快照；对照组标注防虚高 |
| 3 | T-BM-03 | **四臂公平性是关键验收**：同硬件同网络同预算；C 臂（裸 LLM）不许偷带考古/行为资产；失败尝试也落行 |
| 4 | T-BM-04 | 报告器只读 results；空数据渲染"未测" |
| 5 | T-BM-05 | 演示三项目从 pilot30 中选有故事的；离线降级包必备 |
| 6 | T-BM-06 | full100 前先给成本预估表（真实单价×预算样本外推），协调者审批后才开跑 |

## 协作界面
- 对沙箱流水线官/智能体官：runner 调用他们的公开 CLI/API，不 hack 内部；发现产品缺陷 → `T-BUG-BM-<n>` 缺陷工单（附 run_id 与复现命令），这些缺陷记录本身也是基准叙事的一部分。
- 对生产化官：nightly 需要 runner 容器镜像与预算护栏（依赖 T-PRD-08）。

## 完成定义
- [ ] 6 条工单验收输出齐；pilot30 四臂至少各完成 ≥8 个项目的真实运行
- [ ] `revivebench report` 生成的对比表全部带 n= 与 run_id，随机抽 3 格可人工复算
- [ ] demo runbook 彩排录屏 + 断网降级演练通过
- [ ] `git log` 里 results 数据与其 run manifest 可一一对应（审计链完整）

## 禁止
- 禁止手填/美化任何指标；禁止为成绩更换数据集难度分层；禁止收录无 OSI 许可证或作者要求删除的仓库。
