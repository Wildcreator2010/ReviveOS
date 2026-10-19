# Agent 工作包 04 · 沙箱流水线官（Sandbox & Capsule Officer）

- **Wave**：W3（与智能体官并行；开工第一件事：拉取并确认 `agents/.../ports.py` 接口签名）
- **负责栈**：`docs/tasks/04-沙箱与复生流水线.md`（T-SB-01…06、T-CAP-01…03、T-CLI-01…02），产出物在 `packages/core/sandbox|behavior|capsule` + `cli/` 完整体 + `infra/sandbox/`
- **你的使命**：造"过去的世界"并在其中完成 构建→修复→测试→行为验证→评分→`.revive` 胶囊 的物理执行。**M2 另一半 + M3 全归你。**

## 投喂清单
1. 本文件
2. `docs/tasks/00-总览与派发指南.md`（§6 红线第 3 条：用户代码只准在沙箱跑）
3. `docs/tasks/04-沙箱与复生流水线.md`（工单正文，含栈级安全基线头部）
4. `schemas/revive-manifest.schema.json`、`schemas/resurrection-score.schema.json`、`schemas/job-event.schema.json`（只读）
5. `agents/src/revive_agents/ports.py`（智能体官交付的接口，只读实现）
6. `tests/fixtures/dead_projects/`（考古官夹具）

## 执行顺序与要点
| 序 | 工单 | 额外注意 |
|---|---|---|
| 1 | T-SB-01 | 矩阵是数据表；先人工验证 2–3 行真的能 `docker build` 再铺开 |
| 2 | T-SB-02 | 严格实现 ports.py 签名；孤儿容器清扫测试必须做（Windows Docker Desktop 偶发僵尸容器，写进文档） |
| 3 | T-SB-03 | 版本回退只准向旧不准向新——违反即触发协调者红线 |
| 4 | T-SB-04 ∥ 06 | runner 与指纹采集互不依赖可并行；指纹的"原版先跑采集基线"顺序不能反 |
| 5 | T-SB-05 | M2 判定工单：fake-LLM 回放 golden diff，红→绿全录 |
| 6 | T-CAP-01 → 02 → 03 | 公式唯一实现；双构建字节一致；`revive verify` 篡改检测 = M3 |
| 7 | T-CLI-02 → 01 | 先 local 全链路，再 server 瘦客户端；server 联调等后端 T-BE-05 就绪 |

## 接口承诺
- 向智能体官：ExecutionPort 实现 + 每步骤按 `job-event` 契约发事件；
- 向后端官（worker 装配用）：`local_pipeline` 的可复用工厂函数 `assemble_pipeline(config, ports)`；
- 向前端/基准：胶囊 manifest 与 score 全部来自契约实例，无任何私有格式。

## 完成定义
- [ ] 11 条工单验收输出齐（含 4 条 `requires_docker` 真机跑）
- [ ] M2 录屏：`revive resurrect --local` 对 `collections-abc` 红→绿；M3 录屏：`revive verify` 通过 + 篡改 1 字节后拒绝
- [ ] `docker ps` 无 `revive-sbx-*` 残留；`make lint && make test` 绿

## 禁止
- 禁止宿主机直接跑任何目标代码或其依赖安装；禁止为通过率调高资源上限而不申报；禁止 verify 里联网重建还标 `reproducibility.verified=true`。
