from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "User Accounts"

    def ready(self) -> None:
        # Imported for its import-time side effects only, so the name is
        # deliberately unused (F401). Deferred to ready() because importing it
        # at module level raises AppRegistryNotReady during Django startup.
        import apps.workflow.extensions  # noqa: F401
