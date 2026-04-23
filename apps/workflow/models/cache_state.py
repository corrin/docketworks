from django.db import models
from django.utils import timezone


class CacheState(models.Model):
    # Records whether solo-cache invalidation is currently forced for every
    # request. Set by POST /api/disable_cache/ with an auto-resume time so a
    # crashed E2E run can't leave caching off forever. Plain Model (not
    # SingletonModel) so every worker reads the current DB row — using
    # django-solo here would re-introduce the per-worker caching problem
    # this table exists to bypass.
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    disabled_until = models.DateTimeField(null=True, blank=True)

    @classmethod
    def current(cls) -> "CacheState":
        row, _ = cls.objects.get_or_create(pk=1)
        return row

    @classmethod
    def is_disabled(cls) -> bool:
        row = cls.current()
        if not row.disabled_until:
            return False
        return timezone.now() < row.disabled_until
