# Copyright (c) Opendatalab. All rights reserved.
from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar, Token
from contextlib import contextmanager
import time
from typing import Iterator

from prometheus_client import Counter, Gauge, Histogram

docs_parsed_total = Counter(
    "mineru_docs_parsed_total",
    "Documents parsed by the API server, by tier and terminal status.",
    ["tier", "status"],
)

doc_parse_seconds = Histogram(
    "mineru_doc_parse_seconds",
    "Wall-clock seconds for one parser execution.",
    ["tier"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600),
)

doc_pages = Histogram(
    "mineru_doc_pages",
    "Number of pages per parsed document.",
    ["tier"],
    buckets=(1, 5, 10, 20, 50, 100, 200, 500, 1000),
)

blocks_total = Counter(
    "mineru_blocks_total",
    "Content blocks produced, by tier and block type.",
    ["tier", "block_type"],
)

vlm_prompts_total = Counter(
    "mineru_vlm_prompts_total",
    "Approximate VLM prompt volume, counted as pages sent through the VLM path.",
    ["effort"],
)

jobs_inflight = Gauge(
    "mineru_jobs_inflight",
    "Currently running parse files across asynchronous jobs and synchronous parses.",
)

_phase_tier: ContextVar[object | None] = ContextVar("mineru_phase_tier", default=None)
_phase_effort: ContextVar[object | None] = ContextVar("mineru_phase_effort", default=None)
_phase_backend: ContextVar[object | None] = ContextVar("mineru_phase_backend", default=None)

parse_phase_seconds = Histogram(
    "mineru_parse_phase_seconds",
    "Wall-clock seconds spent in parse pipeline phases.",
    ["tier", "effort", "backend", "phase", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 60, 120, 300),
)

parse_phase_events_total = Counter(
    "mineru_parse_phase_events_total",
    "Parse pipeline phase executions by status.",
    ["tier", "effort", "backend", "phase", "status"],
)


def _label(value: object | None) -> str:
    return str(value) if value not in (None, "") else "unknown"


def bind_phase_labels(
    *,
    tier: object | None = None,
    effort: object | None = None,
    backend: object | None = None,
) -> tuple[Token[object | None], Token[object | None], Token[object | None]]:
    return (
        _phase_tier.set(tier if tier is not None else _phase_tier.get()),
        _phase_effort.set(effort if effort is not None else _phase_effort.get()),
        _phase_backend.set(backend if backend is not None else _phase_backend.get()),
    )


def reset_phase_labels(tokens: tuple[Token[object | None], Token[object | None], Token[object | None]]) -> None:
    tier_token, effort_token, backend_token = tokens
    _phase_backend.reset(backend_token)
    _phase_effort.reset(effort_token)
    _phase_tier.reset(tier_token)


@contextmanager
def phase_timer(
    phase: str,
    *,
    tier: object | None = None,
    effort: object | None = None,
    backend: object | None = None,
) -> Iterator[None]:
    labels = {
        "tier": _label(tier if tier is not None else _phase_tier.get()),
        "effort": _label(effort if effort is not None else _phase_effort.get()),
        "backend": _label(backend if backend is not None else _phase_backend.get()),
        "phase": phase,
    }
    started = time.monotonic()
    try:
        yield
    except Exception:
        elapsed = time.monotonic() - started
        parse_phase_seconds.labels(**labels, status="error").observe(elapsed)
        parse_phase_events_total.labels(**labels, status="error").inc()
        raise
    elapsed = time.monotonic() - started
    parse_phase_seconds.labels(**labels, status="success").observe(elapsed)
    parse_phase_events_total.labels(**labels, status="success").inc()


def record_doc_result(*, tier: str, status: str, elapsed: float, page_count: int) -> None:
    docs_parsed_total.labels(tier=tier, status=status).inc()
    doc_parse_seconds.labels(tier=tier).observe(elapsed)
    doc_pages.labels(tier=tier).observe(page_count)


def record_blocks(tier: str, block_type_counts: Mapping[str, int]) -> None:
    for block_type, count in block_type_counts.items():
        if count:
            blocks_total.labels(tier=tier, block_type=block_type).inc(count)


def record_vlm_prompts(effort: str, count: int) -> None:
    if count:
        vlm_prompts_total.labels(effort=effort).inc(count)
