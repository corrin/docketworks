from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.accounts.permissions import CanManageTimesheets


class TimesheetBaseView(APIView):
    """Base view for all timesheet endpoints. Requires superuser access."""

    permission_classes = [IsAuthenticated, CanManageTimesheets]
