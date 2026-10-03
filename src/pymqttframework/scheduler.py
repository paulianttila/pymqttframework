from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from threading import Lock
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import tzlocal

from pymqttframework.app import TriggerSource


def create_cron_trigger(cron_schedule: str) -> CronTrigger:
    """Create a CronTrigger supporting 5-field UNIX and 6-field Spring formats."""
    values = cron_schedule.split()
    if len(values) == 6:
        return CronTrigger(
            second=values[0],
            minute=values[1],
            hour=values[2],
            day=values[3],
            month=values[4],
            day_of_week=values[5],
        )
    return CronTrigger.from_crontab(cron_schedule)


class FrameworkScheduler:
    """Wrapper around APScheduler managing interval and cron tasks."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._scheduler = BackgroundScheduler(timezone=str(tzlocal.get_localzone()))
        self._lock = Lock()
        self._logger = logger or logging.getLogger(__name__)

    def setup_jobs(
        self,
        update_interval: int,
        cron_schedule: str | None,
        update_callback: Callable[[TriggerSource], None],
        initial_delay: int = 5,
    ) -> None:
        """Schedule initial interval and cron jobs."""
        if update_interval > 0:
            self._logger.debug(
                f"Schedule interval job to happen in every {update_interval} sec"
            )
            next_run_time = datetime.now() + timedelta(seconds=initial_delay)
            self._scheduler.add_job(
                update_callback,
                name="INTERVAL",
                trigger="interval",
                args=[TriggerSource.INTERVAL],
                id="do_update_interval",
                max_instances=1,
                seconds=update_interval,
                next_run_time=next_run_time,
                replace_existing=True,
            )

        if cron_schedule:
            self._logger.debug(f"Schedule cron job: {cron_schedule}")
            self._scheduler.add_job(
                update_callback,
                name="CRON_SCHEDULE",
                trigger=create_cron_trigger(cron_schedule),
                args=[TriggerSource.CRON],
                id="do_update_cron",
                max_instances=1,
                replace_existing=True,
            )

    def trigger_update_now(
        self,
        update_interval: int,
        update_callback: Callable[[TriggerSource], None],
    ) -> None:
        """Trigger an immediate manual update and reschedule next interval run."""
        with self._lock:
            self._scheduler.add_job(
                update_callback,
                trigger="date",
                args=[TriggerSource.MANUAL],
                id="do_update_manual",
                max_instances=1,
                next_run_time=datetime.now(),
                replace_existing=True,
            )
            if update_interval > 0:
                next_run = datetime.now() + timedelta(seconds=update_interval)
                if job := self._scheduler.get_job("do_update_interval"):
                    job.modify(next_run_time=next_run)
                else:
                    self._scheduler.add_job(
                        update_callback,
                        name="INTERVAL",
                        trigger="interval",
                        args=[TriggerSource.INTERVAL],
                        id="do_update_interval",
                        max_instances=1,
                        seconds=update_interval,
                        next_run_time=next_run,
                        replace_existing=True,
                    )

    def get_jobs_info(self) -> list[dict[str, str]]:
        """Return scheduled job information as serializable dictionaries."""
        return [
            {
                "id": str(job.id),
                "name": str(job.name),
                "trigger": str(job.trigger),
                "next_run": str(getattr(job, "next_run_time", None)),
            }
            for job in self._scheduler.get_jobs()
        ]

    def get_jobs(self) -> list[Any]:
        """Return list of scheduled APScheduler jobs."""
        return self._scheduler.get_jobs()

    def start(self) -> None:
        """Start the background scheduler."""
        self._scheduler.start()

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the background scheduler."""
        self._scheduler.shutdown(wait=wait)
