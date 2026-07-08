"""
Serializers for Kanban views.
"""

from rest_framework import serializers


class JobReorderSerializer(serializers.Serializer):
    """Serializer for job reorder request data."""

    anchor_job_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Visible job used as the reorder anchor",
    )
    placement = serializers.ChoiceField(
        choices=["above", "below"],
        required=False,
        allow_null=True,
        help_text="Place the moved job above or below anchor_job_id",
    )
    status = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="New status if moving between columns",
    )

    def validate(self, attrs):
        anchor_job_id = attrs.get("anchor_job_id")
        placement = attrs.get("placement")

        if anchor_job_id and not placement:
            raise serializers.ValidationError(
                {"placement": "placement is required when anchor_job_id is supplied"}
            )
        if placement and not anchor_job_id:
            raise serializers.ValidationError(
                {
                    "anchor_job_id": "anchor_job_id is required when placement is supplied"
                }
            )

        return attrs


class JobStatusUpdateSerializer(serializers.Serializer):
    """Serializer for job status update request data."""

    status = serializers.CharField(help_text="New status for the job")


class KanbanSuccessResponseSerializer(serializers.Serializer):
    """Serializer for successful kanban operation response."""

    success = serializers.BooleanField(default=True)
    message = serializers.CharField()


class KanbanErrorResponseSerializer(serializers.Serializer):
    """Serializer for error kanban operation response."""

    success = serializers.BooleanField(default=False)
    error = serializers.CharField()


class JobSearchFiltersSerializer(serializers.Serializer):
    """Serializer for advanced search filters."""

    job_number = serializers.IntegerField(required=False, allow_null=True)
    name = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    company_name = serializers.CharField(required=False, allow_blank=True)
    contact_person = serializers.CharField(required=False, allow_blank=True)
    created_by = serializers.CharField(required=False, allow_blank=True)
    created_after = serializers.DateField(required=False, allow_null=True)
    created_before = serializers.DateField(required=False, allow_null=True)
    status = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True
    )
    paid = serializers.CharField(required=False, allow_blank=True)


class KanbanJobPersonSerializer(serializers.Serializer):
    """Serializer for person data in kanban job context."""

    id = serializers.UUIDField()
    display_name = serializers.CharField()
    icon_url = serializers.URLField(allow_null=True)


class KanbanJobSerializer(serializers.Serializer):
    """
    Serializer for job data in kanban context
    (matches KanbanService.serialize_job_for_api).
    """

    # Basic job info
    id = serializers.UUIDField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True, allow_null=True)
    job_number = serializers.IntegerField()

    # Company and contact info
    company_name = serializers.CharField(allow_blank=True)
    contact_person = serializers.CharField(allow_blank=True)

    # People assigned to the job
    people = KanbanJobPersonSerializer(many=True)

    # Status info
    status = serializers.CharField()  # Display name
    status_key = serializers.CharField()  # Actual status key
    rejected_flag = serializers.BooleanField()  # Indicates if job was rejected

    # Financial
    paid = serializers.BooleanField()
    fully_invoiced = serializers.BooleanField()

    # Job settings
    speed_quality_tradeoff = serializers.CharField()

    # User who created the job
    created_by_id = serializers.UUIDField(allow_null=True)

    # Dates
    created_at = serializers.CharField(
        allow_null=True
    )  # Formatted as string by service
    updated_at = serializers.CharField(allow_null=True)
    delivery_date = serializers.CharField(allow_null=True)

    # Priority
    priority = serializers.FloatField()

    # Shop job flag
    shop_job = serializers.BooleanField()

    # Urgency
    is_urgent = serializers.BooleanField()

    # Budget status
    over_budget = serializers.BooleanField()
    quote_revenue = serializers.FloatField()
    time_and_materials_revenue = serializers.FloatField()

    # Workshop scheduling
    min_people = serializers.IntegerField()
    max_people = serializers.IntegerField()


class FetchAllJobsResponseSerializer(serializers.Serializer):
    """Serializer for fetch_all_jobs response."""

    success = serializers.BooleanField(default=True)
    active_jobs = KanbanJobSerializer(many=True, required=False)
    archived_jobs = KanbanJobSerializer(many=True, required=False)
    total_archived = serializers.IntegerField(required=False)
    error = serializers.CharField(required=False)


class FetchJobsResponseSerializer(serializers.Serializer):
    """Serializer for fetch_jobs response."""

    success = serializers.BooleanField(default=True)
    jobs = KanbanJobSerializer(many=True, required=False)
    total = serializers.IntegerField(required=False)
    filtered_count = serializers.IntegerField(required=False)
    error = serializers.CharField(required=False)


class FetchStatusValuesResponseSerializer(serializers.Serializer):
    """Serializer for fetch_status_values response."""

    success = serializers.BooleanField(default=True)
    statuses = serializers.DictField(child=serializers.CharField(), required=False)
    tooltips = serializers.DictField(child=serializers.CharField(), required=False)
    error = serializers.CharField(required=False)


class AdvancedSearchResponseSerializer(serializers.Serializer):
    """Serializer for advanced_search response."""

    success = serializers.BooleanField(default=True)
    jobs = KanbanJobSerializer(many=True, required=False)
    total = serializers.IntegerField(required=False)
    error = serializers.CharField(required=False)


class KanbanColumnJobSerializer(serializers.Serializer):
    """
    Serializer for job data in kanban column context
    (from get_jobs_by_kanban_column - uses serialize_job_for_api).
    """

    # Basic job info
    id = serializers.CharField()  # Converted to string by service
    job_number = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True, allow_null=True)

    # Company and contact info
    company_name = serializers.CharField(allow_blank=True)
    contact_person = serializers.CharField(allow_blank=True)

    # People assigned to the job (empty list for now)
    people = KanbanJobPersonSerializer(many=True)

    # Status info
    status = serializers.CharField()
    status_key = serializers.CharField()
    rejected_flag = serializers.BooleanField()

    # Financial
    paid = serializers.BooleanField()
    fully_invoiced = serializers.BooleanField()

    # Job settings
    speed_quality_tradeoff = serializers.CharField()

    # User who created the job
    created_by_id = serializers.CharField(allow_null=True)

    # Dates
    created_at = serializers.CharField(allow_null=True)
    updated_at = serializers.CharField(allow_null=True)
    delivery_date = serializers.CharField(allow_null=True)

    # Priority
    priority = serializers.FloatField()

    # Shop job flag
    shop_job = serializers.BooleanField()

    # Urgency
    is_urgent = serializers.BooleanField()

    # Budget status
    over_budget = serializers.BooleanField()
    quote_revenue = serializers.FloatField()
    time_and_materials_revenue = serializers.FloatField()

    # Workshop scheduling
    min_people = serializers.IntegerField()
    max_people = serializers.IntegerField()

    # Badge information (specific to column view)
    badge_label = serializers.CharField()
    badge_color = serializers.CharField()


class FetchJobsByColumnResponseSerializer(serializers.Serializer):
    """Serializer for fetch_jobs_by_column response."""

    success = serializers.BooleanField(default=True)
    jobs = KanbanColumnJobSerializer(many=True, required=False)
    total = serializers.IntegerField(required=False)
    filtered_count = serializers.IntegerField(required=False)
    has_more = serializers.BooleanField(required=False)
    error = serializers.CharField(required=False)


class WorkshopJobSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True, allow_null=True)
    job_number = serializers.IntegerField()
    company_name = serializers.CharField()
    contact_person = serializers.CharField(allow_blank=True, allow_null=True)
    people = KanbanJobPersonSerializer(many=True)
