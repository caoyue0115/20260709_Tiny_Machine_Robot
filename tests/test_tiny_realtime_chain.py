from __future__ import annotations

from unittest import mock

from src.api import realtime


def test_normalized_realtime_default_uses_settings_asr_provider() -> None:
    with mock.patch.object(realtime.settings, "asr_provider", "volcengine"):
        provider = str(realtime.settings.asr_provider or realtime.ASR_PROVIDER_DASHSCOPE).strip().lower()

    assert provider == "volcengine"


def test_realtime_provider_choices_include_volcengine_and_dashscope() -> None:
    assert "volcengine" in realtime.ASR_PROVIDER_CHOICES
    assert "dashscope" in realtime.ASR_PROVIDER_CHOICES
