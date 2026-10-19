"""LLM provenance and cost tracing (T-AG-07).

Every call is recorded as hashes plus usage so production can answer "why was
this patch changed and what did it cost" without ever persisting raw prompts by
default.  Full text is only retained when 'REVIVE_DEBUG_LLM=1', and even then
it is scrubbed by the secret regex first.  Persistence goes through an injected
'LLMCallPort' (the PG 'llm_calls' writer belongs to T-BE-02).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

logger = logging.getLogger("revive_agents.llm")

SECRET_RE = re.compile(r"(?:sk|key|token|api[_-]?key)[-_][A-Za-z0-9_\-]{8,}", re.IGNORECASE)


def content_hash(value: str | None) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def scrub(value: str) -> str:
    return SECRET_RE.sub("[REDACTED]", value or "")


def debug_llm() -> bool:
    return str(os.getenv("REVIVE_DEBUG_LLM", "")).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class LLMCallRecord:
    job_id: str
    node: str
    prompt_name: str
    prompt_version: str
    model: str
    request_hash: str
    response_hash: str
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd_estimate: float = 0.0
    raw_id: str = ""
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LLMCallPort(Protocol):
    async def record(self, record: LLMCallRecord) -> None: ...


def llm_record(
    job_id: str,
    node: str,
    prompt_name: str,
    version: str,
    model: str,
    usage: Any,
    latency: float,
    request: str,
    response: str,
) -> dict[str, Any]:
    """Hash-only record; kept as a plain dict for the PG writer and OTel span."""

    def _get(name: str, default: Any) -> Any:
        if isinstance(usage, dict):
            return usage.get(name, default)
        return getattr(usage, name, default)

    return {
        "job_id": job_id,
        "node": node,
        "prompt_name": prompt_name,
        "prompt_version": version,
        "model": model,
        "usage": {
            "input_tokens": int(_get("input_tokens", 0) or 0),
            "output_tokens": int(_get("output_tokens", 0) or 0),
            "cost_usd_estimate": float(_get("cost_usd_estimate", 0.0) or 0.0),
        },
        "latency": latency,
        "request_hash": content_hash(request),
        "response_hash": content_hash(response),
    }


class Tracer:
    """Fan-out to an optional OTel span factory and an injected call port."""

    def __init__(
        self,
        port: LLMCallPort | None = None,
        *,
        span_factory: Callable[[str, dict[str, Any]], Any] | None = None,
        debug: bool | None = None,
    ) -> None:
        self.port = port
        self.span_factory = span_factory
        self.debug = debug_llm() if debug is None else debug

    async def record(self, record: LLMCallRecord) -> None:
        if self.span_factory is not None:
            try:  # OTel is optional and never allowed to break the main chain
                with self.span_factory("llm.complete", record.to_dict()):
                    pass
            except Exception:  # pragma: no cover - defensive
                logger.warning("llm_span_emit_failed", exc_info=True)
        if self.port is not None:
            await self.port.record(record)

    def full_text(self, record: LLMCallRecord, request: str, response: str) -> dict[str, Any] | None:
        """Only available in debug mode; returned text is always scrubbed."""

        if not self.debug:
            return None
        payload = {
            "job_id": record.job_id,
            "node": record.node,
            "request": scrub(request),
            "response": scrub(response),
        }
        logger.info(
            "llm_debug_payload",
            extra={"job_id": record.job_id, "node": record.node},
        )
        return payload


class TracedProvider:
    """Wraps an LLMProvider and records hash-only provenance for every call."""

    def __init__(
        self,
        provider: Any,
        tracer: Tracer,
        *,
        job_id: str = "",
        node: str = "",
        prompt_name: str = "",
        prompt_version: str = "",
        model: str = "",
    ) -> None:
        self.provider = provider
        self.tracer = tracer
        self.job_id = job_id
        self.node = node
        self.prompt_name = prompt_name
        self.prompt_version = prompt_version
        self.model = model

    async def complete(
        self,
        messages: Sequence[dict[str, str]],
        *,
        response_format: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float = 30.0,
    ) -> Any:
        started = time.perf_counter()
        completion = await self.provider.complete(
            messages,
            response_format=response_format,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        request_text = json.dumps(list(messages), sort_keys=True, ensure_ascii=False)
        usage = getattr(completion, "usage", None)
        record = LLMCallRecord(
            job_id=self.job_id,
            node=self.node,
            prompt_name=self.prompt_name,
            prompt_version=self.prompt_version,
            model=self.model or getattr(self.provider, "model", "") or "",
            request_hash=content_hash(request_text),
            response_hash=content_hash(getattr(completion, "text", "")),
            latency_ms=latency_ms,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            cost_usd_estimate=float(getattr(usage, "cost_usd_estimate", 0.0) or 0.0),
            raw_id=str(getattr(completion, "raw_id", "") or ""),
        )
        await self.tracer.record(record)
        return completion
