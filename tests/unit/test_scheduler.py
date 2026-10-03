from unittest.mock import MagicMock
from apscheduler.triggers.cron import CronTrigger

from pymqttframework.scheduler import FrameworkScheduler, create_cron_trigger


def test_create_cron_trigger_formats() -> None:
    # 5 fields standard cron
    t5 = create_cron_trigger("*/15 * * * *")
    assert isinstance(t5, CronTrigger)

    # 6 fields Spring syntax (with seconds)
    t6 = create_cron_trigger("0 */15 * * * *")
    assert isinstance(t6, CronTrigger)


def test_scheduler_lifecycle() -> None:
    sched = FrameworkScheduler()
    callback = MagicMock()

    sched.setup_jobs(
        update_interval=10,
        cron_schedule="*/5 * * * *",
        update_callback=callback,
        initial_delay=1,
    )
    jobs = sched.get_jobs()
    job_ids = [j.id for j in jobs]
    assert "do_update_interval" in job_ids
    assert "do_update_cron" in job_ids

    info = sched.get_jobs_info()
    assert len(info) == 2
    assert any(item["id"] == "do_update_interval" for item in info)

    # Trigger manual update
    sched.trigger_update_now(update_interval=10, update_callback=callback)
    jobs_after = sched.get_jobs()
    job_ids_after = [j.id for j in jobs_after]
    assert "do_update_manual" in job_ids_after
    assert "do_update_interval" in job_ids_after
