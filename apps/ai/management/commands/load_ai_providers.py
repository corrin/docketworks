"""Idempotent per-vendor bootstrap using the same validation as Admin > Integrations."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from apps.ai.enums import AIProviderTypes
from apps.ai.models import AIProvider
from apps.ai.services.provider_configuration import (
    ProviderCreate,
    ProviderPatch,
    create_provider,
    set_default_provider,
    update_provider,
)
from apps.core.schemas import NonBlankText, NullableText


class SeedFields(BaseModel):
    """An optional vendor seed; null credentials leave that vendor unconfigured."""

    model_config = ConfigDict(extra="forbid")
    name: NonBlankText
    provider_type: AIProviderTypes
    model_name: NullableText
    api_key: NullableText = Field(repr=False)
    default: bool = False


class Seed(BaseModel):
    """Accept the existing fixture envelope without trusting its primary key."""

    model_config = ConfigDict(extra="forbid")
    model: str
    pk: int | None = None
    fields: SeedFields


SEEDS = TypeAdapter(list[Seed])


def load_vendor(fields: SeedFields) -> AIProvider | None:
    """Add a missing vendor or refill its exact empty seed; preserve configured rows."""
    if fields.api_key is None:
        return None
    if fields.model_name is None:
        raise CommandError(f"{fields.provider_type}: a supplied API key requires a model")
    payload = ProviderCreate(
        name=fields.name,
        provider_type=fields.provider_type,
        model_name=fields.model_name,
        api_key=fields.api_key,
    )
    rows = list(AIProvider.objects.select_for_update().filter(provider_type=fields.provider_type))
    if any(row.api_key is not None and row.model_name is not None for row in rows):
        return None
    if not rows:
        return create_provider(payload)
    matches = [
        row for row in rows if row.name == fields.name and row.model_name == fields.model_name
    ]
    if len(matches) != 1 or matches[0].api_key is not None:
        raise CommandError(
            f"{fields.provider_type}: incomplete entries require attention in Integrations"
        )
    return update_provider(matches[0].pk, ProviderPatch(api_key=fields.api_key))


def read_seeds(path: Path) -> list[Seed]:
    """Validate the whole fixture before entering the write transaction."""
    try:
        seeds = SEEDS.validate_json(path.read_text())
    except (OSError, ValidationError) as exc:
        # GPT: Pydantic's rendered error can contain the input API key.
        raise CommandError(
            "Cannot load AI fixture: check its JSON, fields and nonblank values"
        ) from exc
    if any(seed.model != "ai.aiprovider" for seed in seeds):
        raise CommandError("The fixture must contain only ai.aiprovider entries")
    if len({seed.fields.provider_type for seed in seeds}) != len(seeds):
        raise CommandError(
            "Bootstrap accepts one seed per vendor; manage additional models in Integrations"
        )
    if any(seed.fields.default and seed.fields.api_key is None for seed in seeds):
        raise CommandError("The selected bootstrap default requires an API key and model")
    if sum(seed.fields.default for seed in seeds) > 1:
        raise CommandError("The AI fixture must select at most one application default")
    return seeds


class Command(BaseCommand):
    """Seed missing AI integrations without overwriting administrator configuration."""

    help = "Load missing AI vendors from a fixture; preserve configured vendors and defaults"

    def add_arguments(self, parser: CommandParser) -> None:
        """Use the same fixture path for manual provisioning and instance setup."""
        parser.add_argument("fixture", type=Path)

    def handle(self, *_args: object, **options: object) -> None:
        """Validate the complete input before applying any vendor changes."""
        path = options["fixture"]
        if not isinstance(path, Path):
            raise TypeError("The fixture path must be a Path")
        seeds = read_seeds(path)
        try:
            with transaction.atomic():
                has_default = AIProvider.objects.filter(default=True).exists()
                for seed in seeds:
                    row = load_vendor(seed.fields)
                    if row is None:
                        self.stdout.write(
                            f"{seed.fields.provider_type}: existing or unset; preserved"
                        )
                        continue
                    if seed.fields.default and not has_default:
                        set_default_provider(row.pk)
                        has_default = True
                    self.stdout.write(f"{seed.fields.provider_type}: configured")
        except ValidationError as exc:
            raise CommandError(
                "A supplied AI key requires a name, supported vendor and model"
            ) from exc
