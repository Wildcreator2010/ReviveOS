# 备份与恢复演练

脚本依赖 Docker/pg_dump/mc，验收标记 `requires_docker`；未在现场演练前填写 RPO/RTO。备份必须复制到异地或独立账号/卷，不能与生产同卷同机。执行 `BACKUP_DIR=... DATABASE_URL=... infra/backup/pg-backup.sh`，随后恢复到临时栈并逐项运行 `revive verify`。