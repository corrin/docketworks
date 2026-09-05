"""Typed install-level integration settings (ADR 0053)."""

from typing import ClassVar

from django.core.exceptions import ImproperlyConfigured
from django.db import models


class IntegrationSettings(models.Model):
    """The credentials and switches this install uses to reach external services.

    One typed column per credential (ADR 0053): mypy sees every read, each
    column carries its own not-blank constraint, and the set of integrations
    is in code rather than data. It holds what the install has exactly one of
    — N-of integrations (``XeroApp``, ``AIProvider``, ``SupplierCredential``)
    keep their own tables. Never ``CompanyDefaults``: its GET is any-staff boot
    data that echoes every column.

    Plaintext by decision (2026-08-01): field-level encryption was dropped in
    v2 because per-instance databases owned by per-client roles make it
    key-management theatre. The scrubber truncates this table whole, so no
    secret reaches a non-production dump.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    # Google Places (New), read by apps/platform/integrations/google/places.
    google_maps_api_key = models.CharField(  # noqa: DJ001 -- unset is NULL (ADR 0040); a CHECK rejects ""
        max_length=255, null=True, blank=True
    )

    # The phone provider's portal (CRM call ingestion). `phone_provider_enabled`
    # is the one switch for the integration; the tasks read the four login
    # values at the point of use and fail there, naming what is missing.
    phone_provider_enabled = models.BooleanField(default=False)
    phone_provider_recording_deletion_enabled = models.BooleanField(default=False)
    # Owner ruling 2026-08-23: a retention window is a setting, not a literal.
    # This is the delay before the PROVIDER deletes its copy, so it belongs
    # beside the switch that turns that deletion on rather than in
    # CompanyDefaults, whose GET is any-staff boot data.
    phone_provider_recording_deletion_after_days = models.PositiveSmallIntegerField(default=31)
    phone_provider_base_url = models.URLField(null=True, blank=True, default=None)  # noqa: DJ001 -- unset is NULL (ADR 0040)
    phone_provider_username = models.TextField(blank=True, null=True)  # noqa: DJ001 -- unset is NULL (ADR 0040)
    phone_provider_password = models.TextField(blank=True, null=True)  # noqa: DJ001 -- unset is NULL (ADR 0040)
    phone_provider_account_code = models.CharField(  # noqa: DJ001 -- unset is NULL (ADR 0040)
        max_length=100, blank=True, null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Fable: pinned to the table v1 created for the phone-provider row.
        # v1's dump restores by table name, and the scrubber's private-table
        # list names this one, so keeping it moves no data and changes no
        # scrub contract. The physical rename belongs to the post-cutover
        # "purge v1/v2 names" sweep in docs/rewrite-status.md.
        db_table = "crm_phoneprovidersettings"
        verbose_name = "Integration Settings"
        verbose_name_plural = "Integration Settings"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(id=1),
                name="core_integrationsettings_singleton",
            ),
            models.CheckConstraint(
                condition=~models.Q(google_maps_api_key=""),
                name="core_integrationsettings_google_maps_api_key_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(phone_provider_base_url=""),
                name="core_integrationsettings_phone_provider_base_url_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(phone_provider_username=""),
                name="core_integrationsettings_phone_provider_username_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(phone_provider_password=""),
                name="core_integrationsettings_phone_provider_password_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(phone_provider_account_code=""),
                name="core_integrationsettings_phone_provider_account_code_not_blank",
            ),
        ]

    def __str__(self) -> str:
        return "integration settings"

    @classmethod
    def get_solo(cls) -> "IntegrationSettings":
        """Return the singleton. Never creates one — reads do not write.

        Fable: the row is created by core/0003 on a fresh install and by
        `manage.py load_integration_settings` after a scrubbed restore (which
        truncates the table while django_migrations already records 0003).
        Its absence is an operator problem, said plainly rather than papered
        over with a row nobody configured (ADR 0015).
        """
        instance = cls.objects.first()
        if instance is None:
            raise ImproperlyConfigured(
                "IntegrationSettings has no row. A fresh install gets it from "
                "core/0003_integration_settings_row; after a scrubbed restore run "
                "`manage.py load_integration_settings <fixture>` or re-insert the saved row."
            )
        return instance
