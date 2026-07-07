# Copyright (c) Opendatalab. All rights reserved.
from __future__ import annotations

from collections.abc import Mapping

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
