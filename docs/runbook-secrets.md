# ReviveOS secrets rotation runbook

生产环境只从 secret manager 注入变量；不得把值写进仓库、镜像、日志或 trace。验收数字必须来自现场记录。

## LLM API key
1. 在供应商创建新 key，限制模型、来源与额度。
2. 更新 REVIVE_LLM__API_KEY 并滚动重启 API/worker。
3. 验证成本与错误指标后吊销旧 key。

## JWT signing secret
1. 生成至少 32 字节随机值。
2. 更新 REVIVE_JWT__SECRET 并滚动重启 API。
3. 通知用户重新登录；不得打印 token。

## MinIO credentials
1. 创建最小权限的新 access/secret pair。
2. 更新 S3_ACCESS_KEY / S3_SECRET_KEY，验证读写与备份。
3. 吊销旧 pair 并检查审计记录。

## Revive API key
1. 创建替代 API key，仅展示一次并安全交付。
2. 更新调用方，验证 401/200 后吊销旧 key。
3. 记录 owner、时间和权限范围，不记录值。

## 回滚与审计
保留 secret manager 版本号，不保留明文；失败时回滚上一版本并记录事件编号。
