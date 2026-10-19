# Agent 工作包 03 · 智能体官（Agents & LLM Officer）

- **Wave**：W3（与沙箱流水线官并行，靠 ExecutionPort/EventPort 接口文件对接）
- **负责栈**：`docs/tasks/03-智能体与模型接入.md`（T-AG-01…08），产出物全部在 `agents/`
- **你的使命**：搭可插拔 LLM Provider（openai/anthropic/custom 三格式全支持，用户自带密钥）+ 三个 Agent 节点 + LangGraph Supervisor 主图。**你是 M2 的一半。**

## 投喂清单
1. 本文件
2. `docs/tasks/00-总览与派发指南.md`（§1 模型接入决策、§6 红线第 7 条修复上限）
3. `docs/tasks/03-智能体与模型接入.md`（工单正文）
4. `schemas/environment-genome.schema.json`、`schemas/job-event.schema.json`（只读）
5. `packages/core/src/revive_core/models/`（考古官已交付的域模型，只读引用）

## 执行顺序与要点
| 序 | 工单 | 额外注意 |
|---|---|---|
| 1 | T-AG-01 | 三适配器 + fake 回放 Provider 是全部下游测试的地基；custom=OpenAI 兼容 base_url 路径必须独立测试 |
| 2 | T-AG-02 | 提示词全部 `prompts/<name>/vN.md` 版本化，评审时只给 diff 不给口头 |
| 3 | T-AG-03 | 幻觉拦截测试是重点：引用不存在证据 id 的补强必须被丢弃 |
| 4 | T-AG-04 | 5/10/300 上限在代码常量强制并接入 CI 扫描；只产 diff 不落盘 |
| 5 | T-AG-06 | **先写 `ports.py`（ExecutionPort/EventPort 协议）并 PR 给沙箱官**，双方签字后再各自实现——这是 W3 并行的解耦点 |
| 6 | T-AG-05 → 07 → 08 | 行为计划预算 25 用例；成本护栏默认 $2/job；记忆库缺 embedding 时必须可降级为空转不阻塞主链 |

## 接口承诺
- `agents/src/revive_agents/ports.py`：`ExecutionPort{ensure_env/run/apply_patch/snapshot_ws/restore_ws}`、`EventPort{emit(event)}`——签名冻结，沙箱官实现、后端官消费。
- `supervisor.build_graph(deps) -> CompiledGraph`：CLI 本地模式与后端 worker 都会直接实例化它；依赖全注入、无全局单例。

## 完成定义
- [ ] 8 条工单验收输出齐
- [ ] fake-LLM 下 supervisor 成功/失败/预算耗尽三条剧本事件序列全对（T-AG-06 验收）
- [ ] `grep -r "sk-" agents/ src` 无密钥；`make lint && make test` 绿
- [ ] 与沙箱官的 ports.py 合对测试（双方 PR 互链）

## 禁止
- 禁止节点内直接执行/修改文件（那是沙箱的事）；禁止绕过 factory 直接 import SDK；禁止任何默认模型名硬编码进业务代码。
