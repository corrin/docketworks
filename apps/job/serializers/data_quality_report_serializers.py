"""Serializers for data quality report responses."""

from rest_framework import serializers

from apps.company.services.duplicate_person_report import (
    DuplicatePersonCandidate,
    DuplicatePersonCompanyLink,
    DuplicatePersonContactMethod,
    DuplicatePersonMatch,
    DuplicatePersonReport,
    DuplicatePersonReportSummary,
    DuplicatePersonSummary,
)
from apps.company.services.duplicate_phone_report import (
    DuplicatePhoneIssue,
    DuplicatePhoneOwner,
    DuplicatePhonesReport,
    DuplicatePhoneSummary,
)


class ComplianceSummarySerializer(serializers.Serializer):
    """Summary of compliance issues."""

    not_invoiced = serializers.IntegerField(
        help_text="Number of jobs that are not invoiced"
    )
    not_paid = serializers.IntegerField(help_text="Number of jobs that are not paid")
    not_cancelled = serializers.IntegerField(
        help_text="Number of jobs that should be cancelled but are not"
    )
    has_open_tasks = serializers.IntegerField(
        help_text="Number of jobs with open tasks"
    )


class ArchivedJobIssueSerializer(serializers.Serializer):
    """Details of a non-compliant archived job."""

    job_id = serializers.CharField(help_text="Job's unique identifier")
    job_number = serializers.CharField(help_text="Job number")
    company_name = serializers.CharField(help_text="Company name or 'Shop Job'")
    archived_date = serializers.DateField(help_text="Date when job was archived")
    current_status = serializers.CharField(help_text="Job's current status")
    issue = serializers.CharField(
        help_text="Compliance issue: 'Not invoiced', 'Not paid', 'Not cancelled', 'Has open tasks'"
    )
    invoice_status = serializers.CharField(
        required=False, allow_null=True, help_text="Invoice status if relevant"
    )
    outstanding_amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True,
        help_text="Outstanding amount if relevant",
    )
    job_value = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total job value (invoiced amount or quote/actual revenue)",
    )


class ArchivedJobsComplianceResponseSerializer(serializers.Serializer):
    """Response for archived jobs compliance check."""

    total_archived_jobs = serializers.IntegerField(
        help_text="Total number of archived jobs"
    )
    non_compliant_jobs = serializers.ListField(
        child=ArchivedJobIssueSerializer(),
        help_text="List of non-compliant jobs with details",
    )
    summary = ComplianceSummarySerializer(help_text="Summary of compliance issues")
    checked_at = serializers.DateTimeField(help_text="When the check was performed")


class DuplicatePhoneOwnerSerializer(serializers.Serializer[DuplicatePhoneOwner]):
    """One owner of a mis-owned phone number."""

    method_id = serializers.CharField(help_text="Contact-method id")
    owner_kind = serializers.CharField(help_text="'company' or 'person'")
    owner_name = serializers.CharField(help_text="Human-readable owner")
    effective_company_id = serializers.CharField(
        allow_null=True, help_text="Company the number resolves to"
    )


class DuplicatePhoneSummarySerializer(serializers.Serializer[DuplicatePhoneSummary]):
    """Summary of duplicate-phone issues."""

    cross_company = serializers.IntegerField(
        help_text="Numbers owned by more than one company"
    )
    internal_line = serializers.IntegerField(
        help_text="Company numbers that are actually internal company lines"
    )


class DuplicatePhoneIssueSerializer(serializers.Serializer[DuplicatePhoneIssue]):
    """One problematic phone number and its owners."""

    normalized_value = serializers.CharField(help_text="Normalized phone number")
    issue = serializers.CharField(help_text="'cross_company' or 'internal_line'")
    endpoint_label = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Internal endpoint label (internal_line only)",
    )
    owners = DuplicatePhoneOwnerSerializer(many=True)


class DuplicatePhonesResponseSerializer(serializers.Serializer[DuplicatePhonesReport]):
    """Response for the duplicate phones check."""

    duplicate_phones = serializers.ListField(
        child=DuplicatePhoneIssueSerializer(),
        help_text="Mis-owned phone numbers with details",
    )
    summary = DuplicatePhoneSummarySerializer(help_text="Summary of issues")
    checked_at = serializers.DateTimeField(help_text="When the check was performed")


class DuplicatePersonCompanyLinkSerializer(
    serializers.Serializer[DuplicatePersonCompanyLink]
):
    link_id = serializers.UUIDField()
    company_id = serializers.UUIDField()
    company_name = serializers.CharField()
    position = serializers.CharField(allow_null=True)
    is_primary = serializers.BooleanField()
    is_active = serializers.BooleanField()


class DuplicatePersonContactMethodSerializer(
    serializers.Serializer[DuplicatePersonContactMethod]
):
    method_id = serializers.UUIDField()
    method_type = serializers.ChoiceField(choices=["phone", "email"])
    value = serializers.CharField()
    normalized_value = serializers.CharField()
    contact_label = serializers.CharField()
    is_primary = serializers.BooleanField()


class DuplicatePersonSummarySerializer(serializers.Serializer[DuplicatePersonSummary]):
    person_id = serializers.UUIDField()
    name = serializers.CharField()
    email = serializers.EmailField(allow_null=True)
    is_active = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    company_links = DuplicatePersonCompanyLinkSerializer(many=True)
    contact_methods = DuplicatePersonContactMethodSerializer(many=True)
    job_count = serializers.IntegerField()
    phone_call_count = serializers.IntegerField()


class DuplicatePersonMatchSerializer(serializers.Serializer[DuplicatePersonMatch]):
    kind = serializers.ChoiceField(choices=["name", "email", "phone"])
    normalized_value = serializers.CharField()


class DuplicatePersonCandidateSerializer(
    serializers.Serializer[DuplicatePersonCandidate]
):
    confidence = serializers.ChoiceField(choices=["high", "medium", "low"])
    matches = DuplicatePersonMatchSerializer(many=True)
    shared_company_ids = serializers.ListField(child=serializers.UUIDField())
    first_person = DuplicatePersonSummarySerializer()
    second_person = DuplicatePersonSummarySerializer()


class DuplicatePersonReportSummarySerializer(
    serializers.Serializer[DuplicatePersonReportSummary]
):
    candidate_pairs = serializers.IntegerField()
    people_flagged = serializers.IntegerField()
    high = serializers.IntegerField()
    medium = serializers.IntegerField()
    low = serializers.IntegerField()


class DuplicatePeopleResponseSerializer(serializers.Serializer[DuplicatePersonReport]):
    duplicate_people = DuplicatePersonCandidateSerializer(many=True)
    summary = DuplicatePersonReportSummarySerializer()
    checked_at = serializers.DateTimeField()
