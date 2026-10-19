# ReviveOS unified task entry point (T-INIT-01 / T-INIT-03 / T-INIT-04).
#
# Everything runs through the workspace-local interpreter, never a bare system
# `python`:
#   Windows        : .venv\Scripts\python.exe
#   Linux / WSL/CI : .venv/bin/python
# The first existing one wins; override with `make test PYTHON=...`.
#
# uv and pnpm are not on PATH on the Windows dev box. See docs/dev-environment.md:
#   uv   -> %USERPROFILE%\.local\bin\uv.exe   (override with UV=...)
#   pnpm -> node .tools/pnpm/node_modules/pnpm/bin/pnpm.cjs

VENV_WIN := .venv/Scripts/python.exe
VENV_POSIX := .venv/bin/python
PYTHON ?= $(if $(wildcard $(VENV_WIN)),$(VENV_WIN),$(VENV_POSIX))

UV ?= uv
PNPM ?= node .tools/pnpm/node_modules/pnpm/bin/pnpm.cjs

SRC_PATHS := packages/core/src cli/src agents/src apps/api/src
# Every directory that holds Python. Kept explicit instead of "." because
# `ruff format .` panics on this workspace's root walk (stray/scratch entries);
# the scope below is the whole Python surface and is deterministic.
PY_PATHS := $(SRC_PATHS) tests tools revivebench
COMPOSE := docker compose -f infra/compose/dev.docker-compose.yml

PRE_COMMIT_HOME ?= .pre-commit-cache
export PRE_COMMIT_HOME

# Put the venv first on PATH so pre-commit `language: system` hooks resolve the
# same interpreter as $(PYTHON).
ifeq ($(OS),Windows_NT)
VENV_BIN := .venv/Scripts
PATH_SEP := ;
else
VENV_BIN := .venv/bin
PATH_SEP := :
endif
export PATH := $(VENV_BIN)$(PATH_SEP)$(PATH)

.PHONY: help sync dev dev-down dev-ps dev-logs test unit contracts check-rules openapi gen-web \
        lint fmt typecheck pre-commit migrate migrate-rollback web-install web-build desktop-build desktop-dist \
        ci web-check prod-check

help:
	@echo "sync          install/refresh the uv workspace into .venv"
	@echo "dev           start postgres+redis+minio, then bootstrap the buckets"
	@echo "dev-down      stop the dev stack (keeps volumes)"
	@echo "dev-ps        show dev container health"
	@echo "dev-logs      follow dev container logs"
	@echo "test          full pytest suite"
	@echo "unit          pytest unit layer (skips requires_docker)"
	@echo "contracts     validate schemas/ and tests/contracts fixtures"
	@echo "check-rules   global rules gate (secrets / repair limits)"
	@echo "lint          ruff check + ruff format --check"
	@echo "fmt           apply ruff format and safe fixes"
	@echo "typecheck     mypy over the four Python packages"
	@echo "migrate       alembic upgrade head (needs DATABASE_URL + dev postgres)"
	@echo "migrate-rollback  alembic downgrade base"
	@echo "pre-commit    run every hook on every file"
	@echo "gen-web       regenerate TypeScript types from OpenAPI"
	@echo "web-build     typecheck, lint, and build the Web console"
	@echo "desktop-build compile the Electron desktop shell"
	@echo "desktop-dist  package the Windows desktop installer"
	@echo "web-check     web typecheck + lint (no build; run web-build outside the DSH sandbox)"
	@echo "ci            exactly the CI quality gate: lint, typecheck, unit, contracts, rules, web-check"
	@echo "prod-check    static production checks (compose parse, image digests, openapi drift)"

sync:
	$(UV) sync --all-packages

dev:
	$(COMPOSE) up -d
	$(COMPOSE) run --rm minio-init

dev-down:
	$(COMPOSE) down

dev-ps:
	$(COMPOSE) ps

dev-logs:
	$(COMPOSE) logs -f --tail=100

test:
	$(PYTHON) -m pytest -q

unit:
	$(PYTHON) -m pytest -q tests -m "not requires_docker"

contracts:
	$(PYTHON) tools/check_contracts.py

openapi:
	$(PYTHON) tools/export_openapi.py

check-rules:
	$(PYTHON) tools/check_global_rules.py .

lint:
	$(PYTHON) -m ruff check $(PY_PATHS)
	$(PYTHON) -m ruff format --check $(PY_PATHS)

fmt:
	$(PYTHON) -m ruff format $(PY_PATHS)
	$(PYTHON) -m ruff check --fix $(PY_PATHS)

typecheck:
	$(PYTHON) -m mypy $(SRC_PATHS)

pre-commit:
	$(PYTHON) -m pre_commit run --all-files

migrate:
	$(PYTHON) -m alembic -c apps/api/alembic.ini upgrade head

migrate-rollback:
	$(PYTHON) -m alembic -c apps/api/alembic.ini downgrade base

web-install:
	$(PNPM) install

gen-web: openapi
	$(PNPM) --filter web gen:api

web-build:
	$(PNPM) --filter web typecheck
	$(PNPM) --filter web lint
	$(PNPM) --filter web build

desktop-build:
	$(PNPM) --filter desktop build

desktop-dist: web-build
	$(PNPM) --filter desktop dist

# `next build` needs to fork worker processes, which the DSH sandbox denies; the
# typecheck + lint half is still meaningful there, so CI and sandboxes share this.
web-check:
	$(PNPM) --filter web typecheck
	$(PNPM) --filter web lint

# One command that mirrors .github/workflows/ci.yml (minus the Web build, which
# needs a host that can fork child processes).
ci: lint typecheck unit contracts check-rules web-check
	@echo "ci: all repository gates passed"

prod-check:
	$(PYTHON) tools/image_digests.py
	$(PYTHON) tools/export_openapi.py --output .pytest-work/openapi.verify.json
	$(PYTHON) -c "import json,sys; a=json.load(open('schemas/openapi/openapi.json',encoding='utf-8')); b=json.load(open('.pytest-work/openapi.verify.json',encoding='utf-8')); sys.exit(0 if a==b else 'openapi snapshot drifted: run make openapi')"
	@echo "prod-check: compose/digest/openapi static checks passed"
