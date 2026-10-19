# 08 · ReviveBench 基准与 Demo 交付（前缀 T-BM）

> 铁律（全栈继承）：所有对外数字必须来自真实跑出的 `results.jsonl`，未跑出的格子保持"待测"。基准的可信度=产品的可信度。

### T-BM-01 数据集规格与候选探测工具
- 背景：定义"死项目"样本的元数据标准与采集方法，让 ReviveBench 从第一天起可复跑、可审计。
- 涉及文件：`benchmarks/revivebench/dataset.schema.json`、`benchmarks/revivebench/probe.py`（CLI：`revivebench discover --topic ml --since 2014 --until 2019`）、`tests/unit/bench/test_probe.py`。
- 输入/输出契约：数据集条目固定字段：`{repo, commit_pinned, license(spdx), stars_at_pin, last_activity, death_reasons: [R01..R08], size_mb, has_tests, has_ci, has_dockerfile, python_requires_evidence, notes}`；`probe` 只做 GitHub 搜索 API + 体积/许可证初筛，产出 `candidates.jsonl`（**候选≠入选**）；许可证硬门禁：非 OSI 许可证自动标记 `eligible=false`；每个入选理由必须引用 `death_reasons` 的机器证据（如 PyPI 版本断档），不接受"看起来老了"。
- 验收：`uv run pytest tests/unit/bench/test_probe.py -q` 绿（录制夹具）；对 1 个已知死项目跑 probe 输出合法 JSONL 行。
- 禁止：probe 禁止 clone 内容入库（只采元数据）；禁止把候选直接当数据集发布。
- 依赖：T-CORE-02、T-CORE-05。

### T-BM-02 pilot30 数据集策划与固定
- 背景：30 项目试点集：R01–R08 每类 ≥3 例 + 2 例健康对照 + 难度分层（easy/medium/hard 三档，按证据丰富度）。
- 涉及文件：`benchmarks/revivebench/datasets/pilot30.jsonl`、`benchmarks/revivebench/datasets/PILOT30.md`（每例一行入选理由）、锁文件 `pilot30.lock.json`（repo→commit→tree hash→license 快照）。
- 输入/输出契约：`revivebench validate pilot30.jsonl`：逐条检查 schema、commit 存在性（GitHub API）、许可证与上游当前值一致性；难度分档规则写进 PILOT30.md 附录（证据数量/依赖深度/CI 有无三因子）；对照组的 `expected_outcome=alive` 必须标注（防止"本来就能跑"被算作复生成绩）。
- 验收：`uv run revivebench validate benchmarks/revivebench/datasets/pilot30.jsonl` 退出 0 且打印 30 条 8 类分布统计；人工检查点：抽查 5 条的 commit 锚点真实存在。
- 禁止：数据集禁止收录要求删除的仓库（响应流程写进 PILOT30.md）。
- 依赖：T-BM-01。

### T-BM-03 四臂对比 Runner 框架
- 背景：同一硬件/同一网络条件下对比四种方法：A 裸 Docker（照 README 装）、B 人工修复（记录人时）、C 裸 LLM Agent（无考古无行为验证、同预算上限）、D ReviveOS 全链路。指标：复生成功率、Time-to-Recovery、行为兼容率、人工干预次数、复现性（verify 通过）。
- 涉及文件：`benchmarks/revivebench/runner/{matrix.py,arm_a.py,arm_b_ledger.py,arm_c.py,run_all.py}`、`benchmarks/revivebench/results.schema.json`、`tests/integration/bench/test_runner_pilot.py`。
- 输入/输出契约：每次运行产出 `results/<run_id>.jsonl`（一行一项目：`{run_id, ts, repo, arm, outcome, metrics{...}, environment_fingerprint{docker_version, host_spec, commit_sha_of_reviveos, llm_provider_model_redacted}, artifacts_ref, failures: [{stage, error_signature}]}`）——失败也必须有记录行，禁止静默跳过；arm B 用"人时台账"文件手工登记（格式固定）；run manifest 记录 git sha 与全部输入哈希（同 run_id 可复跑核对）；预算隔离：arm C/D 各自独立 `JOB_BUDGET_USD`，写入 manifest。
- 验收：`uv run revivebench run --dataset pilot30 --arms A,D --limit 3 --dry-run` 输出执行计划不真跑；对 2 个 fixture 项目真跑 A/D 两臂产出合法 results 行并通过 `results.schema.json` 校验。
- 禁止：runner 禁止自动重试后只保留成功记录（每次尝试都落行）；禁止在报告前修改 dataset 难度分层。
- 依赖：T-BM-02、T-CLI-02、T-CAP-03。

### T-BM-04 结果报告生成器（只从真实数据渲染）
- 背景：把 `results/*.jsonl` 渲染成对比表与分布图（README 表格 + HTML 报告）；所有格子标注样本量 n 与失败明细链接。
- 涉及文件：`benchmarks/revivebench/report.py`、`benchmarks/revivebench/templates/report.html.j2`、`tests/unit/bench/test_report.py`。
- 输入/输出契约：`revivebench report --run <id> --out report.html`；任何指标附 `n=`；缺数据的臂/类别显示"未测"而非 0%；报告头部含 run manifest 摘要（代码版本、模型配置脱敏、硬件）；同输入两次渲染 HTML 字节级一致（时间戳用 run 时间非渲染时间）。
- 验收：`uv run pytest tests/unit/bench/test_report.py -q` 绿（夹具 results：全成功/部分失败/空数据三套——空数据必须渲染"未测"）；人工检查：随机抽一格数字与 JSONL 手算一致。
- 禁止：禁止任何手工覆写报告数字的入口。
- 依赖：T-BM-03。

### T-BM-05 演示工程与路演资产
- 背景：M4/M5 后的对外演示：选 3 个"有故事"的 pilot30 项目（科研工具/被广泛依赖的弃疗库/中国开发者熟悉的项目各一），预跑缓存 + 现场直播双方案；输出 Demo Runbook。
- 涉及文件：`docs/demo-runbook.md`、`benchmarks/revivebench/demo/`（预跑胶囊、离线降级包、剧本 checklist）、`apps/web` 的演示只读路由（`/demo` 加载预置事件流回放）。
- 输入/输出契约：现场剧本 10 分钟版：提交→30 秒看到考古面板→切预置直播回放→行为对比页→下载胶囊；网络故障降级路径（直接放回放）；每项演示数据标出处（run_id）。
- 验收：按 runbook 完整走一遍彩排录屏（文件归档在 demo 目录）；断网模式下演示全程可用。
- 禁止：禁止在演示中使用未跑出/未标 run_id 的数字。
- 依赖：T-BM-04、T-FE-11。

### T-BM-06 full100 扩展与持续基准（选配，量产阶段做）
- 背景：pilot30 校准 runner 后扩到 100 项目：分批跑、成本预算闸门（预估+上限审批）、月度重跑机制（跟踪能力曲线变化——CORE-Bench 14 个月被解决是先例）。
- 涉及文件：`benchmarks/revivebench/datasets/full100/`（分片 jsonl + 扩采计划）、`tools/bench_nightly.yml`（GitHub Actions schedule，打自建 runner）、`docs/bench-policy.md`。
- 输入/输出契约：扩采流程复用 T-BM-01/02 工具链（禁止另写采集器）；nightly 只重跑 20% 轮换样本并记录漂移；成本上限 `BENCH_NIGHTLY_BUDGET_USD` 超限自动停并报警。
- 验收：full100 首批 40 项目完成且 validate 通过；一次 nightly 试跑产出增量 results 并进入 T-BM-04 报告。
- 禁止：nightly 禁止使用比发布 run 更强的模型配置（口径一致才可比）。
- 依赖：T-BM-04。
