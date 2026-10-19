#!/usr/bin/env bash
set -euo pipefail
: "${SOURCE_ALIAS:?}" "${TARGET_ALIAS:?}"
mc mirror --overwrite "$SOURCE_ALIAS" "$TARGET_ALIAS"
