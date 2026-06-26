import json
import subprocess
import tempfile
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
CUTOVER_LEGACY_SCRIPT = REPO_ROOT / "scripts" / "server" / "cutover_legacy_instance.sh"
LEGACY_ROLLBACK_SCRIPT = REPO_ROOT / "scripts" / "legacy_rollback.sh"
PREDEPLOY_BACKUP_SCRIPT = REPO_ROOT / "scripts" / "predeploy_backup.sh"
COMMON_SCRIPT = REPO_ROOT / "scripts" / "server" / "common.sh"
SERVER_SETUP_SCRIPT = REPO_ROOT / "scripts" / "server" / "server-setup.sh"
SERVER_README = REPO_ROOT / "scripts" / "server" / "README.md"
PRODUCTION_SETUP_DOC = REPO_ROOT / "docs" / "instance-setup-production.md"
DEMO_SETUP_DOC = REPO_ROOT / "docs" / "instance-setup-demo.md"
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

        self.assertIn("XERO_DEFAULT_USER_ID=", content)
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

    def test_instance_script_requires_xero_default_user_id(self) -> None:
        content = INSTANCE_SCRIPT.read_text()

        self.assertIn('[[ -z "${XERO_DEFAULT_USER_ID:-}" ]]', content)
        self.assertIn('MISSING+=("XERO_DEFAULT_USER_ID")', content)
        self.assertNotIn("UNCONFIGURED_XERO_DEFAULT_USER_ID", content)

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
        self.assertIn("printf '%s\\n' '$sha' > '$release_dir/.release-sha'", content)
        self.assertIn("python3.12 -m venv '$release_dir/.venv'", content)
        self.assertIn("npm run check:typed-router", content)
        self.assertIn("npm run build", content)
        self.assertIn("npm run manual:build", content)
        self.assertIn("rm -rf node_modules", content)
        self.assertIn("touch '$release_dir/.complete'", content)

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

    def test_node_major_parsing_accepts_patch_versions(self) -> None:
        common_content = COMMON_SCRIPT.read_text()
        release_utils_content = RELEASE_UTILS.read_text()
        server_setup_content = SERVER_SETUP_SCRIPT.read_text()

        self.assertIn("node_major_from_nvmrc()", common_content)
        self.assertIn("node_major_from_nvmrc()", server_setup_content)
        self.assertIn(
            "sed -nE 's/^[[:space:]]*v?([0-9]+).*/\\1/p'",
            common_content,
        )
        self.assertIn(
            "sed -nE 's/^[[:space:]]*v?([0-9]+).*/\\1/p' .nvmrc",
            release_utils_content,
        )
        self.assertNotIn("tr -d 'v[:space:]'", release_utils_content)
        self.assertNotIn("tr -d 'v[:space:]'", server_setup_content)

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

    def test_instance_mediafiles_are_owned_for_app_writes_and_nginx_reads(
        self,
    ) -> None:
        content = INSTANCE_SCRIPT.read_text()

        self.assertIn(
            'chown "$INSTANCE_USER:www-data" "$INSTANCE_DIR/mediafiles"',
            content,
        )
        self.assertIn('chmod 750 "$INSTANCE_DIR/mediafiles"', content)

    def test_xero_default_user_id_docs_match_required_create_time_workflow(
        self,
    ) -> None:
        docs = "\n".join(
            [
                CREDENTIALS_TEMPLATE.read_text(),
                SERVER_README.read_text(),
                PRODUCTION_SETUP_DOC.read_text(),
                DEMO_SETUP_DOC.read_text(),
            ]
        )

        self.assertIn("XERO_DEFAULT_USER_ID must be present", docs)
        self.assertIn("required before `instance.sh create`", docs)
        self.assertNotIn("leave blank for now", docs)
        self.assertNotIn("Create the instance first", docs)
        self.assertNotIn("copy that UUID", docs)
        self.assertNotIn("Copy the relevant user ID into credentials.env", docs)
        self.assertNotIn("then run `instance.sh reconfigure`", docs)

    def test_release_cleanup_is_deploy_integrated_and_reachability_based(self) -> None:
        deploy_content = DEPLOY_SCRIPT.read_text()
        release_utils_content = RELEASE_UTILS.read_text()

        self.assertIn("--cleanup-releases", deploy_content)
        self.assertIn("cleanup_incomplete_releases", deploy_content)
        self.assertIn('cleanup_unreferenced_releases "$TARGET_SHA"', deploy_content)
        self.assertIn("release_is_referenced()", release_utils_content)
        self.assertIn(
            'read_env_value "$instance_dir/deploy-state.env" PREVIOUS_SHA',
            release_utils_content,
        )
        self.assertIn("Removing unreferenced release", release_utils_content)

    def test_legacy_cutover_rollback_artifacts_are_root_trusted(self) -> None:
        cutover_content = CUTOVER_LEGACY_SCRIPT.read_text()
        rollback_content = LEGACY_ROLLBACK_SCRIPT.read_text()
        predeploy_backup_content = PREDEPLOY_BACKUP_SCRIPT.read_text()

        self.assertIn(
            'ROLLBACK_DIR="$CONFIG_DIR/legacy-rollbacks/$INSTANCE"',
            cutover_content,
        )
        self.assertIn('mkdir -p "$ROLLBACK_DIR"', cutover_content)
        self.assertIn('chown root:root "$ROLLBACK_DIR"', cutover_content)
        self.assertIn('chmod 700 "$ROLLBACK_DIR"', cutover_content)
        self.assertIn(
            'SNAPSHOT="$ROLLBACK_DIR/legacy_${OLD_SHORT}.tar.gz"',
            cutover_content,
        )
        self.assertIn('SNAPSHOT_TMP="$SNAPSHOT.tmp.$$"', cutover_content)
        self.assertIn('tar -czf "$SNAPSHOT_TMP"', cutover_content)
        self.assertIn('tar -tzf "$SNAPSHOT_TMP" >/dev/null', cutover_content)
        self.assertIn('mv "$SNAPSHOT_TMP" "$SNAPSHOT"', cutover_content)
        self.assertIn('chown root:root "$SNAPSHOT"', cutover_content)
        self.assertNotIn(
            'chown "$INST_USER:$INST_USER" "$SNAPSHOT"',
            cutover_content,
        )
        self.assertLess(
            cutover_content.index("for unit in gunicorn celery-worker celery-beat"),
            cutover_content.index('tar -czf "$SNAPSHOT_TMP"'),
        )

        self.assertIn(
            'ROLLBACK_DIR="$CONFIG_DIR/legacy-rollbacks/$INSTANCE"',
            rollback_content,
        )
        self.assertIn('ROLLBACK_DIR_MODE="$(stat -c', rollback_content)
        self.assertIn('"0:0:700"', rollback_content)
        self.assertIn(
            'SNAPSHOT_MATCHES=("$ROLLBACK_DIR"/legacy_"$OLD_PREFIX"*.tar.gz)',
            rollback_content,
        )
        self.assertIn(
            'UNITS_DIR="$ROLLBACK_DIR/legacy_${OLD_SHORT}.units"',
            rollback_content,
        )
        self.assertIn(
            'NGINX_BACKUP="$ROLLBACK_DIR/legacy_${OLD_SHORT}.nginx.conf"',
            rollback_content,
        )
        self.assertIn(
            'DB_MATCHES=("$ROLLBACK_DIR"/predeploy_*_"$OLD_SHORT".sql.gz)',
            rollback_content,
        )
        self.assertIn('DB_DUMP_MODE="$(stat -c', rollback_content)
        self.assertIn(
            "Legacy predeploy backup must be root:root mode 600",
            rollback_content,
        )
        self.assertIn('gunzip -t "$DB_DUMP"', rollback_content)
        self.assertNotIn(
            'DB_MATCHES=("$BACKUP_DIR"/predeploy_*_"$OLD_SHORT".sql.gz)',
            rollback_content,
        )
        self.assertNotIn(
            'SNAPSHOT_MATCHES=("$BACKUP_DIR"/legacy_"$OLD_PREFIX"*.tar.gz)',
            rollback_content,
        )

        self.assertIn(
            'ROLLBACK_DIR="$CONFIG_DIR/legacy-rollbacks/$INSTANCE"',
            predeploy_backup_content,
        )
        self.assertIn(
            'LEGACY_MANIFEST="$ROLLBACK_DIR/legacy_${HASH}.manifest"',
            predeploy_backup_content,
        )
        self.assertIn('if [[ -f "$LEGACY_MANIFEST" ]]; then', predeploy_backup_content)
        self.assertIn('OUT_DIR="$ROLLBACK_DIR"', predeploy_backup_content)
        self.assertIn('chown root:root "$OUT"', predeploy_backup_content)
        self.assertIn('chmod 600 "$OUT"', predeploy_backup_content)

    def test_legacy_rollback_preserves_backups_and_uses_restored_venv(self) -> None:
        content = LEGACY_ROLLBACK_SCRIPT.read_text()

        self.assertNotIn('chown -R "$INST_USER:$INST_USER" "$INSTANCE_DIR"', content)
        self.assertIn('[[ "$(basename "$path")" == "backups" ]] && continue', content)
        self.assertIn("grep -Fx './manage.py'", content)
        self.assertIn("grep -Fx './.venv/bin/python'", content)
        self.assertIn('LEGACY_PYTHON="$INSTANCE_DIR/.venv/bin/python"', content)
        self.assertIn('"$3" manage.py sync_sequences', content)
        self.assertNotIn("SHARED_VENV", content)

    def test_deploy_uses_single_legacy_checkout_predicate(self) -> None:
        content = DEPLOY_SCRIPT.read_text()

        self.assertIn("is_legacy_checkout()", content)
        self.assertIn(
            '[[ -d "$instance_dir/.git" && ! -L "$instance_dir/current" ]]',
            content,
        )
        self.assertIn('if is_legacy_checkout "$instance_dir"; then', content)
        self.assertIn(
            'if [[ -n "$previous_sha" ]] && ! is_legacy_checkout "$instance_dir"; then',
            content,
        )
        self.assertIn(
            "sudo $SCRIPT_DIR/../legacy_rollback.sh $instance ${previous_sha:0:12}",
            content,
        )
        self.assertIn(
            "sudo $SCRIPT_DIR/../predeploy_rollback.sh $instance ${previous_sha:0:12}",
            content,
        )
        self.assertNotIn(
            'if [[ -n "$previous_sha" && ! -d "$instance_dir/.git" ]]',
            content,
        )

    def test_server_readme_documents_both_rollback_paths(self) -> None:
        content = SERVER_README.read_text()

        self.assertIn("predeploy_rollback.sh", content)
        self.assertIn("legacy_rollback.sh", content)
        self.assertIn("first legacy checkout cutover", content)

    def test_typed_router_drift_is_checked_in_release_build(self) -> None:
        deploy_content = DEPLOY_SCRIPT.read_text()
        release_utils_content = RELEASE_UTILS.read_text()

        self.assertIn("npm run check:typed-router", release_utils_content)
        self.assertNotIn(
            "server generated a different frontend/src/typed-router.d.ts",
            deploy_content,
        )
        self.assertNotIn("frontend/src/typed-router.d.ts", deploy_content)
