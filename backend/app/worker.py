from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from types import SimpleNamespace

from app.config import settings
from app.connectors.http import SafeHttpClient
from app.db import SessionLocal
from app.services.matching import HybridMatcher
from app.services.scans import (
    enqueue_due_scans,
    execute_scan,
    next_queued_scan_id,
    recover_interrupted_runs,
)

logger = logging.getLogger(__name__)


def create_runtime():
    return SimpleNamespace(
        state=SimpleNamespace(
            session_factory=SessionLocal,
            http=SafeHttpClient(),
            matcher=HybridMatcher(settings),
            scan_tasks={},
        )
    )


async def run_worker_once(runtime, now: datetime | None = None) -> bool:
    with runtime.state.session_factory() as session:
        enqueue_due_scans(session, now)
        scan_id = next_queued_scan_id(session)
    if not scan_id:
        return False
    await execute_scan(scan_id, runtime)
    return True


async def drain_worker(runtime, now: datetime | None = None) -> int:
    processed = 0
    while await run_worker_once(runtime, now):
        processed += 1
    return processed


async def worker_loop() -> None:
    runtime = create_runtime()
    with runtime.state.session_factory() as session:
        recovered = recover_interrupted_runs(session)
    if recovered:
        logger.warning("Recovered %s interrupted scan(s)", recovered)
    try:
        while True:
            worked = await run_worker_once(runtime)
            if not worked:
                await asyncio.sleep(settings.worker_poll_seconds)
    finally:
        await runtime.state.http.close()
        await runtime.state.matcher.close()


async def worker_until_idle() -> int:
    runtime = create_runtime()
    with runtime.state.session_factory() as session:
        recovered = recover_interrupted_runs(session)
    if recovered:
        logger.warning("Recovered %s interrupted scan(s)", recovered)
    try:
        processed = await drain_worker(runtime)
    finally:
        await runtime.state.http.close()
        await runtime.state.matcher.close()
    return processed


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(worker_loop())
    except KeyboardInterrupt:
        pass


def once_main() -> None:
    logging.basicConfig(level=logging.INFO)
    processed = asyncio.run(worker_until_idle())
    logger.info("Worker finished after processing %s scan(s)", processed)


if __name__ == "__main__":
    main()
