import re
import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps
from django.db.models import Model


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if not digits:
        return ""
    if digits.startswith("64"):
        return f"+{digits}"
    if digits.startswith("0") and len(digits) > 1:
        return f"+64{digits[1:]}"
    return f"+{digits}"


def migrate_phone_settings(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    CompanyDefaults = apps.get_model("workflow", "CompanyDefaults")
    PhoneEndpoint = apps.get_model("crm", "PhoneEndpoint")
    PhoneProviderSettings = apps.get_model("crm", "PhoneProviderSettings")

    defaults = CompanyDefaults.objects.first()
    if defaults is None:
        PhoneProviderSettings.objects.get_or_create(pk=1)
        return

    PhoneProviderSettings.objects.update_or_create(
        pk=1,
        defaults={
            "downloads_enabled": defaults.phone_call_downloads_enabled,
            "recording_deletion_enabled": (
                defaults.phone_provider_recording_deletion_enabled
            ),
            "base_url": defaults.phone_provider_base_url,
            "username": defaults.phone_provider_username,
            "password": defaults.phone_provider_password,
            "account_code": defaults.phone_provider_account_code,
        },
    )

    owned_numbers = list(defaults.phone_own_numbers or [])
    if defaults.company_phone:
        owned_numbers.insert(0, defaults.company_phone)
    seen = set()
    for index, raw_number in enumerate(owned_numbers):
        normalized = normalize_phone(raw_number)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        endpoint_type = "main_line" if index == 0 else "shared"
        label = "Main line" if index == 0 else f"Company line {index + 1}"
        PhoneEndpoint.objects.update_or_create(
            normalized_number=normalized,
            defaults={
                "number": normalized,
                "label": label,
                "endpoint_type": endpoint_type,
                "provider_account_code": defaults.phone_provider_account_code,
                "provider_metadata": {},
                "is_active": True,
            },
        )


def customer_index(apps: StateApps) -> dict[str, set[tuple[str, str, str]]]:
    ClientContactMethod = apps.get_model("client", "ClientContactMethod")
    PhoneEndpoint = apps.get_model("crm", "PhoneEndpoint")
    internal_numbers = set(
        PhoneEndpoint.objects.filter(is_active=True).values_list(
            "normalized_number", flat=True
        )
    )
    index: dict[str, set[tuple[str, str, str]]] = {}
    for method in ClientContactMethod.objects.filter(method_type="phone"):
        normalized = method.normalized_value or normalize_phone(method.value)
        if not normalized or normalized in internal_numbers:
            continue
        if method.contact_id:
            client_id = method.contact.client_id
            index.setdefault(normalized, set()).add(
                ("contact", method.contact_id, client_id)
            )
        elif method.client_id:
            index.setdefault(normalized, set()).add(
                ("client", method.client_id, method.client_id)
            )
    return index


def resolve_customer(
    apps: StateApps, matches: set[tuple[str, str, str]]
) -> tuple[Model | None, Model | None]:
    Client = apps.get_model("client", "Client")
    ClientContact = apps.get_model("client", "ClientContact")
    if not matches:
        return None, None
    client_ids = {client_id for _, _, client_id in matches}
    if len(client_ids) != 1:
        return None, None
    if len(matches) != 1:
        return Client.objects.get(id=next(iter(client_ids))), None
    kind, object_id, _client_id = next(iter(matches))
    if kind == "contact":
        contact = ClientContact.objects.select_related("client").get(id=object_id)
        return contact.client, contact
    return Client.objects.get(id=object_id), None


def classify_existing_calls(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    PhoneEndpoint = apps.get_model("crm", "PhoneEndpoint")
    PhoneCallRecord = apps.get_model("crm", "PhoneCallRecord")
    endpoints = {
        endpoint.normalized_number: endpoint
        for endpoint in PhoneEndpoint.objects.filter(is_active=True)
    }
    phone_matches = customer_index(apps)

    for call in PhoneCallRecord.objects.all().iterator():
        normalized_origin = normalize_phone(call.origin)
        normalized_destination = normalize_phone(call.destination)
        origin_endpoint = endpoints.get(normalized_origin)
        destination_endpoint = endpoints.get(normalized_destination)
        if origin_endpoint and destination_endpoint:
            direction = "internal"
            our_number = normalized_origin
            external_number = ""
            client = None
            contact = None
        elif origin_endpoint:
            direction = "outbound"
            our_number = normalized_origin
            external_number = normalized_destination
            client, contact = resolve_customer(
                apps, phone_matches.get(normalized_destination, set())
            )
        elif destination_endpoint:
            direction = "inbound"
            our_number = normalized_destination
            external_number = normalized_origin
            client, contact = resolve_customer(
                apps,
                phone_matches.get(normalized_origin, set()),
            )
        else:
            direction = "unknown"
            our_number = ""
            external_number = normalized_origin or normalized_destination
            matches = set()
            matches.update(phone_matches.get(normalized_origin, set()))
            matches.update(phone_matches.get(normalized_destination, set()))
            client, contact = resolve_customer(apps, matches)

        call.direction = direction
        call.our_number = our_number
        call.external_number = external_number
        call.origin_endpoint = origin_endpoint
        call.destination_endpoint = destination_endpoint
        call.client = client
        call.contact = contact
        call.save(
            update_fields=[
                "direction",
                "our_number",
                "external_number",
                "origin_endpoint",
                "destination_endpoint",
                "client",
                "contact",
                "updated_at",
            ]
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("accounts", "0015_create_system_automation_user"),
        ("client", "0022_client_name_trgm_index"),
        ("crm", "0005_phone_call_sync_near_realtime"),
        ("workflow", "0236_remove_companydefaults_charge_out_rate"),
    ]

    operations = [
        migrations.CreateModel(
            name="PhoneEndpoint",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("number", models.CharField(max_length=150)),
                (
                    "normalized_number",
                    models.CharField(db_index=True, max_length=150, unique=True),
                ),
                ("label", models.CharField(max_length=255)),
                (
                    "endpoint_type",
                    models.CharField(
                        choices=[
                            ("main_line", "Main line"),
                            ("staff_mobile", "Staff mobile"),
                            ("staff_ddi", "Staff DDI"),
                            ("extension", "Extension"),
                            ("shared", "Shared"),
                        ],
                        max_length=30,
                    ),
                ),
                ("provider_account_code", models.CharField(blank=True, max_length=100)),
                ("provider_metadata", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "staff",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="phone_endpoints",
                        to="accounts.staff",
                    ),
                ),
            ],
            options={
                "ordering": ["endpoint_type", "label", "normalized_number"],
            },
        ),
        migrations.CreateModel(
            name="PhoneProviderSettings",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("downloads_enabled", models.BooleanField(default=False)),
                ("recording_deletion_enabled", models.BooleanField(default=False)),
                ("base_url", models.URLField(blank=True, default=None, null=True)),
                ("username", models.CharField(blank=True, default="", max_length=255)),
                ("password", models.CharField(blank=True, default="", max_length=255)),
                ("account_code", models.CharField(blank=True, default="", max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Phone Provider Settings",
                "verbose_name_plural": "Phone Provider Settings",
            },
        ),
        migrations.AddField(
            model_name="phonecallrecord",
            name="direction",
            field=models.CharField(
                choices=[
                    ("inbound", "Inbound"),
                    ("outbound", "Outbound"),
                    ("internal", "Internal"),
                    ("unknown", "Unknown"),
                ],
                db_index=True,
                default="unknown",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="phonecallrecord",
            name="our_number",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="phonecallrecord",
            name="external_number",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="phonecallrecord",
            name="origin_endpoint",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="origin_phone_calls",
                to="crm.phoneendpoint",
            ),
        ),
        migrations.AddField(
            model_name="phonecallrecord",
            name="destination_endpoint",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="destination_phone_calls",
                to="crm.phoneendpoint",
            ),
        ),
        migrations.AddIndex(
            model_name="phoneendpoint",
            index=models.Index(
                fields=["is_active", "normalized_number"],
                name="crm_phone_endpoint_active_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="phoneendpoint",
            index=models.Index(
                fields=["staff", "is_active"],
                name="crm_phone_endpoint_staff_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="phonecallrecord",
            index=models.Index(fields=["direction", "-call_datetime"], name="crm_phone_direction_idx"),
        ),
        migrations.AddIndex(
            model_name="phonecallrecord",
            index=models.Index(fields=["origin_endpoint", "-call_datetime"], name="crm_phone_origin_ep_idx"),
        ),
        migrations.AddIndex(
            model_name="phonecallrecord",
            index=models.Index(fields=["destination_endpoint", "-call_datetime"], name="crm_phone_dest_ep_idx"),
        ),
        migrations.RunPython(migrate_phone_settings, migrations.RunPython.noop),
        migrations.RunPython(classify_existing_calls, migrations.RunPython.noop),
    ]
