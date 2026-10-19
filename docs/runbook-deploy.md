# 生产部署

起栈与 HTTPS 验收需要 Docker daemon，均标记 `requires_docker`；当前环境 daemon 不可达，未声明通过。静态校验：`docker compose -f infra/compose/prod.docker-compose.yml config --quiet`。Caddy 使用 `tls internal`，只暴露 443。
