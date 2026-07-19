import importlib.util
import types
from pathlib import Path
from typing import ClassVar
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.workflow.enums import AIProviderTypes
from apps.workflow.models import AIProvider

SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "restore_checks"
    / "check_ai_providers.py"
)


def load_check_ai_providers() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("check_ai_providers", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load check_ai_providers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CheckAIProvidersTests(TestCase):
    check: ClassVar[types.ModuleType]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.check = load_check_ai_providers()

    def test_missing_provider_fails_validation(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Claude: Not configured"):
            self.check.validate_chat_provider(AIProviderTypes.ANTHROPIC)

    def test_provider_error_propagates(self) -> None:
        AIProvider.objects.create(
            name="Claude",
            provider_type=AIProviderTypes.ANTHROPIC,
            api_key="test-key",
            model_name="test-model",
        )
        service = MagicMock()
        service.get_text_response.side_effect = RuntimeError("provider unavailable")

        with (
            patch.object(self.check, "LLMService", return_value=service),
            self.assertRaisesRegex(RuntimeError, "provider unavailable"),
        ):
            self.check.validate_chat_provider(AIProviderTypes.ANTHROPIC)
