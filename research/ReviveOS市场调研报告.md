# ReviveOS 所在品类市场调研报告
## ——软件运行时复生与可复现基础设施（含邻近的遗留软件现代化 / 开源供应链维护 / 可复现计算市场）

> 报告日期：2026-10-06（所有链接访问日期均为 2026-10-06）
> 调研执行：基于公开网络来源的系统性检索（WebSearch，多轮交叉验证）
> 范围：全球为主，中国单列；历史数据 2020–2026，预测数据 2026–2032
> 数据编号 D01–D26 对应文末《数据台账》；正文所有结论仅引用台账内数据点
> 诚实声明：**"软件运行时复生"作为独立品类不存在任何第三方市场规模统计**。本报告使用四类邻近口径做代理测量（见 D01–D05 与假设清单 A2）。凡无法核验的数字一律不进入正文，全部列入《数据缺口清单》。

---

# 一、执行摘要

1. **"死而不僵"的软件规模是量级级别的真实痛点，不是营销话术。** PyPI 全量 415,151 个包中被学术方法判定为非活跃的有 103,733 个（推算约 25%）[D08]；Sonatype 追踪的约 120 万个开源项目中仅 11% 处于积极维护 [D25]；Synopsys 对 1,067 个商业代码库的审计显示 96% 含开源组件、开源代码占其总量 77%，49% 的代码库含有两年内无任何开发活动的开源件 [D06][D26]。——即"源码还在、运行条件已死"的标的池巨大且持续增长。

2. **ReviveOS 的直接品类无市场统计，但四个邻近市场均被咨询机构量化且增速 5.8%–14.6%：** 应用现代化服务 2025 年 $226.7 亿→2031 年 $514.5 亿（CAGR 14.6%）[D01]；IT 现代化服务 2025 年 $339 亿→2032 年 $721 亿（CAGR 11.38%，口径与前者不同，冲突并列见 §2.3）[D03]；大型机现代化 2025 年 $83.9 亿→2030 年 $133.4 亿 [D02]；中国全口径软件业务收入 2025 年 154,831 亿元、同比 +13.2%（其中与品类最接近的"基础软件"细分 2,146 亿元、+11.1%）[D05]。

3. **需求侧最强的付费证据来自金融与科研两个场景。** 金融业：Micro Focus 对 49 国 1,104 名从业者的调查显示全球每日在用 COBOL 代码 775–8,500 亿行（各机构估计冲突显著，已并列呈现 [D10][D11]），64% 的 COBOL 依赖组织倾向现代化而非重写 [D10]；Cognition（Devin）企业端年化收入 16 个月内从 $3,700 万增至约 $9 亿，其标杆案例正是用 AI 把奔驰 8 个月的现代化项目压缩到 8 天 [D21]——证明"为让旧软件重新可用/可迁而付费"的意愿真实且强劲。科研界：INRIA/CNRS "十年复现挑战" 35 名科学家中大量无法重跑自己十年前的代码 [D12]，普林斯顿 CORE-Bench 显示 2024 年 AI Agent 复现论文代码成功率仅约 21% [D14]。

4. **竞争格局：正面品类尚无霸主，但"方法论邻居"已有重兵。** 大厂现代化阵营（AWS Transform 已 GA 且开箱支持 Python/Java/Node 升级 [D20]）走"改代码"路线；科研胶囊阵营（IEEE Code Ocean，正向捕获式）[D14 注]；保存阵营（Internet Archive 已在浏览器中模拟运行 25 万+ 件软件 [D17]；Software Heritage 保存 100 亿+ 唯一源文件 [D18]）；**2026 年 9 月新出现的 ScienceIDE（AItonomy 基金会 + PhAI Labs + 阿里 Qwen + 20 余所高校）已把 27 个上游科学代码库转成 64 个可执行验证环境、生成 2,812 个任务 [D16]——其"仓库→可执行环境→数值验证"与 ReviveOS 创新点一/二方法论高度同构，是当前最需要正面回应的竞品**。集中度：无任一玩家覆盖"逆向考古 + 行为保持修复 + 长期保存格式"全链路，品类窗口仍开。

5. **技术可行性风险已被第三方基准定量证实：环境自动重建极难。** JetBrains EnvBench（2025）：最先进 LLM Agent 在 329 个有真实配置困难的 Python 仓库上仅能成功配置 6.69%（JVM 29.47%）[D13]。但先行指标同样明确：2026 年 5 月普林斯顿宣布 CORE-Bench 被 Opus 4.5 + Claude Code 脚手架"解决"（准确率提升至约 95%）[D15]——前沿 Agent 能力曲线正在快速吃掉"复现"任务，ReviveOS 的护城河必须放在**数据资产（历史证据库）与保存格式标准**上，而不是 Agent 编排本身。

6. **监管正在把"软件长期可追溯"变成强制合规需求，构成品类冷启动的政策东风。** 欧盟 CRA（Regulation (EU) 2024/2847）：漏洞/事件报告义务已于 2026-09-11 生效，SBOM（机器可读软件物料清单）、≥5 年支持期、更新不得撤回等义务将于 2027-12-11 全面适用，覆盖所有投放欧盟市场的软件（含非欧盟厂商）[D23]。这与 `.revive` 胶囊中 sbom/、provenance.json 的字段设计直接同构。

7. **资本信号：相邻赛道热、"复生"细分零融资记录。** AI 遗留现代化创业公司 2026 年上半年连续获得融资（Kodesage 种子 $660 万 [D22]；8090 Labs 由 Salesforce Ventures 领投 $1.35 亿 [D22]）；Devin 收入 20 倍增长 [D21]。检索未发现任何"运行时复生"细分的对标融资——品类定义权仍待抢。

---

# 二、市场规模与增速

## 2.1 历史数据（实测/审计口径）

| 编号 | 口径 | 数值 | 年份 |
|---|---|---|---|
| D05 | 中国软件业务收入（全口径，工信部官统） | 154,831 亿元人民币，+13.2% | 2025 |
| D05 | 其中：基础软件产品收入 | 2,146 亿元，+11.1% | 2025 |
| D05 | 其中：工业软件产品收入 | 3,330 亿元，+9.7% | 2025 |
| D06 | 商业代码库开源渗透率（Synopsys 审计 1,067 库） | 96% 含开源；开源占代码量 77% | 2023 审计，2024-01 发布 |
| D17 | Internet Archive 浏览器内可模拟运行软件件数 | >250,000 件 | 2023-09 |
| D18 | Software Heritage 源码存档规模 | 唯一源文件 >100 亿、commit >20 亿、项目 >1.6 亿、约 1 PB | 2022 中 |
| D19 | PyPI 项目总数 | >654,000 | 2025 |

## 2.2 预测数据（列明机构与假设）

| 编号 | 机构 | 口径 | 基期 | 终期 | CAGR | 机构假设前提 |
|---|---|---|---|---|---|---|
| D01 | MarketsandMarkets | 应用现代化**服务**（云迁移/再平台/后期现代化） | 2025: $226.7 亿 | 2031: $514.5 亿 | 14.6% | 数字化转型投入、云采用率提升为驱动；亚太最快 |
| D02 | MarketsandMarkets | 大型机现代化（软件+服务） | 2025: $83.9 亿 | 2030: $133.4 亿 | 9.7% | 软件细分增速高于服务 |
| D03 | QYResearch | IT 现代化**服务**（端到端交付口径） | 2025: $339 亿 | 2032: $721 亿 | 11.38%（2026–2032） | 竞争格局高度分散、无单一主导厂商（该机构原文结论） |
| D04 | 恒州诚思 YHResearch | 遗留系统现代化（按收入，含产品+服务） | 2024: ≈545.9 亿元(RMB) | 2031: ≈827.8 亿元(RMB) | 5.8% | 再托管/再平台/重架构三类并表 |
| D21→外推 | —（不入账） | Devin 类 AI 现代化企业收入 | 2025-05: $0.37 亿 | 2026-09: ≈$9 亿年化 | —（实测非预测，公司自披露） | 未经审计，见假设 A5 |

## 2.3 来源冲突的并列呈现（规则 5）

**冲突一：现代化市场规模差 1.5 倍（D01 vs D03）。** M&M（2025: $227 亿）与 QYResearch（2025: $339 亿）差异原因是统计口径不同：前者限定"应用现代化服务"（应用层级），后者为"IT 现代化服务"（含基础设施、数据、安全现代化）。两者均为服务型收入口径，不含纯软件产品。取任一值都必须注明口径，本报告正文引用时均带口径标签。

**冲突二：遗留系统现代化增速差（D04 vs D01，5.8% vs 14.6%）。** YH 口径按"遗留系统现代化"整体收入（含大量传统集成商交付，基数含日元/人民币区服务外包），M&M 仅计新兴应用现代化服务。增速差反映的是"人力外包式现代化"与"工具/云式现代化"两个子结构——ReviveOS 属于后者，引用 D01/D03 增速更贴切。

**冲突三：COBOL 代码存量三个数量级打架（D10 vs D11 vs 其他）。** Reuters-2017/媒体口径 2,200 亿行 [D11]；Micro Focus 2022 调查口径 7,750–85,000 亿行 [D10]。差异原因：估算机构、年份、"活跃生产行 vs 全部存量行"定义、以及是否含复制代码均不同。**不得取平均**；本报告仅用"数千亿行级、各家口径互斥"的定性表述 + 两条台账。另有一个广为流传的 Gartner 数据（美企平均 245 个遗留系统、年成本 $1.5 万亿）仅能检索到无一手出处的转述页，**已整体剔除并列入数据缺口 G01**。

## 2.4 直接品类规模判断

"运行时复生"（Source Alive / Runtime Dead 软件的重建-验证-保存）无任何第三方 TAM/SAM 统计。结合假设清单 A2 的代理逻辑，可辩护的表述是：**其潜在需求池 ≥ D01 应用现代化服务的委托方集合**（凡有遗留系统的企业理论上都先需要"知道哪些软件已死/将死"），以及 D08/D25 所量化的高达 25% / 89% 的废弃组件存量；**但已实现的付费市场趋近于零**——这既是空白，也是"品类教育成本由先行者承担"的风险（见 §9）。

---

# 三、需求侧：客户分层与支付意愿

## 3.1 分层与证据链

| 层级 | 需求场景 | 支付意愿证据 | 台账 |
|---|---|---|---|
| L1 金融机构 | COBOL/大型机存量系统人员断代，现代化预算已存在 | 64% 组织选现代化而非重写（Micro Focus 调查，49 国样本）；AI 现代化乙方（Devin）企业客户含英伟达、花旗、奔驰、多家美国银行，企业用量 2026 年以来增 10 倍+ | D10 / D21 |
| L2 科研机构与出版方 | 论文代码十年后无法复现；期刊被要求提供可复现载体 | IEEE Xplore 官方集成 Code Ocean "一键复现"胶囊；《Applied Soft Computing》等期刊发放可复现徽章（正向捕获式付费的先例） | D14/D24（渠道证据）|
| L3 出海软件制造商（EU CRA 合规） | 2026-09-11 起漏洞报告义务生效；2027-12-11 起 SBOM+支持期强制 | 合规是法定义务、预算为刚性；义务覆盖含非欧盟厂商 | D23 |
| L4 开源生态基金会 | 弃用软件无接管机制：89.5% 用户希望收到弃用通知、仅 8.7% 弃用公告给了替代方案 | 付费方为基金会/政府科研经费（如 France 2030 对 SWH 的支持），非 C 端 | D08/D09 |
| L5 工业企业（CAD/仿真/工控） | 老专家离职、软件无人能跑 | **数据不足**：本轮未检索到工业企业为此场景单独付费的可核验案例（见缺口 G07） | — |

## 3.2 需求侧规模锚点（量化）

- 标的池：PyPI 非活跃包 103,733 个（≈25%）[D08]；全开源项目仅 11% 被积极维护 [D25]；商业代码库中 49% 含有两年内无开发活动的开源件、91% 含落后 ≥10 个版本的组件 [D26]。
- 需求趋势：开源组件下载增速从 2021 年 73% 放缓至 2023 年 33%，而供给（项目数）仍 +29%/年 [D25]——**供给过剩 + 维护收缩的剪刀差正是"死软件存量"持续膨胀的直接机制**。
- 科研侧的实证灾难：十年复现挑战 43 项投稿中仅 28 项产出复现报告，且大量成功案例依赖虚拟机/模拟器/软盘等手工考古 [D12]；AI Agent 自动复现成功率 2024 年仅约 21% [D14]。

## 3.3 客户为什么不买现有替代品（需求缺口论证）

Code Ocean 类方案要求**作者在软件还活着时主动打包**（正向捕获），对 2010–2018 年间已死的软件无能为力 [D24/D14 注]；Internet Archive 只保存二进制并靠模拟器运行，不做源码级重建与行为验证 [D17]；SWH 只存源码 [D18]；AWS Transform/OpenRewrite 路线的前提是**软件还在生产环境活着且有测试基线** [D20]。四类现有方案覆盖不到的交集 = ReviveOS 定义的目标客群。

---

# 四、供给侧与竞争格局

## 4.1 阵营划分与份额/集中度判断

**无任何机构发布过本品类的份额数据**（原因：品类未被统计机构识别——见缺口 G02）。据本轮检索，按方法论分四个阵营：

| 阵营 | 玩家 | 关键事实 | 台账 |
|---|---|---|---|
| A. AI 改造派（把死代码改活=现代化） | AWS Transform（已 GA，开箱支持 Python/Java/Node 升级；其 Mainframe Modernization 托管运行时 2025-11-07 起停收新客户）；GitHub Copilot Modernization Agent（底层用 OpenRewrite）；Cognition Devin（收入 20 倍，奔驰 8 月→8 天）；Thoughtworks AI/works（behavior-first 现代化）；创业公司 Kodesage（$6.6M）、8090 Labs（$135M） | 拥挤、资本密集；**均不处理"无测试基线、作者失联"的软件** | D20/D21/D22 |
| B. 正向捕获复现派（胶囊发明者） | IEEE Code Ocean（胶囊+一键复现+期刊徽章）；ReproZip（重放打包） | 心智已被占用：`.revive` 必然被拿来对比；依赖作者配合，无法逆向 | D24/D14 |
| C. 科学 Agent 环境派（2026 新物种，最大方法论威胁） | ScienceIDE（AItonomy + PhAI Labs + Qwen + 20 余所高校）：27 库/64 环境/2,812 任务，验证采用数值容差+不变量 | 与 ReviveOS 创新点一、二同构；目的不同（造训练数据 vs 软件延续）；面向"活着且有专家认领"的上游科学代码 | D16 |
| D. 保存/考古派（遗产基础设施） | Internet Archive（Emularity，25 万件浏览器可跑）；Software Heritage（100 亿文件存档，UNESCO/Inria 背书）；GitHub Arctic Code Vault（千年胶片） | 保存"尸骸"而非"复活"；均无 AI 修复与行为等价验证能力 | D17/D18 |

**集中度结论**：四阵营 CR4 无定义（品类未立）；在"逆向考古 × 行为保持修复 × 可携带保存格式"三要素交集上，份额事实上为 0%，无先行者取得结构性卡位。ScienceIDE 是唯一已具备要素①②部分能力且资源雄厚的玩家，但它公开的目的函数是训练科学 Agent [D16]，不做保存格式——这是当前格局里 ReviveOS 最重要的一条差异化时间窗。

## 4.2 竞品表勘误（对原方案 §2/§13 的修正）

- 原方案竞品表中的 "Perslis"：全网检索无此产品，**疑似虚构，必须删除**（已在上一轮沟通说明）。
- 原表遗漏：IEEE Code Ocean、ScienceIDE、EnvBench/CORE-Bench（学术基准）、ReproZip、Internet Archive Emularity。补齐后差异化叙事才能经受评委质询。

---

# 五、产业链上下游

```text
上游（数据与标的供给）                    中游（工具/服务层）              下游（买单方）
──────────────────────                ──────────────────          ─────────────
代码托管：GitHub/GitLab 快照被          改造派：AWS Transform、        L1 金融/政企遗留栈
SWH 爬取存档 [D18]                     OpenRewrite/Moderne [D20]      （D10/D21 证据）
包仓库：PyPI >65.4 万项目 [D19]、       捕获派：Code Ocean、ReproZip   L2 科研/出版 [D24]
  Maven、npm（弃用池 [D08][D25]）      保存派：IA Emularity、SWH      L3 CRA 合规出海厂商 [D23]
历史运行时镜像源：Ubuntu/Debian          基准设施：EnvBench、           L4 开源基金会 [D09]
  旧版 ISO、Docker Hub 旧 tag           CORE-Bench、SWE-bench         L5 工业软件（数据不足 G07）
旧 CI 记录 / Issue / 论文附录
AI 底座：OpenAI/Anthropic/Qwen 等
  （ReviveOS 方案为可插拔，不构成
  自研模型依赖 [D16 注：ScienceIDE
  同样不自研底层模型，只训 IDE 系列]）
```

- 上游议价力弱（数据公开），但存在**法律灰区**：旧版私有软件镜像的再分发受版权限制（十年挑战参与者对下载旧 VB 的合法性明确表示存疑 [D12]；IA 依赖 DMCA 档案豁免 [D17 背景]）。ReviveOS 商用需前置 SPDX 许可证扫描与豁免边界评估（方案已含 Syft/Grype，建议增加 license 维度）。
- 下游渠道的既有锚点：IEEE Xplore 证明"论文页内嵌可复现胶囊"是被学术出版接受的分发形态 [D24]——ReviveHub 可类比接入期刊/会议投稿链路。

# 六、价格与商业模式

可核验的价格事实有限（多数厂商不公开价目表，见缺口 G04）：
- Devin：企业订阅/按用量计（公司未公开单价，收入端证据 D21）；
- AWS Transform：并入云消费计费；其托管运行时停止新客户开通（D20）本身是产品毛利模型失效的信号，值得引以为戒——**纯托管运行时重资产路线大厂也在撤退**；
- Code Ocean：机构订阅 + 期刊合作（定价未公开，G04）；
- OpenRewrite：开源引擎 + Moderne 商业化（模式确证，费率未公开，G04）。
可行的商业模型推断（假设 A6）：ReviveOS 短期最匹配的变现是 **L3 合规驱动的项目制/订阅制**（CRA 2027-12 大限前有明确预算时钟 [D23]）+ **L2 科研复现服务**（按胶囊计费，对标 Code Ocean 期刊分成模式），而非 L1 正面撞 AWS/Cognition 资本火力。

# 七、渠道结构

1. 云市场/大厂直销（A 阵营主渠道，D20/D21）；
2. 学术出版嵌入式分发（IEEE Xplore "Run on Code Ocean" 按钮是先例，D24）；
3. 竞赛/基准声量渠道：EnvBench、CORE-Bench 证明"公开基准+论文"是本品类获取研究界信任的标准路径（D13/D14）；ReviveBench 应复用 EnvBench 仓库子集以保持可比性；
4. 政府/基金会背书渠道：SWH 走 UNESCO/Inria 路线 [D18]，适合 ReviveHub 长期化。
中国渠道补充：工信部官统显示基础软件/工业软件为政策重点细分（D05），信创替代工程本身就是"读懂旧系统"需求的放大器（定性，规模数据见缺口 G05）。

# 八、政策与监管

- **欧盟 CRA（最强驱动，台账 D23，A 级）**：Regulation (EU) 2024/2847，2024-10-23 通过、2024-12-10 生效；Art.14 漏洞/事件报告义务 2026-09-11 已适用（24h 预警 / 72h 通报 / 修复后 14d 终报）；2027-12-11 起 SBOM（Annex I，机器可读、持续更新）、≥5 年支持期、更新不得撤回等全面适用；对开源软件管理人（steward）自 2027-12-11 适用较轻义务。**含义**：`.revive` 的 sbom/ + provenance.json 字段 = 现成的合规交付载体；"长期可复现"从工程洁癖升级为法定义务。
- **美国**：软件保存依赖 DMCA 档案豁免（IA 先例 [D17 背景]）；行政层面 AI 现代化进入联邦采购（Devin 客户含美国陆军/海军/NASA，C 级 D21）。
- **中国**：官方统计口径单列"基础软件产品收入 2,146 亿元 (+11.1%)"（D05），品类归属上 ReviveOS 可对标基础软件/软件供应链安全政策叙事（信息安全和关键软件自主可控为大方向，具体文件条款本轮未逐一定位，见缺口 G06）。

# 九、技术趋势

1. **Agent 化改造能力快速商品化**：EnvBench 2025-03 显示 LLM 配环境仅 6.69%/29.47% 成功 [D13]；14 个月后 CORE-Bench 被 Opus 4.5 + 新脚手架宣布"解决"（≈95%）[D15]。**趋势斜率极陡——任何以"Agent 会修代码"为核心的卖点都在快速贬值**，护城河必须转移到：私有历史证据语料、行为指纹库、保存格式的网络效应。
2. **改造引擎收敛到确定性中间层**：AWS 与 GitHub 的产品都站在 OpenRewrite 这类确定性转换引擎上做编排（来源为咨询博客，C 级，D20 注）。ReviveOS 的 "Evidence First, AI Second" 与此同流，可引用为设计合法性佐证。
3. **可复现单元格式标准化运动**：胶囊（Code Ocean/D24）→ 存档标识（SWHID/D18）→ SBOM 法定格式（CRA/D23），三股力量汇向"软件必须携带可验证身世"。`.revive` 开源规范化的时机是顺势的。
4. **AI for Science 基建反哺**：ScienceIDE 把科学软件转为可学习环境 [D16]，客观上为 ReviveOS 准备了同一批标的的"预解剖"数据（环境定义、验收标准）——既是竞品，也是最理想的潜在数据合作方/上游。

# 十、风险与先行指标

| 风险 | 证据 | 等级 |
|---|---|---|
| 技术可行性：环境重建成功率个位数% [D13]，MVP 若对外承诺"通用复生"会翻车 | 高 |
| 能力曲线吞并：前沿模型 14 个月解决一个复现基准 [D15]，纯 Agent 编排无护城河 | 高 |
| 品类教育成本：无第三方 TAM（G02），投资人/评委第一问必然"市场多大"——用代理口径 + 缺口诚实回答 | 中 |
| 巨头顺手覆盖：AWS Transform Custom 已支持 Python 升级 [D20]，若其加入"历史环境重建"即碾压 | 中 |
| 版权红线：旧运行时镜像/私有软件历史版本的再分发合法性（D12 参与者自述存疑） | 中 |
| 大厂撤退先例：AWS 托管运行时停收新客户（D20）——重资产托管模式毛利不成立 | 低（模式警示） |

**先行指标（建议持续监测）**：① EnvBench/CORE-Bench 榜首成绩刷新速率（能力商品化速度）；② ScienceIDE 仓库是否出现"preservation/archive"关键词（竞品转向信号）；③ CRA 2027-12 大限前的 SBOM 工具采购公告；④ PyPI 非活跃包比率年度变化（D08 方法可复跑）；⑤ Devin 类公司企业用量增速（预算流向）。

---

# 十一、数据台账

访问日期统一为 2026-10-06。等级定义：A=官方统计/监管/审计披露；B=知名咨询/券商研报或学术预印本（一手机构数据）；C=引用了原始来源的权威/行业媒体转述；D=禁用（自媒体、无日期、内容农场——本报告正文未引用任何 D 级）。

| 编号 | 数据点 | 数值 | 口径 | 地域 | 数据年份 | 发布机构 | 发布日期 | 等级 | 来源链接 |
|---|---|---|---|---|---|---|---|---|---|
| D01 | 应用现代化服务市场 | $226.7亿(2025)→$514.5亿(2031), CAGR 14.6% | 服务收入 | 全球 | 预测 | MarketsandMarkets | 2025-10-29 (PRNewswire) | B | https://www.marketsandmarkets.com/Market-Reports/application-modernization-services-market-149625724.html |
| D02 | 大型机现代化市场 | $83.9亿(2025)→$133.4亿(2030), CAGR 9.7% | 软件+服务 | 全球 | 预测 | MarketsandMarkets | 2025-08-21 | B | https://www.marketsandmarkets.com/PressReleases/mainframe-modernization.asp |
| D03 | IT 现代化服务市场 | $339亿(2025)→$371亿(2026E)→$721亿(2032), CAGR 11.38%(26-32) | 端到端 IT 服务收入 | 全球 | 预测 | QYResearch（经东方财富创作平台转述） | 2026-09-04 | B/C | https://emcreative.eastmoney.com/app_fortune/article/index.html?artCode=20260904181327280124410 |
| D04 | 遗留系统现代化市场 | ≈545.9亿元RMB(2024)→≈827.8亿元(2031), CAGR 5.8% | 收入，产品+服务 | 全球 | 预测 | 恒州诚思 YHResearch（经格隆汇转述） | 2025-10-15 | B/C | https://m.gelonghui.com/p/2996899 |
| D05 | 中国软件业务收入 | 154,831亿元(+13.2%)；基础软件 2,146亿(+11.1%)；工业软件 3,330亿(+9.7%) | 官方行业统计 | 中国 | 2025 | 工业和信息化部《2025年软件业运行情况》 | 2026-01-30 | A | http://finance.people.com.cn/n1/2026/0131/c1004-40656847.html （新华社/人民网转发原文） |
| D06 | 商业代码库开源渗透 | 96%含开源；开源占比77%；样本1,067库/17行业 | Black Duck 审计抽样 | 全球 | 2023审计 | Synopsys CyRC (OSSRA 2024 第9版) | 2024（官方页 2025-01-08 可见） | B | https://www.blackduck.com/zh-cn/resources/analyst-reports/open-source-security-risk-analysis.html |
| D07 | 审计代码库含过期4年+开源件比例 | 89%（OSSRA 2023） | Black Duck 审计 | 全球 | 2022审计 | Synopsys（经深圳网安行业站 2024-11-05 转述 + arXiv 2408.10327 引用） | 2023（转述 2024-11-05） | C | https://www.szw.org.cn/20241105/68155.html |
| D08 | PyPI 非活跃包 | 415,151 包中 103,733 非活跃（双法交叉判定，推算25.0%）；明确弃用 9,173；仅 8.7% 弃用公告附替代方案 | 学术实证（无 commit 且超期未发版双条件） | 全球(PyPI) | 数据截至2023-01，发2024 | arXiv:2408.10327 预印本 | 2024-08-19 | B | https://arxiv.org/html/2408.10327v1 |
| D09 | 弃用供需意愿错配 | 75.4% 非活跃维护者不打算发弃用声明；89.5% 用户希望被告知 | 问卷（作者自采集） | 全球 | 2023-24 | arXiv:2408.10327 | 2024-08-19 | B | 同 D08 |
| D10 | COBOL 存量与态度 | 每日在用 775–8,500 亿行；49国1,104名从业者；64% 倾向现代化而非重写 | 抽样调查（Vanson Bourne 执行） | 全球 | 2021-22 | Micro Focus | 2022-02（新浪科技·新智元转述） | C | https://finance.sina.com.cn/tech/csj/2022-02-12/doc-ikyamrna0376544.shtml |
| D11 | COBOL 存量（另一口径） | 2,200 亿行活跃；43% 银行核心系统；95% ATM 交易 | 转引 Reuters 2017/行业估算 | 全球 | 2017 | Reuters（经阿里云开发者社区 2023-05-08 转述） | 2023-05-08 | C | https://developer.aliyun.com/article/1207252 |
| D12 | 十年复现挑战结果 | 35 人参与；43 投稿、28 复现报告；成功普遍依赖虚拟机/模拟器/老硬件手工考古 | 公开挑战（期刊记录） | 全球 | 2020 | ReScience C (Rougier & Hinsen 等) | 2020，DOI:10.5281/zenodo.3886628 系列 | A | https://www.sohu.com/a/414828244_813542 （转述）+ 原刊 https://rescience.github.io |
| D13 | EnvBench 环境配置成功率 | 329 Python+665 JVM 困难仓库；最佳 LLM 方法 Python 6.69% / JVM 29.47% (pass@1)；确定性脚本基线在筛选阶段即解决 15.9%/31.6% | 学术基准 | 全球 | 2025 | JetBrains Research 等, arXiv:2503.14443 | 2025-03 | B | https://arxiv.org/html/2503.14443v1 + https://github.com/JetBrains-Research/EnvBench |
| D14 | CORE-Bench 复现成功率 | 90 个 Code Ocean 胶囊（CS/医/社科, Python/R）；2024 年最强 Agent ≈21% | 学术基准 | 全球 | 2024 | Princeton (Narayanan, Siegel et al.), arXiv:2409.11363 | 2024-09-17 | B | https://arxiv.org/abs/2409.11363 + https://openreview.net/forum?id=BsMMc4MEGS |
| D15 | CORE-Bench 被宣布解决 | Opus 4.5 + Claude Code 脚手架，准确率≈95%，基准方验证后宣布解决 | 基准维护方公告（经聚合媒体转述） | 全球 | 2026 | Princeton HAL / Sayash 公告，miracleplus 转述 | 2026-05-07 | C⚠️（一手为社媒，见缺口 G03） | https://news.miracleplus.com/share_link/99951 |
| D16 | ScienceIDE 规模 | 27 上游代码库、64 环境定义、2,812 任务（2,515修复/295实现/2加速）、14 学科；发布 PhAI-IDE-72B/9B/4B | 技术报告+官网 | 全球 | 2026-09-16 截点 | AItonomy Foundation / PhAI Labs / Qwen, arXiv:2609.19134 | 2026-09-17 | B | https://arxiv.org/abs/2609.19134 + https://github.com/aitofound/ScienceIDE |
| D17 | IA 浏览器可运行软件 | >250,000 件（Emularity 十年累计） | 机构自报 | 全球 | 2023-09 | Internet Archive 官方博客 | 2023-09-20 | A | https://blog.archive.org/2023/09/ |
| D18 | Software Heritage 存档 | 唯一源文件>100亿、commits>20亿、项目>1.6亿、≈1PB | 机构自报（采访转述） | 全球 | 2022 中 | Software Heritage (Polytechnique Insights 专栏) | 2022-05-11 | B/C | https://www.polytechnique-insights.com/en/columns/economy/source-code-building-a-universal-software-archive/ |
| D19 | PyPI 项目总数 | >654,000 | PSF 数据（经论文引用） | 全球 | 2025 | arXiv:2510.00674 引 PSF | 2025-10-01 | B | https://arxiv.org/html/2510.00674v1 |
| D20 | AWS 产品事实 | AWS Transform for Mainframe GA；Custom 转换开箱支持 Java/Node/Python 升级；Mainframe Modernization 托管运行时 2025-11-07 起不再向新客户开放 | 官方产品页 | 全球 | 2026 在架 | Amazon Web Services | 页面访问 2026-10-06 | A | https://aws.amazon.com/cn/mainframe-modernization/ + https://aws.amazon.com/cn/transform/custom/ |
| D21 | Cognition/Devin 商业数据 | 年化收入 $3,700万(2025-05)→$4.92亿(2026-05)→≈$9亿(2026-09)；奔驰现代化 8个月→8天；企业用量 2026 来 +10倍 | 公司自披露（未审计） | 全球 | 2026-09 | Cognition，经新浪财经报道 | 2026-09-13 | C | http://cj.sina.cn/article/normal_detail?url=https://finance.sina.com.cn/wm/2026-09-13/doc-inirscxz0538118.shtml |
| D22 | 相邻创业融资 | Kodesage 种子 $6.6M（2026-06-04, VentureFriends 领投）；8090 Labs A轮 $135M（2026-06-30, Salesforce Ventures 领投） | 融资公告报道 | 全球 | 2026 | SiliconANGLE / TechTimes | 2026-06-04 / 2026-06-30 | C | https://siliconangle.com/news/apps/ + https://www.techtimes.com/articles/319378/20260630/palihapitiya-takes-ceo-role-8090-labs-after-135m-salesforce-ventures-led-round.htm |
| D23 | 欧盟 CRA 时间线 | Reg.(EU) 2024/2847：2024-10-23 通过、2024-12-10 生效；Art.14 报告义务 2026-09-11 适用；主体义务（SBOM Annex I、≥5年支持期等）2027-12-11 适用 | 欧盟立法 | 欧盟（域外效力含中国出口商） | 2024–2027 | EUR-Lex（律所 jdSupra/iThome 政策解读佐证） | 2024-12-10 生效；解读 2026-09-14/22 | A | https://eur-lex.europa.eu/eli/reg/2024/2847/oj + https://www.jdsupra.com/legalnews/preparing-for-the-eu-cyber-resilience-4157975/ |
| D24 | Code Ocean 模式 | IEEE Xplore 内嵌 "Run on Code Ocean" 一键复现；期刊可复现徽章；作者须上传时定义完整环境 | 平台官方机制+媒体说明 | 全球 | 2025-11 报道 | Atypon/Code Ocean（uconf 中文站转述）+ codeocean.com | 2025-11-13 | C | https://www.uconf.com/news/4166 + https://codeocean.com/ |
| D25 | 开源维护收缩 | 追踪约120万项目仅11%积极维护；18.6%一年停维护；供给+29%/年 vs 下载增速73%(2021)→33%(2023) | 四大注册表（Maven/npm/PyPI/NuGet） | 全球 | 2022–23 | Sonatype《2023 State of the Software Supply Chain》（OSC 转述，官方报告链接） | 2023-10（转述 2023-10-12） | B/C | https://www.sonatype.com/state-of-the-software-supply-chain/introduction （转述：https://blog.csdn.net/github_38592071/article/details/133801982） |
| D26 | OSSRA 2024 维护性 | 49% 代码库含两年内无开发活动开源件；91% 风险审计库含落后≥10版本组件 | Black Duck 审计（936 库风险子样本） | 全球 | 2023 审计 | Synopsys Black Duck 官方页 | 2025-01-08（页面日期） | B | 同 D06 链接 |

---

# 十二、数据缺口清单（查不到什么 + 检索路径）

| 编号 | 缺口 | 已尝试的检索路径 | 处理 |
|---|---|---|---|
| G01 | Gartner"美企平均 245 个遗留系统、年成本 $1.5 万亿"一手出处 | 仅命中人人文档转述 PDF 页（无发布日期/原始报告名）；未达 B 级 | 正文剔除；如需引用需购买/查找 Gartner 原新闻稿 |
| G02 | "软件运行时复生/软件保存"独立市场规模 | 英文检索 resurrection/preservation/vintage software market；中文"软件复生 市场规模"——无任何咨询机构立品类 | 用四类邻近口径代理（§2），并如实声明 |
| G03 | Opus 4.5 解决 CORE-Bench 的一手公告（HAL 博客/X 原帖） | 仅命中聚合站 miracleplus；一手为社媒不可直读 | D15 标 C⚠️，正文引用时注明"据转述" |
| G04 | Devin/Code Ocean/Moderne/OpenRewrite 商业定价 | 官网均无公开价目表 | §6 定性描述，不给数字 |
| G05 | 中国信创/老旧系统改造市场规模（赛迪/信通院口径） | 本轮未定位到带日期的官方报告页 | 政策叙事可用，数字不引用 |
| G06 | 中国关于软件长期可复现/SBOM 的具体监管条文 | 检索命中以欧盟 CRA 为主 | 中国部分只引用工信部统计（D05），不虚构政策 |
| G07 | 工业企业为"老软件无人能跑"单独付费的可核验案例 | 检索到的均为咨询公司自述（Reddit 榜单等 D 级） | 需求分层 L5 标"数据不足" |
| G08 | 银行核心迁移报价 $5,000万–$5亿/次；英国央行"COBOL 维护工程师不足 2,000 人"；TSB 迁移事故损失 5 亿英镑；哈佛"开源替代成本 $8.8 万亿" | 分别仅命中网易号/百家号/百度系/聚合站（均 D 级）；TSB 应有一手 FCA/PRA 报告但本轮未定位 | 全部不入正文；建议后续查英国 FCA 2019 公开报告与 Harvard LCV 论文 |
| G09 | EnvBench Python 6.69% 的置信区间/模型细节 | 已读 arXiv HTML 摘要与 §3-4 节 | 引用 pass@1 点估计即可，不引申 |
| G10 | Software Heritage 2024/2025 最新存档规模 | 命中 2022 专栏（D18）与 2023 学术转述（口径含 2.5 亿 origins），无 2025 官方年报页 | 引用 2022 口径并标年份，不更新到"最新" |

---

# 十三、假设清单（全部集中于此）

- **A1 品类界定**：将 ReviveOS 界定为"软件运行时复生与可复现基础设施"，其市场测量必须由四个邻近口径代理（应用现代化服务、IT 现代化服务、大型机现代化、基础软件收入），代理成立的前提是"现代化委托方集合 ⊇ 死软件持有方集合"，此包含关系为逻辑推断而非统计结论。
- **A2 地域**：以全球口径为主（各机构原始口径），中国单列；人民币/美元数值未做换算与购买力调整。
- **A3 时间**：历史 2020–2026；预测 2026–2032，均沿用发布机构自身的基年假设（已在 §2.2 列明）。
- **A4 等级判定补充规则**：学术预印本（arXiv）判 B（方法可见、可复跑）；厂商基于自有审计数据的一手报告（Synopsys/Sonatype/IA/MIIT）按其机构性质分别判 B 或 A；凡"转述官方"的报道降一级（标 B/C 或 C）；无法定位原始发布日期的页面不高于 C⚠️。
- **A5 未审计披露**：D21 的 Cognition 收入为公司自披露，无审计背书，只用作"需求热度"的方向性证据，不作绝对市场规模推算。
- **A6 商业模式推断**：§6 末段（CRA 合规 + 科研胶囊为最优变现路径）是基于证据权重的主观判断，非数据结论。
- **A7 派生计算**：D08 的"25.0%"为报告者用论文分子的原始计数（103,733/415,151）推算，论文原文未直接给出该百分比；引用时标注"推算"。
- **A8 检索局限**：本报告依赖搜索引擎可索引的公开网页（共 8 轮检索，2026-10-06 执行），付费墙内报告全文（QYResearch/YH/各 OSSRA PDF）未读原文，仅引用其公开摘要与新闻稿。

---

# 十四、参考文献（统一格式：机构. 标题. 发布日期. 访问日期 2026-10-06. URL）

1. MarketsandMarkets. Application Modernization Services Market – Global Forecast to 2031. 2025-10-29. https://www.marketsandmarkets.com/Market-Reports/application-modernization-services-market-149625724.html
2. MarketsandMarkets. Mainframe Modernization Market worth $13.34 billion by 2030 (Press Release). 2025-08-21. https://www.marketsandmarkets.com/PressReleases/mainframe-modernization.asp
3. QYResearch（东方财富创作平台转述）. 全球 IT 现代化服务市场研究. 2026-09-04. https://emcreative.eastmoney.com/app_fortune/article/index.html?artCode=20260904181327280124410
4. 恒州诚思 YHResearch（格隆汇转述）. 2025年全球及中国遗留系统现代化头部企业市场占有率调研. 2025-10-15. https://m.gelonghui.com/p/2996899
5. 工业和信息化部. 2025年软件业运行情况. 2026-01-30. 人民网财经转载: http://finance.people.com.cn/n1/2026/0131/c1004-40656847.html
6. Synopsys Black Duck. 开源安全和风险分析（OSSRA）报告系列（第9版，2024）. https://www.blackduck.com/zh-cn/resources/analyst-reports/open-source-security-risk-analysis.html
7. arXiv:2408.10327. An Empirical Study on Package-Level Deprecation in Python Ecosystem. 2024-08-19. https://arxiv.org/html/2408.10327v1
8. Micro Focus（Vanson Bourne 执行）COBOL 调查（新浪科技·新智元转述）. 2022-02-12. https://finance.sina.com.cn/tech/csj/2022-02-12/doc-ikyamrna0376544.shtml
9. Reuters 2017 数据（阿里云开发者社区转引）. 60多岁的COBOL，今天仍有8000亿行代码. 2023-05-08. https://developer.aliyun.com/article/1207252
10. ReScience C. Ten Years Reproducibility Challenge 系列（DOI:10.5281/zenodo.3886628 等）. 2020. https://rescience.github.io
11. arXiv:2503.14443 (JetBrains Research). EnvBench: A Benchmark for Automated Environment Setup. 2025-03. https://arxiv.org/html/2503.14443v1
12. arXiv:2409.11363 (Princeton). CORE-Bench: Fostering the Credibility of Published Research Through a Computational Reproducibility Agent Benchmark. 2024-09-17. https://arxiv.org/abs/2409.11363
13. miracleplus（转述 HAL/Princeton 公告）. CORE-Bench 基准测试结果：Opus 4.5. 2026-05-07. https://news.miracleplus.com/share_link/99951
14. arXiv:2609.19134 (AItonomy Foundation). ScienceIDE: Turning World's Scientific Codebase into Agent Learnable Environments. 2026-09-17. https://arxiv.org/abs/2609.19134
15. Internet Archive Blog. 10 Years of Emulation at the Archive (250,000+ items). 2023-09-20. https://blog.archive.org/2023/09/
16. Polytechnique Insights. Why Software Heritage is creating a global software archive. 2022-05-11. https://www.polytechnique-insights.com/en/columns/economy/source-code-building-a-universal-software-archive/
17. Amazon Web Services. Mainframe Modernization / Transform Custom 产品页. 访问于 2026-10-06. https://aws.amazon.com/cn/transform/custom/
18. 新浪财经. 三位华人，让AI自己写代码，估值3000亿（Cognition 数据）. 2026-09-13. https://finance.sina.com.cn/wm/2026-09-13/doc-inirscxz0538118.shtml
19. SiliconANGLE. Startup Kodesage secures seed funding. 2026-06-04. https://siliconangle.com/news/apps/
20. TechTimes. Palihapitiya Takes CEO Role at 8090 Labs After $135M Round. 2026-06-30. https://www.techtimes.com/articles/319378/20260630/palihapitiya-takes-ceo-role-8090-labs-after-135m-salesforce-ventures-led-round.htm
21. EUR-Lex. Regulation (EU) 2024/2847 (Cyber Resilience Act). https://eur-lex.europa.eu/eli/reg/2024/2847/oj ；律所解读 (JD Supra). 2026-09-14. https://www.jdsupra.com/legalnews/preparing-for-the-eu-cyber-resilience-4157975/
22. Code Ocean 官网 + UCONF 中文站. IEEE Code Ocean 一键复现机制说明. 2025-11-13. https://codeocean.com/ ; https://www.uconf.com/news/4166
23. Sonatype. State of the Software Supply Chain Report 2023. https://www.sonatype.com/state-of-the-software-supply-chain/introduction （OSC 转述：https://blog.csdn.net/github_38592071/article/details/133801982, 2023-10-12）
24. arXiv:2510.00674. A Practical Tool for Reducing Python Dependency Bloat（引 PyPI 项目总数）. 2025-10-01. https://arxiv.org/html/2510.00674v1
