"""Project configuration package.

Importing the celery app here ensures shared_task decorators bind to it when
Django starts (the standard celery + Django wiring).
"""

from config.celery import app as celery_app

__all__ = ["celery_app"]
