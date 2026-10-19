"""ReviveOS command line entrypoint.

The CLI is intentionally a thin orchestration layer. Archaeology, sandbox
execution, scoring and capsule verification remain in revive_core; the commands
here only select a backend, render results and map failures to stable exit codes.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import typer
from revive_core import schemas
from revive_core.archaeology import PypiClient, build_timeline, extract_evidence, fetch_repo, infer_genome
from revive_core.capsule.replay import replay as replay_capsule
from revive_core.capsule.verify import verify as verify_capsule
from revive_core.sandbox.executor import NullEventPort, sandbox_tmpdir
from revive_core.sandbox.port_impl import DockerExecutionPort, LocalExecutionPort, docker_available
from rich.console import Console

from .auth import Credentials, CredentialStore
from .client import ReviveClient
from .jobs import event_type, render_event
from .local_pipeline import LLMRepairPolicy, PipelineConfig, PipelinePorts, assemble_pipeline
from .render import render_genome, render_json, render_pipeline

app = typer.Typer(
    name="revive",
    help="ReviveOS software runtime resurrection and reproducibility CLI.",
    no_args_is_help=True,
    add_completion=False,
)
jobs_app = typer.Typer(help="Inspect server-side resurrection jobs.", no_args_is_help=True)
app.add_typer(jobs_app, name="jobs")
console = Console()


def _fail(message: str, code: int = 1) -> None:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(code)


def _server_url(explicit: str | None, credentials: Credentials | None = None) -> str:
    value = explicit or (credentials.server if credentials else "") or os.environ.get("REVIVE_SERVER_URL", "")
    if not value:
        _fail("a server URL is required (pass --server or set REVIVE_SERVER_URL)", 2)
    return value.rstrip("/")


def _client(server: str | None) -> tuple[ReviveClient, CredentialStore]:
    store = CredentialStore()
    credentials = store.load()
    client = ReviveClient(
        _server_url(server, credentials),
        access_token=credentials.access_token,
        refresh_token=credentials.refresh_token,
        api_key=credentials.api_key,
    )
    return client, store


def _persist_client_credentials(client: ReviveClient, store: CredentialStore) -> None:
    """Persist rotated tokens so one-time refresh tokens are not lost."""
    current = store.load()
    store.save(
        Credentials(
            access_token=client.access_token,
            refresh_token=client.refresh_token,
            server=client.base_url,
            api_key=current.api_key,
            extra=current.extra,
        )
    )


def _json_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump(mode="json"))
    return {"value": value}


@app.command()
def analyze(
    url: str = typer.Argument(..., help="GitHub repository URL or local repository path."),  # noqa: B008
    out: Path | None = typer.Option(None, "--out", help="Write the schema-valid genome JSON here."),  # noqa: B008
    offline: bool = typer.Option(False, "--offline", help="Do not query PyPI for historical releases."),  # noqa: B008
) -> None:
    """Analyze a repository and print its inferred environment genome."""
    work = sandbox_tmpdir("revive-analyze-")
    destination = work / "repo"
    pypi: PypiClient | None = None
    try:
        mirror = fetch_repo(url, destination)
        evidence = extract_evidence(mirror.path, commit_sha=mirror.head_commit)
        timeline = build_timeline(mirror)
        if not offline:
            pypi = PypiClient(offline=False)
        genome = infer_genome(evidence, timeline, pypi, offline=offline)
        payload = genome.model_dump(mode="json", exclude_none=True)
        schemas.validate(payload, "genome")
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(str(exc), 2)
    finally:
        if pypi is not None:
            pypi.close()

    if out is not None:
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            _fail(f"could not write {out}: {exc}", 2)
    render_genome(payload, console)
    if float(payload.get("overall_confidence", 0.0)) < 0.4:
        _fail("evidence is insufficient (overall_confidence < 0.4)", 3)


def _make_execution_port(
    *,
    work_root: Path,
    source: Path | None,
    job_id: str,
    keep_sandbox: bool,
    events: Any = None,
) -> Any:
    """Select Docker in a capable host, otherwise the explicit local substitute."""
    available, _reason = docker_available()
    if available:
        return DockerExecutionPort(
            workspace=source,
            job_id=job_id,
            keep_sandbox=keep_sandbox,
            base_dir=work_root / "docker",
            events=events,
        )
    return LocalExecutionPort(
        workspace=work_root / "sandbox",
        source=source,
        job_id=job_id,
        ephemeral=not keep_sandbox,
        events=events,
    )


async def _run_local_pipeline(
    repo_url: str,
    *,
    budget_usd: float,
    timeout: float,
    keep_sandbox: bool,
    out: Path | None,
    work_root: Path | None,
) -> Any:
    root = work_root or sandbox_tmpdir("revive-local-run-")
    root.mkdir(parents=True, exist_ok=True)
    source = Path(repo_url).expanduser() if not repo_url.startswith(("http://", "https://")) else None
    if source is not None and source.name == ".git":
        source = source.parent
    job_id = f"local-{os.getpid()}"
    event_port = NullEventPort()
    execution = _make_execution_port(
        work_root=root,
        source=source if source is not None and source.exists() else None,
        job_id=job_id,
        keep_sandbox=keep_sandbox,
        events=event_port,
    )
    provider: Any = None
    repair_policy: Any = None
    try:
        try:
            from revive_agents.llm.factory import from_config

            provider = from_config()
            repair_policy = LLMRepairPolicy(provider)
        except Exception:
            provider = None
            repair_policy = None
        config = PipelineConfig(
            repo_url=repo_url,
            job_id=job_id,
            work_root=str(root),
            out_path=str(out) if out else None,
            timeout=timeout,
            keep_sandbox=keep_sandbox,
            budget_usd=budget_usd,
        )
        pipeline = assemble_pipeline(
            config,
            PipelinePorts(execution=execution, events=event_port, provider=provider, repair_policy=repair_policy),
        )
        return await pipeline.run()
    finally:
        close = getattr(execution, "close", None)
        if callable(close):
            await close()


@app.command()
def resurrect(
    repo_url: str = typer.Argument(..., help="Repository URL or local path to resurrect."),  # noqa: B008
    local: bool = typer.Option(False, "--local", help="Run the transparent local pipeline."),  # noqa: B008
    server: str | None = typer.Option(None, "--server", help="Control-plane URL for server mode."),  # noqa: B008
    budget_usd: float = typer.Option(0.0, "--budget-usd", min=0.0, help="Maximum LLM budget."),  # noqa: B008
    timeout: float = typer.Option(300.0, "--timeout", min=0.1, help="Pipeline timeout in seconds."),  # noqa: B008
    keep_sandbox: bool = typer.Option(False, "--keep-sandbox", help="Keep the local sandbox workspace."),  # noqa: B008
    out: Path | None = typer.Option(None, "--out", help="Output .revive path in local mode."),  # noqa: B008
    work_root: Path | None = typer.Option(None, "--work-root", help="Scratch root for local mode."),  # noqa: B008
) -> None:
    """Resurrect a repository locally or submit it to the control plane."""
    if local:
        try:
            result = asyncio.run(
                _run_local_pipeline(
                    repo_url,
                    budget_usd=budget_usd,
                    timeout=timeout,
                    keep_sandbox=keep_sandbox,
                    out=out,
                    work_root=work_root,
                )
            )
        except typer.Exit:
            raise
        except Exception as exc:
            _fail(str(exc), 2)
        render_pipeline(result, console)
        if result.status == "dead":
            raise typer.Exit(1)
        return

    client, store = _client(server)
    try:
        job = client.submit_resurrection(
            repo_url,
            budget_usd=budget_usd,
            timeout=timeout,
            keep_sandbox=keep_sandbox,
        )
        terminal: str | None = None
        for item in client.stream_events(job.id):
            payload = item.json()
            event = payload if isinstance(payload, Mapping) else {"event": item.event, "data": item.data}
            render_event(event, console)
            kind = event_type(event)
            if kind in {"job.succeeded", "job.failed"}:
                terminal = kind
                break
        if client.access_token != store.load().access_token or client.refresh_token != store.load().refresh_token:
            _persist_client_credentials(client, store)
        if terminal == "job.failed":
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(str(exc), 2)
    finally:
        client.close()


@app.command()
def verify(
    capsule: Path = typer.Argument(..., exists=True, readable=True, help="Path to a .revive capsule."),  # noqa: B008
    json_output: bool = typer.Option(False, "--json", help="Print the machine-readable report."),  # noqa: B008
) -> None:
    """Check capsule schema and content digests, then run available rebuild checks."""
    try:
        report = asyncio.run(verify_capsule(capsule))
    except Exception as exc:
        _fail(str(exc), 2)
    payload = _json_mapping(report)
    render_json(payload, console)
    raise typer.Exit(int(payload.get("exit_code", 2)))


@app.command()
def replay(
    capsule: Path = typer.Argument(..., exists=True, readable=True, help="Path to a .revive capsule."),  # noqa: B008
    command: list[str] = typer.Argument(None, help="Command to run inside the replay workspace."),  # noqa: B008
) -> None:
    """Re-enter a capsule workspace and run a command."""

    async def _run() -> Any:
        workspace = sandbox_tmpdir("revive-replay-cli-")
        execution = LocalExecutionPort(workspace=workspace, ephemeral=True, offline=True)
        try:
            return await replay_capsule(capsule, execution, argv=command or None, workspace=workspace)
        finally:
            await execution.close()

    try:
        result = asyncio.run(_run())
    except Exception as exc:
        _fail(str(exc), 2)
    if result.stdout:
        typer.echo(result.stdout, nl=not result.stdout.endswith("\n"))
    if result.stderr:
        typer.echo(result.stderr, err=True, nl=not result.stderr.endswith("\n"))
    raise typer.Exit(int(result.exit_code))


@app.command()
def login(
    server: str | None = typer.Option(None, "--server", help="Control-plane URL."),
    token: str | None = typer.Option(None, "--token", help="Paste an access token."),
    email: str | None = typer.Option(None, "--email"),
    password: str | None = typer.Option(None, "--password"),
) -> None:
    """Save a control-plane token in the OS keyring or a 0600 fallback file."""
    store = CredentialStore()
    current = store.load()
    selected_server = _server_url(server, current)
    if token:
        credentials = Credentials(access_token=token, server=selected_server)
    elif email and password:
        client = ReviveClient(selected_server)
        try:
            payload = client.login_password(email, password)
        except Exception as exc:
            _fail(str(exc), 2)
        finally:
            client.close()
        credentials = Credentials(
            access_token=str(payload.get("access_token", "")),
            refresh_token=str(payload.get("refresh_token", "")),
            server=selected_server,
        )
    else:
        _fail("pass --token or both --email and --password", 2)
    location = store.save(credentials)
    typer.echo(f"credentials saved ({location})")


@jobs_app.command("ls")
def jobs_list(server: str | None = typer.Option(None, "--server")) -> None:
    """List server-side jobs."""
    client, store = _client(server)
    try:
        for job in client.list_jobs():
            typer.echo(f"{job.id}\t{job.status}\t{job.repo}")
    except Exception as exc:
        _fail(str(exc), 2)
    finally:
        _persist_client_credentials(client, store)
        client.close()


@jobs_app.command("get")
def jobs_get(job_id: str = typer.Argument(...), server: str | None = typer.Option(None, "--server")) -> None:
    """Get one server-side job."""
    client, store = _client(server)
    try:
        job = client.get_job(job_id)
        render_json(job.__dict__, console)
    except Exception as exc:
        _fail(str(exc), 2)
    finally:
        _persist_client_credentials(client, store)
        client.close()


@app.command()
def download(
    job_id: str = typer.Argument(...),  # noqa: B008
    output: Path = typer.Option(..., "-o", "--output", help="Destination .revive file."),  # noqa: B008
    server: str | None = typer.Option(None, "--server"),  # noqa: B008
) -> None:
    """Download a completed server-side capsule."""
    client, store = _client(server)
    try:
        path = client.download_capsule(job_id, output)
        typer.echo(str(path))
    except Exception as exc:
        _fail(str(exc), 2)
    finally:
        _persist_client_credentials(client, store)
        client.close()


if __name__ == "__main__":
    app()


__all__ = ["app", "jobs_app"]
