# Stub file for django-eventstream's models (the package ships no py.typed).
# The mypy_django_plugin imports every INSTALLED_APPS models module while
# building its context, so these two tables need declarations even though no
# application code references them directly.
from django.db import models

class EventCounter(models.Model):
    id = models.AutoField(primary_key=True, serialize=False, verbose_name="ID")
    name = models.CharField(max_length=255, unique=True)
    value = models.BigIntegerField(default=0)
    updated = models.DateTimeField(db_index=True, auto_now=True)
    @classmethod
    def get_or_create(cls, name: str) -> EventCounter: ...

class Event(models.Model):
    id = models.AutoField(primary_key=True, serialize=False, verbose_name="ID")
    channel = models.CharField(max_length=255, db_index=True)
    type = models.CharField(max_length=255, db_index=True)
    data = models.TextField()
    eid = models.BigIntegerField(default=0, db_index=True)
    created = models.DateTimeField(db_index=True, auto_now_add=True)
    class Meta:
        unique_together = ("channel", "eid")
