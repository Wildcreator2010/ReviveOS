# Agent 工作包 07 · 生产化官（Production Hardening Officer）

- **Wave**：W5（W3/W4 主体功能合入后开工）
- **负责栈**：`docs/tasks/07-生产化安全与部署.md`（T-PRD-01…09），产出物在 `infra/`、`tools/`、`docs/runbook-*` 及跨栈安全接线
- **你的使命**：把"功能齐"变成"敢上线"：沙箱加固、SSRF、密钥治理、观测、prod compose、备份演练、发布供应链、故障演练。**M5 归你。**

## 投喂清单
1. 本文件
2. `docs/tasks/00-总览与派发指南.md`（§1 部署/观测决策、§6 全局红线）
3. `docs/tasks/07-生产化安全与部署.md`（工单正文，含威胁模型头部）
4. `docs/tasks/04-沙箱与复生流水线.md` 头部安全基线（你要在其上叠加而不是重做）
5. 现有代码 HEAD（全部只读；你改动跨栈文件时须与原工单负责人分支协调）

## 执行顺序与要点
| 序 | 工单 | 额外注意 |
|---|---|---|
| 1 | T-PRD-01 | 4 个逃逸用例是硬验收；digest 锁与 T-PRD-08 的锁文件同一来源 |
| 2 | T-PRD-02 | netguard 要接进**所有**出网点（fetcher/pypi client/probe）——发现旁路就开缺陷单给对应栈 |
| 3 | T-PRD-03 | 启动自检宁可过严；轮转手册可先薄后厚 |
| 4 | T-PRD-04 ∥ 05 | trace 贯通 API→worker→agents→sandbox 四段是验收标准；脱敏正则与 CI 扫描同源 |
| 5 | T-PRD-06 | prod compose 首次全栈拉起 = M5 主体验收；caddy 本地自签也要走 HTTPS |
| 6 | T-PRD-07 → 09 | 恢复演练真实执行拿到 RPO/RTO 实测数（禁止写理论值）；三故障剧本逐个演 |
| 7 | T-PRD-08 | trivy/SBOM/digest 三件套进 release 流水线 |

## 协作界面
- 对后端官/沙箱官：你是"攻击者+审计者"角色——发现漏洞提缺陷工单（格式：`T-BUG-PRD-<n>` 附复现脚本），不直接改他们核心逻辑，除非协调者授权。
- 对基准官：其 full100 nightly 依赖你的 runner 镜像与预算护栏先行就绪。

## 完成定义
- [ ] 9 条工单验收输出齐（含逃逸、SSRF、恢复演练三场真机）
- [ ] M5 录屏：prod compose 全新机器（干净 Docker Desktop 环境）一键起 → 全链路 job → 攻击用例全拒
- [ ] runbook 四件套入库：deploy / secrets / restore / incidents

## 禁止
- 禁止为"先跑通"关闭安全配置再忘记恢复（所有豁免必须 env 开关 + 启动告警）；禁止编造 RPO/RTO/压测数字。
