"""Reject ORM relations outside migrated ownership boundaries (ADR 0055)."""

from scripts.bootstrap import setup_django


def main() -> int:
    setup_django()
    from django.apps import apps

    from config.architecture import forbidden_model_relations, model_relations

    violations = forbidden_model_relations(model_relations(apps.get_models()))
    if violations:
        print("Forbidden context model relations:\n" + "\n".join(violations))
        return 1
    print("Migrated ORM context boundaries: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
