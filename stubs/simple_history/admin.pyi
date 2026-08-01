from typing import TypeVar

from django.contrib.admin import ModelAdmin
from django.db import models
from django.http import HttpRequest, HttpResponse

_M = TypeVar("_M", bound=models.Model)

class SimpleHistoryAdmin(ModelAdmin[_M]):
    def history_form_view(
        self, request: HttpRequest, object_id: str, version_id: str
    ) -> HttpResponse: ...
