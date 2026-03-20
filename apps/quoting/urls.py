from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views, views_django_jobs

router = DefaultRouter()
router.register(
    r"django-jobs",
    views_django_jobs.DjangoJobViewSet,
    basename="django-job",
)
router.register(
    r"django-job-executions",
    views_django_jobs.DjangoJobExecutionViewSet,
    basename="django-job-execution",
)

urlpatterns = [
    path(
        "extract-supplier-price-list/",
        views.extract_supplier_price_list_data_view,
        name="extract_supplier_price_list_data",
    ),
] + router.urls
