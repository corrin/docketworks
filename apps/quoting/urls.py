from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views, views_scheduled_tasks

router = DefaultRouter()
router.register(
    r"scheduled-tasks",
    views_scheduled_tasks.ScheduledTaskViewSet,
    basename="scheduled-task",
)
router.register(
    r"scheduled-task-executions",
    views_scheduled_tasks.ScheduledTaskExecutionViewSet,
    basename="scheduled-task-execution",
)

urlpatterns = [
    path(
        "extract-supplier-price-list/",
        views.extract_supplier_price_list_data_view,
        name="extract_supplier_price_list_data",
    ),
] + router.urls
