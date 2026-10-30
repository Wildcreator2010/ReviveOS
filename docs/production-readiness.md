# Production Readiness and Deployment

## Readiness status

The repository contains production image definitions, a fail-closed Compose topology and a production API stack that assembles itself from configuration. It still must be exercised once on the target platform before it can be called deployment-verified.

- Production Dockerfiles and a GHCR release workflow exist for API, worker and Web. CI builds all three images on every push (no push to a registry) and smoke-tests the API `/healthz` and the Web static console, so a broken Dockerfile fails long before a release. The release workflow itself has not been exercised on a tag yet, and third-party base image digests must still be resolved and reviewed. Compose requires explicit GHCR image paths to match the release owner.
- **Production API stack (implemented).** With `REVIVE_ENV=prod` + `DATABASE_URL` + `REDIS_URL` + `S3_*`, `create_app` builds a request-scoped SQLAlchemy UoW (commit on success, rollback on error), a PostgreSQL control-plane port, `RedisEventBus` over `SessionEventSink`, a Redis login throttle, and an S3-compatible capsule store. It refuses to start when any of those would be process-local.
- **Web authentication (implemented).** The console ships a `/login` route with login/register; access and refresh tokens live in `sessionStorage` and are attached as `Authorization: Bearer`; a single-flight refresh rotates them on 401. `POST /auth/logout` revokes the refresh family. CORS allows `localhost`/`127.0.0.1` origins by default so the Electron renderer can talk to a local API; set `REVIVE_CORS_ORIGINS`/`REVIVE_CORS_ORIGIN_REGEX` for other deployments. This is a bearer-token design (no CSRF cookies); protect the origin with TLS and avoid injecting untrusted scripts.
- **Model provider settings (implemented).** Admins can configure `fake` / `openai` / `anthropic` / `custom` in the Web settings page. The config is stored in `runtime_settings` and read by the worker at job start; `REVIVE_LLM__API_KEY` is no longer a startup requirement. Provider API keys are stored encrypted with `REVIVE_SECRETS__KEY` (or a domain-separated key derived from `REVIVE_JWT__SECRET`) and are only returned as a last-four hint. The admin page includes a no-network `fake` probe and an authenticated connection test. Keep `REVIVE_SECRETS__KEY` identical between API and worker if you set it; rotating it makes stored provider keys unreadable. API keys now expire after `REVIVE_API_KEY__TTL_DAYS` (default 90; `0` disables expiry).
- **Sandbox images are digest-pinned when possible.** The worker resolves each base-image tag to a digest before building and caches the result; set `REVIVE_SANDBOX__REQUIRE_DIGEST=1` to fail closed when resolution is unavailable. A custom seccomp profile can be loaded by setting `REVIVE_SANDBOX__SECCOMP_PROFILE` to a path visible to the Docker daemon on the host; otherwise Docker's default profile applies.
- **First admin is a deliberate manual step:** register a normal account through `/login`, then run `UPDATE users SET role='admin' WHERE email='...'` against PostgreSQL. The API has no self-service role escalation.
- **Keep the API internal.** Uvicorn trusts Caddy's `X-Forwarded-For` (overwritten by the Caddyfile) so login throttling and logs see the real client IP; the API port must never be published directly, or a caller could spoof that header.
- **Capsules are produced by the worker.** After a successful job the worker builds a deterministic tar.gz `.revive` capsule, self-verifies its manifest/digests, and uploads it to `POST /jobs/{id}/capsule` using `REVIVE_WORKER__TOKEN`; Compose supplies `REVIVE_API_URL=http://api:8000`. A capsule build/upload failure fails the job rather than emitting a fake `capsule://` reference. Dependencies are inferred from the archaeology genome and installed while the sandbox image builds; the job container itself stays network-disabled and runs `pip install --no-index --no-deps --no-build-isolation -e .`.
- **Behavior capture is real when a tests/import case exists.** The worker runs the captured cases inside the sandbox and records fingerprints/compatibility; without a baseline the compatibility is `null` and the job is at best partial (no fabricated 1.0). A repo with no tests/importable package records `tests_absent` and succeeds as partial rather than pretending tests passed.
- **Celery beat runs the orphan sweeper.** Compose includes a `beat` service; the worker queue consumes the scheduled sweep task. Without beat, terminal/unknown sandbox containers are never cleaned.
- **LLM usage is persisted.** The worker wraps the provider with a recorder that writes `llm_calls` rows, so `/admin/costs/daily` is populated from real provider usage/cost estimates.
- **Remaining verification gap: the cross-process persistence test has not run here.** `tests/integration/api/test_api_persistence.py` is marked `requires_docker`; it is skipped in this sandbox because the Docker daemon/PG are unreachable. Run it in CI or on a Docker host before accepting production traffic.
- Worker dispatch goes through Celery in production (`_dispatch_job`), so user code never runs inside the API process. Cancellation is cooperative: the pipeline's per-stage guard reads the persisted `cancel_requested` flag.
- Compose requires every image digest and fails closed when values are missing. `tools/image_digests.py` rejects all-zero placeholders, but a real digest lock/update automation is still an operator/release responsibility. The Postgres service must use a pgvector-capable image (`pgvector/pgvector:pg16`); migration `0002` runs `CREATE EXTENSION vector`, which stock `postgres:16` cannot satisfy.
- The API image implements `GET /healthz` (liveness) and `GET /readyz` (readiness). Readiness now covers **postgres, redis and object storage**: the S3 bucket is HEAD-probed (200/403 counts as reachable, so a 403 on a private bucket is still ready; transport errors, 404 for a missing bucket and 5xx are not). Compose keeps `/healthz` for the container healthcheck so a transient dependency outage cannot trigger a restart loop; use `/readyz` for load-balancer or orchestrator gating. Compose runs Alembic migrations as a one-shot dependency before the API starts.
- Image builds install the workspace from `pyproject.toml` rather than `uv.lock`, and the application base images are tag-pinned (`python:3.11-slim`, `node:20-alpine`, `nginxinc/nginx-unprivileged:1.27-alpine`, `caddy:2-alpine`). Sandbox base images are resolved to digests by the worker when the registry is reachable; set `REVIVE_SANDBOX__REQUIRE_DIGEST=1` to fail closed otherwise. The release workflow records the digest of every application image it publishes, but reproducible-by-construction application builds still require switching the Dockerfiles to `uv sync --frozen` and digest-pinned base images — track that before a regulated release.
- `GET /metrics` serves Prometheus text for the API/worker process (jobs, sandbox runs, LLM cost, repair ratio). It is intentionally internal: it is not part of the OpenAPI contract and Caddy only proxies `/api/*`, so it is reachable only on the compose network. Scrape it from the observability stack (`infra/observability/`).
- `schemas/openapi/openapi.json` is guarded by `tests/unit/api/test_openapi_contract.py`; a route change without regenerating the snapshot fails the test suite (run `python tools/export_openapi.py`, then `pnpm --filter web gen:api`).
- A production `.env` file is absent by design. Create `infra/envs/revive.prod.env` from the template using a secret manager, and supply S3 credentials, a high-entropy JWT secret, worker token, and unique Postgres/Redis passwords; LLM provider credentials can be set here or in the admin Web settings. Compose supplies internal service URLs. Do not commit populated values.
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
