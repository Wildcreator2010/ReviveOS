#!/usr/bin/env bash
set -euo pipefail
[[ "${REQUIRES_DOCKER:-0}" == 1 ]] || { echo "requires_docker"; exit 2; }
docker compose -f infra/compose/prod.docker-compose.yml kill worker
