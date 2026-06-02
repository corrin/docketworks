"""
Form ViewSets and views.

Covers:
- FormViewSet: CRUD for form/register definitions
- FormEntryViewSet: CRUD for entries within forms
- FormFillView: Create a FormEntry from a Form definition
- FormCompleteView: Mark a FormEntry as completed
"""

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.permissions import IsOfficeStaff
from apps.process.models import Form, FormEntry
from apps.process.serializers.form_serializer import (
    FormCreateSerializer,
    FormDetailSerializer,
    FormEntrySerializer,
    FormListSerializer,
    FormUpdateSerializer,
)
from apps.workflow.services.error_persistence import persist_app_error

# ─── Category → queryset filter mappings ──────────────────────────────────────

FORM_CATEGORIES = {
    "safety": {
        "document_type": "form",
        "tags_any": ["safety", "inspection", "hazard-id", "maintenance"],
    },
    "training": {"document_type": "form", "tags": ["training"]},
    "incident": {"document_type": "form", "tags": ["incident"]},
    "meeting": {
        "document_type": "form",
        "tags_any": ["meeting", "administration"],
    },
    "register": {"document_type": "register", "tags": []},
}


def _apply_category_filter(qs, category_map, category):
    """Apply category-specific filters to a queryset."""
    config = category_map.get(category)
    if config is None:
        return None

    qs = qs.filter(document_type=config["document_type"])

    if tags := config.get("tags"):
        for tag in tags:
            qs = qs.filter(tags__contains=[tag])
    elif tags_any := config.get("tags_any"):
        tag_q = Q()
        for tag in tags_any:
            tag_q |= Q(tags__contains=[tag])
        qs = qs.filter(tag_q)

    return qs


def _apply_common_filters(qs, request):
    """Apply shared query-param filters (q, tags, status)."""
    if query := request.query_params.get("q"):
        qs = qs.filter(title__icontains=query)
    if tags_param := request.query_params.get("tags"):
        for tag in tags_param.split(","):
            tag = tag.strip()
            if tag:
                qs = qs.filter(tags__contains=[tag])
    if status_param := request.query_params.get("status"):
        qs = qs.filter(status=status_param)
    return qs


# ─── Form ViewSet ─────────────────────────────────────────────────────────────


class FormViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    CRUD for form/register definitions (fillable templates with entries, no Google Docs).

    Category is taken from the URL kwarg, e.g. /rest/forms/safety/.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), IsOfficeStaff()]

    def get_serializer_class(self):
        if self.action == "list":
            return FormListSerializer
        if self.action == "create":
            return FormCreateSerializer
        if self.action in {"update", "partial_update"}:
            return FormUpdateSerializer
        return FormDetailSerializer

    def get_queryset(self):
        category = self.kwargs.get("category", "")
        qs = _apply_category_filter(Form.objects.all(), FORM_CATEGORIES, category)
        if qs is None:
            return Form.objects.none()
        qs = qs.annotate(entry_count=Count("entries"))
        return _apply_common_filters(qs, self.request)

    @extend_schema(
        parameters=[
            OpenApiParameter(name="q", description="Search by title", required=False),
            OpenApiParameter(
                name="tags",
                description="Comma-separated tags; ALL must match",
                required=False,
            ),
            OpenApiParameter(
                name="status",
                description="Filter by status (active/archived)",
                required=False,
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        category = self.kwargs.get("category", "")
        if category not in FORM_CATEGORIES:
            return Response(
                {"error": f"Unknown form category: {category}"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        category = self.kwargs.get("category", "")
        if category not in FORM_CATEGORIES:
            return Response(
                {"error": f"Unknown form category: {category}"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        request=FormCreateSerializer,
        responses={201: FormDetailSerializer},
    )
    def create(self, request, *args, **kwargs):
        category = self.kwargs.get("category", "")
        if category not in FORM_CATEGORIES:
            return Response(
                {"error": f"Unknown form category: {category}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        ser = FormCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        config = FORM_CATEGORIES[category]
        from apps.process.services.form_service import FormService

        # Merge category tags with any user-supplied tags
        tags = list(ser.validated_data.get("tags") or [])
        # For tags_any categories, add only the primary tag (first in list)
        for tag in config.get("tags", config.get("tags_any", []))[:1]:
            if tag not in tags:
                tags.append(tag)

        doc = FormService().create_form(
            document_type=config["document_type"],
            title=ser.validated_data["title"],
            document_number=ser.validated_data.get("document_number", ""),
            tags=tags,
            form_schema=ser.validated_data.get("form_schema", {}),
        )
        return Response(FormDetailSerializer(doc).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=FormUpdateSerializer,
        responses=FormDetailSerializer,
    )
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        ser = FormUpdateSerializer(instance, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(FormDetailSerializer(instance).data)

    @extend_schema(
        request=FormUpdateSerializer,
        responses=FormDetailSerializer,
    )
    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)


# ─── Entry ViewSet ────────────────────────────────────────────────────────────


class FormEntryViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    CRUD endpoints for FormEntry, nested under a form document.

    Endpoints:
    - GET    /rest/forms/<category>/<id>/entries/              - list entries
    - POST   /rest/forms/<category>/<id>/entries/              - create entry
    - PUT    /rest/forms/<category>/<id>/entries/<entry_id>/   - update entry
    - DELETE /rest/forms/<category>/<id>/entries/<entry_id>/   - delete entry
    """

    serializer_class = FormEntrySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_form(self):
        return get_object_or_404(Form, pk=self.kwargs["document_pk"])

    def get_queryset(self):
        return (
            FormEntry.objects.filter(
                form_id=self.kwargs["document_pk"],
                is_active=True,
            )
            .select_related("job")
            .order_by("-entry_date", "-created_at")
        )

    def perform_destroy(self, instance):
        """Soft delete — set is_active=False instead of actually deleting."""
        instance.is_active = False
        instance.save(update_fields=["is_active"])

    @extend_schema(responses=FormEntrySerializer(many=True))
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=FormEntrySerializer,
        responses={201: FormEntrySerializer},
    )
    def create(self, request, *args, **kwargs):
        form = self.get_form()
        ser = FormEntrySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save(form=form, entered_by=request.user)
        return Response(
            FormEntrySerializer(ser.instance).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=FormEntrySerializer,
        responses=FormEntrySerializer,
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(
        request=FormEntrySerializer,
        responses=FormEntrySerializer,
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)


# ─── Fill / Complete views ────────────────────────────────────────────────────


class FormFillView(APIView):
    """Create a new FormEntry from a Form definition."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=inline_serializer(
            "FillRequest",
            fields={
                "job_id": serializers.UUIDField(required=False, allow_null=True),
                "entry_date": serializers.DateField(required=False),
                "data": serializers.JSONField(required=False),
            },
        ),
        responses=FormEntrySerializer,
    )
    def post(self, request, pk, **kwargs):
        try:
            from apps.process.services.form_service import FormService

            entry = FormService().create_entry(
                form_id=pk,
                job_id=request.data.get("job_id"),
                entered_by=request.user,
                entry_date=request.data.get("entry_date"),
                data=request.data.get("data"),
            )
            return Response(
                FormEntrySerializer(entry).data,
                status=status.HTTP_201_CREATED,
            )
        except Exception as exc:
            persist_app_error(exc)
            raise
