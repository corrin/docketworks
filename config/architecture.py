"""Executable ORM ownership rules for migrated contexts (ADR 0055)."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from django.db.models import Model

# GPT: this is an ownership manifest, not a list of permitted violations.
# An ownership slice adds its package here and must pass without exceptions.
MIGRATED_CONTEXTS = {"apps.platform.integrations": "platform"}

CONTEXT_DEPENDENCIES: dict[str, frozenset[str]] = {
    "kernel": frozenset(),
    "platform": frozenset({"kernel"}),
    "identity": frozenset(),
    "crm": frozenset({"identity"}),
    "configuration": frozenset({"crm"}),
    "work": frozenset({"configuration", "crm", "identity"}),
    "workforce": frozenset({"work", "configuration", "identity"}),
    "procurement": frozenset({"work", "crm", "configuration", "identity"}),
    "finance": frozenset({"work", "crm", "configuration"}),
    "planning": frozenset({"work", "identity"}),
    "knowledge": frozenset({"work", "identity"}),
    # GPT: these contexts consume queries/commands, not cross-context ORM relations.
    "reporting": frozenset(),
    "search": frozenset(),
    "workflows": frozenset(),
}


@dataclass(frozen=True)
class ModelRelation:
    """A concrete forward ORM dependency, irrespective of its import spelling."""

    source: type[Model]
    target: type[Model]
    field: str


def model_relations(models: Iterable[type[Model]]) -> Iterable[ModelRelation]:
    """Read concrete forward relations, including resolved string FKs and M2Ms."""
    for model in models:
        for field in (*model._meta.local_fields, *model._meta.local_many_to_many):
            if field.related_model is not None:
                yield ModelRelation(model, field.related_model, field.name)


def _context(model: type[Model], packages: Mapping[str, str]) -> str | None:
    for package, context in packages.items():
        if model.__module__ == package or model.__module__.startswith(package + "."):
            return context
    return None


def forbidden_model_relations(
    relations: Iterable[ModelRelation],
    packages: Mapping[str, str] = MIGRATED_CONTEXTS,
) -> list[str]:
    """Reject forbidden directions without grandfathering individual relations."""
    violations = []
    for relation in relations:
        source = _context(relation.source, packages)
        target = _context(relation.target, packages)
        if source == target:
            continue
        if source is None and target != "platform":
            continue
        if source is not None and target in CONTEXT_DEPENDENCIES[source]:
            continue
        violations.append(
            f"{relation.source._meta.label}.{relation.field} -> {relation.target._meta.label}"
        )
    return sorted(violations)
