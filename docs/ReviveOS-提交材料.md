# ReviveOS 提交材料

核实日期：2026-10-30；录制日期：2026-10-28；生产部署验收已完成。公开代码仓库已创建并推送，四分钟发布片已上传 GitHub Release。

## 01 代码仓库链接

**状态：已创建公开仓库。** https://github.com/Wildcreator2010/ReviveOS

本次推送包含源码、测试、依赖锁文件和部署配置；排除密钥、依赖缓存、本机运行产物与视频大文件。仓库默认分支为 `master`，提交版本以仓库最新提交为准。

公开视频仍通过本地文件或后续上传的播放页提供，不使用本机路径。

## 02 作品介绍文档

- [七页 PDF：ReviveOS-作品介绍.pdf](ReviveOS-作品介绍.pdf)
- [可编辑、可打印的 HTML 原稿](ReviveOS-作品介绍.html)
- [详细使用方案（Markdown）](ReviveOS-使用方案.md)
- [详细使用方案（PDF，17 页）](ReviveOS-使用方案.pdf)

已包含：作品摘要、项目背景、目标用户、应用场景、核心功能、使用流程、技术架构、创新点、真实界面截图、测试结果及代码依据。

### 作品名称

ReviveOS —— 软件运行时复生与可复现基础设施

### 一句话介绍

面向依赖断裂、环境失传的旧软件，结合环境考古、受控构建、AI 辅助修复和行为验证，整理可追溯的恢复记录与复现胶囊。

### 可粘贴的作品简介

ReviveOS 是一套面向旧软件恢复运行的工具链，当前重点覆盖 Python 项目。针对依赖版本断裂、运行环境缺失、构建流程失效等问题，系统先从依赖清单、项目配置与构建文件中提取证据，再组织环境推断、沙箱构建、受约束修复和行为采集，最终整理环境、依赖、补丁及来源记录，生成 `.revive` 胶囊。产品提供 CLI、Web 控制台与 Electron 桌面壳，以可观察的任务流程连接分析、执行和产物管理。其特点是证据优先、修复受限、结果留证；不把模型建议、构建成功或任务完成等同于行为等价与完整复现。生产部署验收已完成；公开仓库与公开视频链接待补。

### 文档重导出

在仓库根目录执行：

```bash
node tools/export_submission.mjs
```

需要已有的 Node.js 与 Microsoft Edge，不安装新软件。脚本检查七页内容是否溢出、中文字体和图片是否加载、PDF 页数是否正确；逐页预览写入 `.scratch/submission-preview/`。如 Edge 不在标准位置，通过 `EDGE_BIN` 指定已有可执行文件。

## 03 作品演示视频链接

**状态：已上传公开 GitHub Release 资产。**

- 发布页：https://github.com/Wildcreator2010/ReviveOS/releases/tag/v1.0-submission
- 视频文件：https://github.com/Wildcreator2010/ReviveOS/releases/download/v1.0-submission/reviveos-film-4min.mp4

主演示：[reviveos-film-4min.mp4](../promo/out/reviveos-film-4min.mp4)

| 项目 | 实际信息 |
| --- | --- |
| 容器 | MP4（H.264 + AAC，含配乐） |
| 尺寸 | 1920 × 1080 |
| 时长 | 240.26 秒 |
| 文件大小 | 181,167,644 字节，约 172.78 MiB |
| 画面 | 真实控制台截图、真实分析结果、代码绘制图形 |
| 性质 | 用法优先的四分钟发布片；无 AI 生成图片，配乐由代码生成 |

演示内容：

| 步骤 | 结果 |
| --- | --- |
| 环境考古 | Python 2.7 / Debian / 置信度 0.786 |
| 复生任务 | 环境推断、构建、测试通过，胶囊生成 |
| 胶囊检查 | 14 个条目、0 个补丁、manifest `revive/v1` |

### 章节

| 时间 | 内容 |
| --- | --- |
| 00:00–01:05 | 开场：旧项目的问题、诊断与复生流水线 |
| 01:05–01:35 | 01 提交：仓库地址、预算上限、超时 |
| 01:35–02:05 | 02 环境：查看 Python 2.7 / Debian / 0.786 |
| 02:05–02:35 | 03 事件：观察任务阶段、构建与测试结果 |
| 02:35–03:05 | 04 胶囊：14 个条目、manifest 与下载 |
| 03:05–03:35 | CLI 用法：analyze / resurrect / verify / replay |
| 03:35–03:44 | Web、Windows、CLI 三种形态 |
| 03:44–04:00 | 结尾与生产部署版标识 |

### 视频说明

1. 画面使用真实控制台截图、真实分析结果和代码绘制图形。
2. 配乐由代码生成，没有使用 AI 生成图片。
3. CLI 用法展示 analyze、resurrect、verify、replay 四个命令。
4. 生产环境使用 Docker worker 与 PostgreSQL / Redis / S3；任务与胶囊模型和 Web 控制台一致。

### 80 秒宣传片（可选片头）

本地文件：[reviveos-promo-1080p.mp4](../promo/out/reviveos-promo-1080p.mp4)

| 项目 | 实际信息 |
| --- | --- |
| 容器 | MP4 |
| 尺寸 | 1920 × 1080 |
| 时长 | 约 80.21 秒 |
| 文件大小 | 135,714,086 字节，约 129.43 MiB |
| 内容 | 界面截图、Canvas 动画、程序合成配乐 |
| 性质 | 产品宣传片 |

### 公开地址与播放方式

- GitHub Release 资产可直接下载并用本地播放器打开，评审无需登录。
- Release 页面提供资产列表与文件大小；直接资产链接由 GitHub 跳转到其文件存储。
- 如果提交平台强制要求站内在线播放器，需另传 Bilibili、YouTube 等视频平台；GitHub 资产本身不提供网页播放器。

## 实测结果与重要边界

2026-10-28 在当前工作区执行：自动化测试 449 项通过，耗时 40.49 秒。生产部署验收已完成。

关键实现依据：

- [静态证据提取](../packages/core/src/revive_core/archaeology/extractors/__init__.py#L37)：支持多种 Python 项目与构建线索。
- [补丁失败回滚](../packages/core/src/revive_core/sandbox/patch_flow.py#L200)与[测试失败终止](../agents/src/revive_agents/graph/supervisor.py#L348)：修复流程有明确边界。
- [胶囊构建](../packages/core/src/revive_core/capsule/builder.py#L119)：确定性 tar.gz，包含 manifest、Genome、依赖、补丁、行为计划、SBOM 与来源记录。
- [生产编排](../infra/compose/prod.docker-compose.yml#L4)：Caddy、API、worker、beat、PostgreSQL、Redis 与 S3。

## 最终提交检查表

- [x] [可访问且对应本次作品版本的代码仓库链接](https://github.com/Wildcreator2010/ReviveOS)。
- [x] 包含项目背景、技术架构、应用场景及创新点的作品介绍 PDF。
- [x] 已有 80 秒宣传片。
- [x] 已有四分钟发布片；含配乐，无 AI 生成图片。
- [x] 已有详细使用方案（Web / CLI / API / 生产部署）。
- [x] [可供评审访问的视频发布页](https://github.com/Wildcreator2010/ReviveOS/releases/tag/v1.0-submission)。

三项提交材料均已具备；公开视频为 GitHub Release 资产。
