import json
from pathlib import Path

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parents[3]
CREDENTIALS_TEMPLATE = (
    REPO_ROOT / "scripts" / "server" / "templates" / "credentials-instance.template"
)
XERO_APPS_TEMPLATE = (
    REPO_ROOT / "scripts" / "server" / "templates" / "xero-apps.json.template"
)
INSTANCE_SCRIPT = REPO_ROOT / "scripts" / "server" / "instance.sh"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "server" / "deploy.sh"
COMMON_SCRIPT = REPO_ROOT / "scripts" / "server" / "common.sh"
SERVER_SETUP_SCRIPT = REPO_ROOT / "scripts" / "server" / "server-setup.sh"


class XeroInstanceTemplateTests(SimpleTestCase):
    def test_credentials_template_includes_xero_oauth_env_vars(self):
        content = CREDENTIALS_TEMPLATE.read_text()

        self.assertIn("XERO_CLIENT_ID=", content)
        self.assertIn("XERO_CLIENT_SECRET=", content)
        self.assertIn("XERO_WEBHOOK_KEY=", content)
        self.assertIn("XERO_REDIRECT_URI=", content)

    def test_xero_apps_template_renders_to_valid_json(self):
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

        payload = json.loads(rendered)
        self.assertEqual(len(payload), 1)
        fields = payload[0]["fields"]
        self.assertEqual(fields["label"], "msm-uat xero")
        self.assertEqual(fields["client_id"], "client-id")
        self.assertEqual(fields["client_secret"], "client-secret")
        self.assertEqual(fields["webhook_key"], "webhook-key")
        self.assertEqual(
            fields["redirect_uri"],
            "https://msm-uat.docketworks.site/api/xero/oauth/callback/",
        )

    def test_instance_script_requires_and_loads_xero_app_fixture(self):
        content = INSTANCE_SCRIPT.read_text()

        self.assertIn('[[ -z "${XERO_CLIENT_ID:-}" ]]', content)
        self.assertIn('[[ -z "${XERO_CLIENT_SECRET:-}" ]]', content)
        self.assertIn('[[ -z "${XERO_WEBHOOK_KEY:-}" ]]', content)
        self.assertIn('[[ -z "${XERO_REDIRECT_URI:-}" ]]', content)

        self.assertIn("xero-apps.json.template", content)
        self.assertIn(
            'call_command("loaddata", "apps/workflow/fixtures/xero_apps.json")',
            content,
        )
        self.assertIn(
            "XeroApp already configured; skipping xero_apps.json load", content
        )
        self.assertIn("if XeroApp.objects.exists()", content)
        self.assertNotIn("XeroApp.objects.filter", content)
        self.assertNotIn(".delete()", content)
        self.assertNotIn(
            "python manage.py loaddata apps/workflow/fixtures/xero_apps.json", content
        )
        self.assertNotIn(
            'rm -f "$INSTANCE_DIR/apps/workflow/fixtures/xero_apps.json"', content
        )

    def test_instance_script_exposes_reconfigure_as_convergent_command(self) -> None:
        content = INSTANCE_SCRIPT.read_text()

        self.assertIn("instance.sh reconfigure <client> <env>", content)
        self.assertIn("do_reconfigure()", content)
        self.assertIn("do_configure false reconfigure", content)
        self.assertIn("reconfigure)    do_reconfigure", content)

    def test_instance_script_rerenders_env_preserving_generated_values(self) -> None:
        content = INSTANCE_SCRIPT.read_text()

        self.assertIn("render_instance_env()", content)
        self.assertIn(
            'db_password="$(read_env_value "$env_file" DB_PASSWORD)"', content
        )
        self.assertIn(
            'test_db_password="$(read_env_value "$env_file" TEST_DB_PASSWORD)"',
            content,
        )
        self.assertIn('secret_key="$(read_env_value "$env_file" SECRET_KEY)"', content)
        self.assertIn(
            'bearer_secret="$(read_env_value "$env_file" BEARER_SECRET)"',
            content,
        )
        self.assertIn('tmp_env="$(mktemp "$instance_dir/.env.tmp.XXXXXX")"', content)
        self.assertIn('mv "$tmp_env" "$env_file"', content)
        self.assertNotIn(".env already exists — skipping", content)
        self.assertIn(
            'DB_PASSWORD="$(read_env_value "$INSTANCE_DIR/.env" DB_PASSWORD)"',
            content,
        )
        self.assertNotIn('DB_PASSWORD="$(. "$INSTANCE_DIR/.env"', content)

    def test_instance_script_only_seeds_missing_db_config(self) -> None:
        content = INSTANCE_SCRIPT.read_text()

        self.assertIn(
            "AIProvider already configured; skipping ai_providers.json load", content
        )
        self.assertIn("if AIProvider.objects.exists()", content)
        self.assertIn(
            "XeroApp already configured; skipping xero_apps.json load", content
        )
        self.assertIn("if XeroApp.objects.exists()", content)
        self.assertNotIn(
            "python manage.py loaddata apps/workflow/fixtures/ai_providers.json",
            content,
        )

    def test_instance_script_rejects_seed_for_existing_checkout(self) -> None:
        content = INSTANCE_SCRIPT.read_text()

        self.assertIn('[[ -d "$INSTANCE_DIR/.git" && "$SEED" == "true" ]]', content)
        self.assertIn("--seed is only valid when creating a new instance", content)

    def test_credentials_file_stays_root_owned_before_root_source(self) -> None:
        common_content = COMMON_SCRIPT.read_text()
        instance_content = INSTANCE_SCRIPT.read_text()
        deploy_content = DEPLOY_SCRIPT.read_text()
        server_setup_content = SERVER_SETUP_SCRIPT.read_text()

        self.assertIn("require_root_owned_credentials_file()", common_content)
        self.assertIn("stat -c '%u:%g:%a' \"$creds_file\"", common_content)
        self.assertIn('"0:0:600"', common_content)
        self.assertIn('[[ -L "$creds_file" ]]', common_content)
        self.assertIn("ensure_config_dir()", common_content)
        self.assertIn("stat -c '%u:%g:%a' \"$config_dir\"", common_content)
        self.assertIn('"0:0:755"', common_content)
        self.assertIn('[[ -L "$CONFIG_DIR" ]]', common_content)
        self.assertIn('[[ -L "$config_dir" ]]', common_content)

        self.assertIn('chown root:root "$CREDS_FILE"', instance_content)
        self.assertIn(
            'require_root_owned_credentials_file "$creds_file"',
            instance_content,
        )
        self.assertIn(
            'require_root_owned_credentials_file "$CREDS_FILE"',
            instance_content,
        )
        self.assertNotIn(
            'chown "$INSTANCE_USER:$INSTANCE_USER" "$CREDS_FILE"',
            instance_content,
        )

        self.assertIn(
            'require_root_owned_credentials_file "$creds_file"',
            deploy_content,
        )
        self.assertIn("chown root:root /opt/docketworks/config", server_setup_content)
        self.assertIn("chmod 755 /opt/docketworks/config", server_setup_content)

    def test_deploy_restores_typed_router_after_drift_detection(self) -> None:
        content = DEPLOY_SCRIPT.read_text()

        self.assertIn(
            "server generated a different frontend/src/typed-router.d.ts",
            content,
        )
        self.assertIn(
            'git -C "$instance_dir" restore --source=HEAD -- '
            "frontend/src/typed-router.d.ts",
            content,
        )
        self.assertIn('FAILED_INSTANCES+=("$instance")', content)
