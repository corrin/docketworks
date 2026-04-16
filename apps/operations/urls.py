from django.urls import path

from apps.operations.views.workshop_schedule_view import (
    WorkshopScheduleRecalculateView,
    WorkshopScheduleView,
)

app_name = "operations"

urlpatterns = [
    path(
        "workshop-schedule/",
        WorkshopScheduleView.as_view(),
        name="workshop-schedule",
    ),
    path(
        "workshop-schedule/recalculate/",
        WorkshopScheduleRecalculateView.as_view(),
        name="workshop-schedule-recalculate",
    ),
]
