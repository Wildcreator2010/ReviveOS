# 备份与恢复演练

脚本依赖 Docker/pg_dump/mc，验收标记 `requires_docker`；未在现场演练前填写 RPO/RTO。备份必须复制到异地或独立账号/卷，不能与生产同卷同机。执行 `BACKUP_DIR=... DATABASE_URL=... bash infra/backup/pg-backup.sh`，恢复用 `BACKUP_FILE=... DATABASE_URL=... bash infra/backup/pg-restore.sh`，随后对临时栈逐项运行 `revive verify`。