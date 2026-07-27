from drf_spectacular.utils import extend_schema
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.models import Staff
from apps.job.permissions import IsOfficeStaff
from apps.workflow.enums import NotebookLmRestriction
from apps.workflow.models import NotebookLmLink
from apps.workflow.serializers import NotebookLmLinkSerializer


class NotebookLmLinkViewSet(viewsets.ModelViewSet[NotebookLmLink]):
    """CRUD for NotebookLM training-menu links.

    Full CRUD is office-staff gated (the admin management surface). The extra
    `menu` action is readable by any authenticated staff member and returns only
    the enabled links they are allowed to see — the navbar reads that, so the
    restriction filtering happens server-side.
    """

    permission_classes = [permissions.IsAuthenticated, IsOfficeStaff]
    queryset = NotebookLmLink.objects.all()
    serializer_class = NotebookLmLinkSerializer

    @extend_schema(responses={200: NotebookLmLinkSerializer(many=True)})
    @action(
        detail=False,
        methods=["get"],
        permission_classes=[permissions.IsAuthenticated],
    )
    def menu(self, request: Request) -> Response:
        user = request.user
        include_restricted = isinstance(user, Staff) and user.is_superuser
        links = NotebookLmLink.objects.filter(enabled=True)
        if not include_restricted:
            links = links.exclude(restriction=NotebookLmRestriction.SUPERUSER)
        serializer = self.get_serializer(links, many=True)
        return Response(serializer.data)
