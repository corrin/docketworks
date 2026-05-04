# Events & Queues

- `set_paid_flag_task` [queue] → celery-task — `apps/job/tasks.py`
- `auto_archive_completed_jobs_task` [queue] → celery-task — `apps/job/tasks.py`
- `recompute_workshop_schedule_task` [queue] → celery-task — `apps/operations/tasks.py`
- `run_all_scrapers_task` [queue] → celery-task — `apps/quoting/tasks.py`
- `celery_health_check` [queue] → celery-task — `apps/workflow/tasks.py`
- `process_xero_webhook_event` [queue] → celery-task — `apps/workflow/tasks.py`
- `xero_heartbeat_task` [queue] → celery-task — `apps/workflow/tasks.py`
- `xero_regular_sync_task` [queue] → celery-task — `apps/workflow/tasks.py`
- `xero_30_day_sync_task` [queue] → celery-task — `apps/workflow/tasks.py`
