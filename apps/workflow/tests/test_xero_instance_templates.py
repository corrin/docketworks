import json
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from django.core import serializers
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from apps.accounts.models import Staff
from apps.crm.models import PhoneEndpoint
from apps.workflow.models import CompanyDefaults, XeroApp

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMON_SCRIPT = REPO_ROOT / "scripts" / "server" / "common.sh"
XERO_APPS_TEMPLATE = (
    REPO_ROOT / "scripts" / "server" / "templates" / "xero-apps.json.template"
)
PHONE_PROVIDER_SETTINGS_TEMPLATE = (
    REPO_ROOT
    / "scripts"
    / "server"
    / "templates"
    / "phone-provider-settings.json.template"
)
COMPANY_DEFAULTS_FIXTURE = (
    REPO_ROOT / "apps" / "workflow" / "fixtures" / "company_defaults.json"
)
INITIAL_DATA_FIXTURE = (
    REPO_ROOT / "apps" / "workflow" / "fixtures" / "initial_data.json"
)


class DemoSeedFixtureTests(TestCase):
    def test_demo_seed_fixtures_load_current_demo_contract(self) -> None:
        """Schema changes must not break demo creation or its advertised logins."""
        call_command(
            "loaddata",
            str(COMPANY_DEFAULTS_FIXTURE),
            str(INITIAL_DATA_FIXTURE),
            verbosity=0,
        )

        demo_staff = Staff.objects.filter(email__endswith="@example.com")
        self.assertEqual(demo_staff.count(), 11)
        self.assertFalse(
            Staff.objects.filter(email="defaultadmin@example.com").exists()
        )
        self.assertTrue(
            all(staff.check_password("Default-staff-password") for staff in demo_staff)
        )
        self.assertFalse(demo_staff.exclude(xero_user_id__isnull=True).exists())

        charles = demo_staff.get(email="charles.baker@example.com")
        self.assertEqual(charles.base_wage_rate, Decimal("35.80"))
        self.assertEqual(charles.wage_rate, Decimal("42.96"))

        defaults = CompanyDefaults.objects.get(pk=1)
        self.assertEqual(defaults.company_name, "Demo Company")
        self.assertEqual(
            str(defaults.shop_company_id),
            "00000000-0000-0000-0000-000000000001",
        )

        main_line = PhoneEndpoint.objects.get(label="Main line")
        self.assertEqual(main_line.number, "+6496365131")
        self.assertEqual(main_line.endpoint_type, PhoneEndpoint.EndpointType.MAIN_LINE)

    def test_seed_template_satisfies_instance_sh_validator_contract(self) -> None:
        """`prepare-config --seed` copies this fixture to the operator config, which
        `instance.sh validate_company_defaults_config` then requires to be exactly one
        Company and one CompanyDefaults with a valid-UUID xero_tenant_id and sync
        disabled. Drift here silently breaks `create --seed`."""
        text = COMPANY_DEFAULTS_FIXTURE.read_text()
        records = json.loads(text)

        self.assertEqual(
            sorted(record["model"] for record in records),
            ["company.company", "workflow.companydefaults"],
        )
        self.assertNotIn("__", text)

        defaults = next(
            record["fields"]
            for record in records
            if record["model"] == "workflow.companydefaults"
        )
        UUID(defaults["xero_tenant_id"])
        self.assertIs(defaults["enable_xero_sync"], False)


class XeroInstanceTemplateTests(SimpleTestCase):
    def test_xero_apps_template_renders_to_valid_json(self) -> None:
        """Model field removals must not leave provisioning fixtures unreadable."""
        rendered = (
            XERO_APPS_TEMPLATE.read_text()
            .replace("__INSTANCE__", "msm-uat")
            .replace("__XERO_CLIENT_ID__", "client-id")
            .replace("__XERO_CLIENT_SECRET__", "client-secret")
            .replace("__XERO_WEBHOOK_KEY__", "webhook-key")
            .replace(
                "__XERO_REDIRECT_URI__",
                "https://msm-uat.docketworks.site/api/xero/oauth/callback/",
            )
        )

        deserialized = list(serializers.deserialize("json", rendered))
        self.assertEqual(len(deserialized), 1)
        xero_app = deserialized[0].object
        assert isinstance(xero_app, XeroApp)
        self.assertEqual(xero_app.label, "msm-uat xero")
        self.assertEqual(xero_app.client_id, "client-id")
        self.assertEqual(xero_app.client_secret, "client-secret")
        self.assertEqual(xero_app.webhook_key, "webhook-key")
        self.assertEqual(
            xero_app.redirect_uri,
            "https://msm-uat.docketworks.site/api/xero/oauth/callback/",
        )

    def test_phone_provider_settings_template_renders_to_valid_json(self) -> None:
        rendered = (
            PHONE_PROVIDER_SETTINGS_TEMPLATE.read_text()
            .replace("__PHONE_PROVIDER_DOWNLOADS_ENABLED__", "true")
            .replace("__PHONE_PROVIDER_RECORDING_DELETION_ENABLED__", "false")
            .replace(
                "__PHONE_PROVIDER_BASE_URL_JSON__",
                '"http://phone-provider.lan"',
            )
            .replace("__PHONE_PROVIDER_USERNAME__", "phone-user")
            .replace("__PHONE_PROVIDER_PASSWORD__", "phone-secret")
            .replace("__PHONE_PROVIDER_ACCOUNT_CODE__", "15539090")
        )

        payload = json.loads(rendered)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["model"], "crm.phoneprovidersettings")
        self.assertEqual(payload[0]["pk"], 1)
        fields = payload[0]["fields"]
        self.assertTrue(fields["downloads_enabled"])
        self.assertFalse(fields["recording_deletion_enabled"])
        self.assertEqual(fields["base_url"], "http://phone-provider.lan")
        self.assertEqual(fields["username"], "phone-user")
        self.assertEqual(fields["password"], "phone-secret")
        self.assertEqual(fields["account_code"], "15539090")

    def test_node_major_parsing_accepts_patch_versions(self) -> None:
        for nvmrc_value in ["18", "v18", "18.2.0", "v18.2.0", "  v18.2.0"]:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8") as nvmrc:
                nvmrc.write(nvmrc_value)
                nvmrc.flush()

                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        'source "$1"; node_major_from_nvmrc "$2"',
                        "_",
                        str(COMMON_SCRIPT),
                        nvmrc.name,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )

            self.assertEqual(result.stdout.strip(), "18")

    def test_prod_ref_guard_refuses_non_production_ref_on_prod_only(self) -> None:
        def run(
            instance: str, ref: str, allow: str
        ) -> "subprocess.CompletedProcess[str]":
            return subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; require_production_ref_or_ack "$2" "$3" "$4"',
                    "_",
                    str(COMMON_SCRIPT),
                    instance,
                    ref,
                    allow,
                ],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
            )

        # non-prod instance: any ref is fine
        self.assertEqual(run("msm-uat", "origin/main", "false").returncode, 0)
        # prod instance on the production ref: fine
        self.assertEqual(run("msm-prod", "origin/production", "false").returncode, 0)
        # prod instance on a candidate ref, not acknowledged (no tty): refused
        self.assertNotEqual(run("msm-prod", "origin/main", "false").returncode, 0)
        # prod instance on a candidate ref, explicitly acknowledged: allowed
        self.assertEqual(run("msm-prod", "origin/main", "true").returncode, 0)

    def test_require_root_owned_credentials_file_rejects_bad_owner_and_symlink(
        self,
    ) -> None:
        """The guard must reject a credentials file whose config dir is not
        root:root, or is reached through a symlink. (The root-owned pass path
        needs root and is covered by E2E, not here.)"""

        def run(creds_file: str) -> "subprocess.CompletedProcess[str]":
            return subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; require_root_owned_credentials_file "$2"',
                    "_",
                    str(COMMON_SCRIPT),
                    creds_file,
                ],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
            )

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            creds = base / "inst.credentials.env"
            creds.write_text("")

            # config dir is owned by the test user, not root:root 755 → rejected
            self.assertNotEqual(run(str(creds)).returncode, 0)

            # config dir reached via a symlink → rejected
            link = base / "linkdir"
            link.symlink_to(base)
            self.assertNotEqual(run(str(link / "inst.credentials.env")).returncode, 0)
