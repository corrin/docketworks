from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView

urlpatterns = [
    path("api/", include("apps.workflow.urls")),
    path("api/job/", include("apps.job.urls", namespace="jobs")),
    path("api/accounts/", include("apps.accounts.urls")),
    path("api/timesheets/", include("apps.timesheet.urls")),
    path(
        "api/quoting/", include(("apps.quoting.urls", "quoting"), namespace="quoting")
    ),
    path("api/clients/", include("apps.client.urls_rest", namespace="clients")),
    path("api/purchasing/", include("apps.purchasing.urls", namespace="purchasing")),
    path("api/accounting/", include("apps.accounting.urls", namespace="accounting")),
    path("api/process/", include("apps.process.urls", namespace="process")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
