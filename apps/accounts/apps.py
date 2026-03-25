from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "User Accounts"

    def ready(self) -> None:
        # Import here to avoid AppRegistryNotReady during Django startup
        import apps.workflow.extensions  # noqa: F401
