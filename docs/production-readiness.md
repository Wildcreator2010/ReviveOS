# Production Readiness and Deployment

## Readiness status

The repository contains production image definitions, a fail-closed Compose topology and a production API stack that assembles itself from configuration. It still must be exercised once on the target platform before it can be called deployment-verified.

- Production Dockerfiles and a GHCR release workflow exist for API, worker and Web. CI builds all three images on every push (no push to a registry) and smoke-tests the API `/healthz` and the Web static console, so a broken Dockerfile fails long before a release. The release workflow itself has not been exercised on a tag yet, and third-party base image digests must still be resolved and reviewed. Compose requires explicit GHCR image paths to match the release owner.
- **Production API stack (implemented).** With `REVIVE_ENV=prod` + `DATABASE_URL` + `REDIS_URL` + `S3_*`, `create_app` builds a request-scoped SQLAlchemy UoW (commit on success, rollback on error), a PostgreSQL control-plane port, `RedisEventBus` over `SessionEventSink`, a Redis login throttle, and an S3-compatible capsule store. It refuses to start when any of those would be process-local.
- **Remaining verification gap: the cross-process persistence test has not run here.** `tests/integration/api/test_api_persistence.py` is marked `requires_docker`; it is skipped in this sandbox because the Docker daemon/PG are unreachable. Run it in CI or on a Docker host before accepting production traffic.
- Worker dispatch goes through Celery in production (`_dispatch_job`), so user code never runs inside the API process. Cancellation is cooperative: the pipeline's per-stage guard reads the persisted `cancel_requested` flag.
- Compose requires every image digest and fails closed when values are missing. `tools/image_digests.py` rejects all-zero placeholders, but a real digest lock/update automation is still an operator/release responsibility.
- The API image implements `GET /healthz` (liveness) and `GET /readyz` (readiness). Readiness now covers **postgres, redis and object storage**: the S3 bucket is HEAD-probed (any answer below 500 counts as reachable, so a 403 on a private bucket is still ready; transport errors and 5xx are not). Compose keeps `/healthz` for the container healthcheck so a transient dependency outage cannot trigger a restart loop; use `/readyz` for load-balancer or orchestrator gating. Compose runs Alembic migrations as a one-shot dependency before the API starts.
- Image builds install the workspace from `pyproject.toml` rather than `uv.lock`, and the base images are tag-pinned (`python:3.11-slim`, `node:20-alpine`, `nginx:1.27-alpine`, `caddy:2-alpine`). The release workflow records the digest of every image it publishes, but reproducible-by-construction builds require switching the Dockerfiles to `uv sync --frozen` and digest-pinned base images — track that before a regulated release.
- `GET /metrics` serves Prometheus text for the API/worker process (jobs, sandbox runs, LLM cost, repair ratio). It is intentionally internal: it is not part of the OpenAPI contract and Caddy only proxies `/api/*`, so it is reachable only on the compose network. Scrape it from the observability stack (`infra/observability/`).
- `schemas/openapi/openapi.json` is guarded by `tests/unit/api/test_openapi_contract.py`; a route change without regenerating the snapshot fails the test suite (run `python tools/export_openapi.py`, then `pnpm --filter web gen:api`).
- A production `.env` file is absent by design. Create `infra/envs/revive.prod.env` from the template using a secret manager, and supply S3 credentials, LLM credentials, a high-entropy JWT secret, worker token, and unique Postgres/Redis passwords. Compose supplies internal service URLs. Do not commit populated values.
- Backup scheduling is external: schedule/test the scripts under `infra/backup/` with off-host retention.
- The worker mounts the Docker socket, which is effectively host-root access. Deploy only on a dedicated, isolated host with restricted operator access; this is not a hardened multi-tenant boundary.
- No TLS certificate/domain value or external ingress policy is checked in. Configure the Caddy site for the deployment domain and verify firewall rules expose only intended ports.

## Required release and rollout procedure

1. Tag a release to build and publish API, worker and Web images to GHCR. `release.yml` builds the three images in a matrix, records each immutable digest as an artifact, gates on HIGH/CRITICAL vulnerabilities via the official Trivy action, and emits a CycloneDX SBOM via the official Anchore action (the runner does not ship `trivy`/`syft` binaries, so bare CLI calls were replaced). Configure artifact retention and signing/attestation before regulated use.
2. Resolve the published API, worker and Web images plus reviewed Postgres, Redis and Caddy images to registry digests. Set `API_DIGEST`, `WORKER_DIGEST`, `WEB_DIGEST`, `POSTGRES_DIGEST`, `REDIS_DIGEST`, and `CADDY_DIGEST` in the deployment environment. Reject empty, tag-only, and all-zero values.
3. Create `infra/envs/revive.prod.env` from `infra/envs/revive.prod.env.template` via the secret manager. Validate that no `<REQUIRED_...>` placeholders remain and that secrets are unique to this deployment.
4. Configure the Caddy domain and TLS, provision durable encrypted volumes/storage, configure off-host backups, and test restore before accepting user data.
5. On the isolated deployment host, validate and start the stack:

   ```sh
   docker compose --env-file .env -f infra/compose/prod.docker-compose.yml config --quiet
   docker compose --env-file .env -f infra/compose/prod.docker-compose.yml pull
   docker compose --env-file .env -f infra/compose/prod.docker-compose.yml up -d
   docker compose --env-file .env -f infra/compose/prod.docker-compose.yml ps
   ```

   The `.env` passed to Compose contains image paths, image digests, `REVIVE_DOMAIN`, `DOCKER_GID`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, and `REVIVE_WORKER_TOKEN`; use `infra/envs/compose.env.template` and lowercase 64-character hex passwords. The service `env_file` remains `infra/envs/revive.prod.env` and supplies application/LLM/S3 secrets.
6. Confirm API health, worker connectivity, migrations, TLS, and backup/restore behavior. Keep rollback digests and database recovery steps available before traffic cutover.

## Checks

Run the repository's static test gates before release:

```sh
uv sync --all-packages --frozen
uv run pytest -q tests -m "not requires_docker"
# Cross-process persistence gate (needs DATABASE_URL + a migrated PostgreSQL):
uv run pytest -q tests/integration/api/test_api_persistence.py
uv run python tools/check_contracts.py
uv run python tools/check_global_rules.py .
```

These checks do not prove that production images, credentials, network policy, persistent storage, TLS, or backups work. A deployment drill on the target platform remains required.
