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
DW_RUN_SCRIPT = REPO_ROOT / "scripts" / "server" / "dw-run.sh"
RELEASE_UTILS = REPO_ROOT / "scripts" / "server" / "release-utils.sh"
GUNICORN_TEMPLATE = (
    REPO_ROOT
    / "scripts"
    / "server"
    / "templates"
    / "gunicorn-instance.service.template"
)
CELERY_WORKER_TEMPLATE = (
    REPO_ROOT
    / "scripts"
    / "server"
    / "templates"
    / "celery-worker-instance.service.template"
)
CELERY_BEAT_TEMPLATE = (
    REPO_ROOT
    / "scripts"
    / "server"
    / "templates"
    / "celery-beat-instance.service.template"
)
NGINX_TEMPLATE = (
    REPO_ROOT / "scripts" / "server" / "templates" / "nginx-instance.conf.template"
)
BACKUP_TEMPLATE = (
    REPO_ROOT
    / "scripts"
    / "server"
    / "templates"
    / "backup-db-instance.service.template"
)
SETTINGS_FILE = REPO_ROOT / "docketworks" / "settings.py"


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
            "call_command('loaddata', '$XERO_APPS_FIXTURE')",
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

        self.assertIn('[[ "$IS_EXISTING" == "true" && "$SEED" == "true" ]]', content)
        self.assertIn("--seed is only valid when creating a new instance", content)

    def test_instance_script_uses_shared_releases_not_instance_checkouts(self) -> None:
        content = INSTANCE_SCRIPT.read_text()

        self.assertIn('source "$SCRIPT_DIR/release-utils.sh"', content)
        self.assertIn('ensure_release "$TARGET_SHA"', content)
        self.assertIn('switch_instance_release "$INSTANCE" "$TARGET_SHA"', content)
        self.assertNotIn('git -C "$INSTANCE_DIR" init', content)
        self.assertNotIn('git -C "$INSTANCE_DIR" checkout', content)
        self.assertNotIn("Building frontend for instance", content)

    def test_instance_secret_fixtures_are_instance_private(self) -> None:
        content = INSTANCE_SCRIPT.read_text()

        self.assertIn('local fixture_dir="$instance_dir/.fixtures"', content)
        self.assertIn(
            'local AI_PROVIDERS_FIXTURE="$INSTANCE_DIR/.fixtures/ai_providers.json"',
            content,
        )
        self.assertIn(
            'local XERO_APPS_FIXTURE="$INSTANCE_DIR/.fixtures/xero_apps.json"', content
        )
        self.assertNotIn(
            "$instance_dir/apps/workflow/fixtures/ai_providers.json",
            content,
        )
        self.assertNotIn(
            "$instance_dir/apps/workflow/fixtures/xero_apps.json",
            content,
        )

    def test_deploy_prepares_one_shared_release_for_all_targets(self) -> None:
        content = DEPLOY_SCRIPT.read_text()

        self.assertIn('TARGET_REF="origin/main"', content)
        self.assertIn('TARGET_SHA="$(resolve_release_ref "$TARGET_REF")"', content)
        self.assertIn('ensure_release "$TARGET_SHA"', content)
        self.assertIn('switch_instance_release "$instance" "$TARGET_SHA"', content)
        self.assertNotIn("Updating shared Python dependencies", content)
        self.assertNotIn("Updating shared node_modules", content)
        self.assertNotIn("Building frontend", content)
        self.assertNotIn('git -C "$inst_dir" pull', content)

    def test_release_utils_builds_immutable_release_artifacts(self) -> None:
        content = RELEASE_UTILS.read_text()

        self.assertIn("RELEASES_DIR", content)
        self.assertIn("git -C '$LOCAL_REPO' archive '$sha'", content)
        self.assertIn("printf '%s\\n' '$sha' > '$tmp_dir/.release-sha'", content)
        self.assertIn("python3.12 -m venv '$tmp_dir/.venv'", content)
        self.assertIn("npm run check:typed-router", content)
        self.assertIn("npm run build", content)
        self.assertIn("npm run manual:build", content)
        self.assertIn("rm -rf node_modules", content)
        self.assertIn("touch '$tmp_dir/.complete'", content)

    def test_runtime_templates_use_current_release(self) -> None:
        for template in [
            GUNICORN_TEMPLATE,
            CELERY_WORKER_TEMPLATE,
            CELERY_BEAT_TEMPLATE,
        ]:
            content = template.read_text()
            self.assertIn(
                "WorkingDirectory=/opt/docketworks/instances/__INSTANCE__/current",
                content,
            )
            self.assertIn(
                "/opt/docketworks/instances/__INSTANCE__/current/.venv/bin/", content
            )
            self.assertIn("Environment=PYTHONDONTWRITEBYTECODE=1", content)
            self.assertNotIn("/opt/docketworks/.venv/bin/", content)

        nginx = NGINX_TEMPLATE.read_text()
        self.assertIn(
            "/opt/docketworks/instances/__INSTANCE__/current/frontend/dist", nginx
        )
        self.assertIn("/opt/docketworks/instances/__INSTANCE__/mediafiles/", nginx)

        backup = BACKUP_TEMPLATE.read_text()
        self.assertIn(
            "ExecStart=/opt/docketworks/instances/__INSTANCE__/current/scripts/backup_db.sh __INSTANCE__",
            backup,
        )

    def test_dw_run_uses_current_release_and_instance_env(self) -> None:
        content = DW_RUN_SCRIPT.read_text()

        self.assertIn('CURRENT_DIR="$INSTANCE_DIR/current"', content)
        self.assertIn("source '$CURRENT_DIR/.venv/bin/activate'", content)
        self.assertIn("source '$INSTANCE_DIR/.env'", content)
        self.assertIn("cd '$CURRENT_DIR'", content)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", content)

    def test_build_id_reads_release_sha_before_git(self) -> None:
        content = SETTINGS_FILE.read_text()

        self.assertIn('os.environ.get("DOCKETWORKS_BUILD_SHA"', content)
        self.assertIn('release_sha_file = BASE_DIR / ".release-sha"', content)
        self.assertIn('["git", "rev-parse", "HEAD"]', content)
