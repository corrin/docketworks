"""
Procedure ViewSets and views.

Covers:
- ProcedureViewSet: CRUD for written documents (Google Doc-backed)
- ProcedureContentView: GET/PUT content from Google Docs
- JSA views: list/generate JSAs for jobs
- SWP/SOP generate views
- AI views: hazard/control generation, section/document improvement
"""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.models import Job
from apps.job.permissions import IsOfficeStaff
from apps.process.models import Procedure
from apps.process.serializers.procedure_serializer import (
    ProcedureCreateSerializer,
    ProcedureDetailSerializer,
    ProcedureListSerializer,
    ProcedureUpdateSerializer,
    SWPGenerateRequestSerializer,
)

# ─── Category → queryset filter mappings ──────────────────────────────────────

PROCEDURE_CATEGORIES = {
    "safety": {"document_type": "procedure", "tags": ["safety"]},
    "jsa": {"document_type": "procedure", "tags": ["jsa"]},
    "training": {"document_type": "procedure", "tags": ["training"]},
    "reference": {"document_type": "reference", "tags": []},
}


def _apply_category_filter(qs, category_map, category):
    """Apply category-specific filters to a queryset."""
    config = category_map.get(category)
    if config is None:
        return None

    qs = qs.select_related("job").filter(document_type=config["document_type"])

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


# ─── Procedure ViewSet ────────────────────────────────────────────────────────


class ProcedureViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    CRUD for procedure documents (Google Doc-backed written documents).

    Category is taken from the URL kwarg, e.g. /rest/procedures/safety/.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), IsOfficeStaff()]

    def get_serializer_class(self):
        if self.action == "list":
            return ProcedureListSerializer
        if self.action == "create":
            return ProcedureCreateSerializer
        if self.action in {"update", "partial_update"}:
            return ProcedureUpdateSerializer
        return ProcedureDetailSerializer

    def _get_category(self):
        return self.kwargs.get("category", "")

    def get_queryset(self):
        category = self._get_category()
        qs = _apply_category_filter(
            Procedure.objects.all(), PROCEDURE_CATEGORIES, category
        )
        if qs is None:
            return Procedure.objects.none()
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
                description="Filter by status (draft/active/completed/archived)",
                required=False,
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        category = self._get_category()
        if category not in PROCEDURE_CATEGORIES:
            return Response(
                {"error": f"Unknown procedure category: {category}"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        category = self._get_category()
        if category not in PROCEDURE_CATEGORIES:
            return Response(
                {"error": f"Unknown procedure category: {category}"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        request=ProcedureCreateSerializer,
        responses={201: ProcedureDetailSerializer},
    )
    def create(self, request, *args, **kwargs):
        category = self._get_category()
        if category not in PROCEDURE_CATEGORIES:
            return Response(
                {"error": f"Unknown procedure category: {category}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        ser = ProcedureCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        config = PROCEDURE_CATEGORIES[category]
        from apps.process.services.procedure_service import ProcedureService

        # Merge category tags with any user-supplied tags
        tags = list(ser.validated_data.get("tags") or [])
        for tag in config.get("tags", []):
            if tag not in tags:
                tags.append(tag)

        doc = ProcedureService().create_blank_procedure(
            document_type=config["document_type"],
            title=ser.validated_data["title"],
            document_number=ser.validated_data.get("document_number", ""),
            tags=tags,
            site_location=ser.validated_data.get("site_location", ""),
        )
        return Response(
            ProcedureDetailSerializer(doc).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        request=ProcedureUpdateSerializer,
        responses=ProcedureDetailSerializer,
    )
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        ser = ProcedureUpdateSerializer(instance, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ProcedureDetailSerializer(instance).data)

    @extend_schema(
        request=ProcedureUpdateSerializer,
        responses=ProcedureDetailSerializer,
    )
    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)


# ─── Content View ─────────────────────────────────────────────────────────────


class ProcedureContentResponseSerializer(serializers.Serializer):
    """Response when reading procedure content from Google Docs."""

    title = serializers.CharField()
    document_type = serializers.CharField()
    description = serializers.CharField()
    site_location = serializers.CharField()
    ppe_requirements = serializers.ListField(child=serializers.CharField())
    tasks = serializers.ListField()
    additional_notes = serializers.CharField()
    raw_text = serializers.CharField()


class ProcedureContentUpdateSerializer(serializers.Serializer):
    """Request body for updating procedure content in Google Docs."""

    title = serializers.CharField(required=False)
    site_location = serializers.CharField(required=False)
    description = serializers.CharField(required=False)
    ppe_requirements = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    tasks = serializers.ListField(required=False)
    additional_notes = serializers.CharField(required=False)


class ProcedureContentView(APIView):
    """
    GET/PUT content for a procedure stored in Google Docs.

    - GET: Fetch current content from Google Docs
    - PUT: Push updated content to Google Docs
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), IsOfficeStaff()]

    def _get_procedure(self, pk):
        doc = get_object_or_404(Procedure, pk=pk)
        if not doc.google_doc_id:
            return None, Response(
                {"error": "No Google Doc linked"}, status=status.HTTP_404_NOT_FOUND
            )
        return doc, None

    @extend_schema(responses=ProcedureContentResponseSerializer)
    def get(self, request, pk):
        doc, error_response = self._get_procedure(pk)
        if error_response:
            return error_response

        from apps.process.services.google_docs_service import GoogleDocsService

        content = GoogleDocsService().read_document(doc.google_doc_id)
        return Response(
            {
                "title": content.title,
                "document_type": content.document_type,
                "description": content.description,
                "site_location": content.site_location,
                "ppe_requirements": content.ppe_requirements,
                "tasks": content.tasks,
                "additional_notes": content.additional_notes,
                "raw_text": content.raw_text,
            }
        )

    @extend_schema(
        request=ProcedureContentUpdateSerializer,
        responses=ProcedureDetailSerializer,
    )
    def put(self, request, pk):
        doc, error_response = self._get_procedure(pk)
        if error_response:
            return error_response

        from apps.process.services.google_docs_service import GoogleDocsService

        GoogleDocsService().update_document(doc.google_doc_id, request.data)
        doc.title = request.data.get("title", doc.title)
        doc.site_location = request.data.get("site_location", doc.site_location)
        doc.save()
        return Response(ProcedureDetailSerializer(doc).data)


# ─── JSA views ────────────────────────────────────────────────────────────────


class JSAListView(APIView):
    """List all JSAs for a job."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=ProcedureListSerializer(many=True))
    def get(self, request, job_id):
        job = get_object_or_404(Job, pk=job_id)
        jsas = Procedure.objects.filter(job=job, tags__contains=["jsa"])
        return Response(ProcedureListSerializer(jsas, many=True).data)


class JSAGenerateView(APIView):
    """Generate a new JSA for a job."""

    permission_classes = [permissions.IsAuthenticated, IsOfficeStaff]

    @extend_schema(request=None, responses=ProcedureDetailSerializer)
    def post(self, request, job_id):
        job = get_object_or_404(Job, pk=job_id)
        from apps.process.services.procedure_service import ProcedureService

        jsa = ProcedureService().generate_jsa(job, staff=request.user)
        return Response(
            ProcedureDetailSerializer(jsa).data, status=status.HTTP_201_CREATED
        )


# ─── SWP/SOP Generate views ──────────────────────────────────────────────────


class SWPGenerateView(APIView):
    """Generate a new Safe Work Procedure."""

    permission_classes = [permissions.IsAuthenticated, IsOfficeStaff]

    @extend_schema(
        request=SWPGenerateRequestSerializer, responses=ProcedureDetailSerializer
    )
    def post(self, request):
        ser = SWPGenerateRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        from apps.process.services.procedure_service import ProcedureService

        swp = ProcedureService().generate_swp(**ser.validated_data)
        return Response(
            ProcedureDetailSerializer(swp).data, status=status.HTTP_201_CREATED
        )


class SOPGenerateRequestSerializer(serializers.Serializer):
    """Request body for generating a new SOP."""

    title = serializers.CharField()
    description = serializers.CharField(required=False, default="")
    document_number = serializers.CharField(required=False, default="")


class SOPGenerateView(APIView):
    """Generate a new Standard Operating Procedure."""

    permission_classes = [permissions.IsAuthenticated, IsOfficeStaff]

    @extend_schema(
        request=SOPGenerateRequestSerializer, responses=ProcedureDetailSerializer
    )
    def post(self, request):
        ser = SOPGenerateRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        from apps.process.services.procedure_service import ProcedureService

        sop = ProcedureService().generate_sop(**ser.validated_data)
        return Response(
            ProcedureDetailSerializer(sop).data, status=status.HTTP_201_CREATED
        )


# ─── AI views ─────────────────────────────────────────────────────────────────


class GenerateHazardsRequestSerializer(serializers.Serializer):
    task_description = serializers.CharField()


class GenerateHazardsResponseSerializer(serializers.Serializer):
    hazards = serializers.ListField(child=serializers.CharField())


class GenerateControlsRequestSerializer(serializers.Serializer):
    hazards = serializers.ListField(child=serializers.CharField())
    task_description = serializers.CharField(required=False, default="")


class GenerateControlsResponseSerializer(serializers.Serializer):
    controls = serializers.ListField(child=serializers.CharField())


class ImproveSectionRequestSerializer(serializers.Serializer):
    section_text = serializers.CharField()
    section_type = serializers.CharField()
    context = serializers.CharField(required=False, default="")


class ImproveSectionResponseSerializer(serializers.Serializer):
    improved_text = serializers.CharField()


class ImproveDocumentRequestSerializer(serializers.Serializer):
    raw_text = serializers.CharField()
    document_type = serializers.CharField(default="swp")


class ImproveDocumentResponseSerializer(serializers.Serializer):
    title = serializers.CharField()
    description = serializers.CharField()
    site_location = serializers.CharField()
    ppe_requirements = serializers.ListField(child=serializers.CharField())
    tasks = serializers.ListField()
    additional_notes = serializers.CharField()


class AIGenerateHazardsView(APIView):
    """Generate hazards for a task description using AI."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=GenerateHazardsRequestSerializer,
        responses=GenerateHazardsResponseSerializer,
    )
    def post(self, request):
        from apps.process.services.safety_ai_service import SafetyAIService

        hazards = SafetyAIService().generate_hazards(
            request.data.get("task_description", "")
        )
        return Response({"hazards": hazards})


class AIGenerateControlsView(APIView):
    """Generate controls for hazards using AI."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=GenerateControlsRequestSerializer,
        responses=GenerateControlsResponseSerializer,
    )
    def post(self, request):
        from apps.process.services.safety_ai_service import SafetyAIService

        controls = SafetyAIService().generate_controls(
            hazards=request.data.get("hazards", []),
            task_description=request.data.get("task_description", ""),
        )
        return Response({"controls": controls})


class AIImproveSectionView(APIView):
    """Improve a section of text using AI."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=ImproveSectionRequestSerializer,
        responses=ImproveSectionResponseSerializer,
    )
    def post(self, request):
        from apps.process.services.safety_ai_service import SafetyAIService

        text = SafetyAIService().improve_section(
            section_text=request.data.get("section_text", ""),
            section_type=request.data.get("section_type", ""),
            context=request.data.get("context", ""),
        )
        return Response({"improved_text": text})


class AIImproveDocumentView(APIView):
    """Improve an entire document using AI."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=ImproveDocumentRequestSerializer,
        responses=ImproveDocumentResponseSerializer,
    )
    def post(self, request):
        from apps.process.services.safety_ai_service import SafetyAIService

        improved = SafetyAIService().improve_document(
            raw_text=request.data.get("raw_text", ""),
            document_type=request.data.get("document_type", "swp"),
        )
        return Response(improved)
