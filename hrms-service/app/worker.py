"""Background worker: runs queued employee import jobs and the generic background jobs (contract A10):
attendance recalculation, the nightly attendance day close, the daily shift sync and workflow
escalation. The scheduled ones are queued by the worker itself (at most once per minute; each has a
dedupe key, so several workers never queue the same job twice).

    python -m app.worker

Run at least one worker next to the API. Several workers may run at once: each job is claimed with
SELECT … FOR UPDATE SKIP LOCKED, and a worker sends heartbeats while it works. A job whose
heartbeat is older than WORKER_STALE_SECONDS (its worker stopped) is taken over and resumed after
its last committed batch. Stop with SIGTERM/SIGINT: the current batch finishes first.
"""

import asyncio
import logging
import os
import signal
import socket

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.database.session import dispose_engine, get_session_factory
import time

from app.services.attendance.jobs import claim_background_job, run_background_job, schedule_periodic
from app.services.import_job_runner import claim_next_job, run_job

logger = logging.getLogger("hrms.worker")


SCHEDULE_EVERY_SECONDS = 60
_last_schedule = 0.0


async def run_once(worker_id: str) -> bool:
    """Queues due scheduled jobs, then claims and runs one job; False when there was nothing to do."""
    global _last_schedule
    factory = get_session_factory()
    if time.monotonic() - _last_schedule >= SCHEDULE_EVERY_SECONDS:
        async with factory() as session:
            await schedule_periodic(session)
        _last_schedule = time.monotonic()
    async with factory() as session:
        job_id = await claim_next_job(session, worker_id)
    if job_id is not None:
        logger.info("running employee import job %s", job_id)
        async with factory() as session:
            await run_job(session, job_id)
        return True
    async with factory() as session:
        job_id = await claim_background_job(session, worker_id)
    if job_id is not None:
        logger.info("running background job %s", job_id)
        async with factory() as session:
            await run_background_job(session, job_id)
        return True
    return False


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    logger.info("worker %s started", worker_id)
    try:
        while not stop.is_set():
            try:
                worked = await run_once(worker_id)
            except Exception:  # noqa: BLE001 - keep the worker alive; the job itself records failures
                logger.exception("worker loop error")
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
                except asyncio.TimeoutError:
                    pass
    finally:
        await dispose_engine()
        logger.info("worker %s stopped", worker_id)


if __name__ == "__main__":
    asyncio.run(main())
