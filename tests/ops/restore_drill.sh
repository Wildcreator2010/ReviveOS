#!/usr/bin/env bash
set -euo pipefail
if [[ "${REQUIRES_DOCKER:-0}" != 1 ]]; then echo "requires_docker: restore drill needs Docker daemon"; exit 2; fi
echo "restore drill placeholder: run temporary stack, restore, revive verify"
