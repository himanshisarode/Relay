"""Worker process: `python -m app.worker.main`. Separate from the API so slow SMTP never blocks requests."""

import logging
from datetime import UTC, datetime

from apscheduler.schedulers.blocking import BlockingScheduler

from app.main import _configure_logging
from app.worker.jobs import JOBS, run


def main() -> None:
    _configure_logging()
    sched = BlockingScheduler(timezone="UTC")
    for name, (_, seconds) in JOBS.items():
        # Jobs are idempotent, so running each one immediately at start-up is safe and catches up after downtime.
        sched.add_job(
            run,
            "interval",
            seconds=seconds,
            args=[name],
            id=name,
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(UTC),
        )
    logging.getLogger("relay.worker").info("worker started", extra={"extra_fields": {"jobs": list(JOBS)}})
    sched.start()


if __name__ == "__main__":
    main()
