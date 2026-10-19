# 日志运行手册

stdout 使用单行 JSON；共享脱敏实现位于 `revive_core.logging`，CI 应扫描 `sk-`、`ghp_`、`Bearer` 与邮箱。生产保留 30 天，开发保留 7 天。

查询模板：按 job_id 追事件；按 signature 聚合构建失败；按日期聚合成本。用户代码 stdout 只记录 artifact 指针。
