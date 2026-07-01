from __future__ import annotations

from pathlib import Path
from unittest import mock

from src.settings import Settings


def test_tiny_defaults_identify_public_project_and_realtime_chain() -> None:
    settings = Settings(_env_file=None)

    assert settings.project_name == "Tiny Coffee Machine"
    assert settings.queue_name == "tiny_coffee_tasks"
    assert settings.llm_provider == "dashscope"
    assert settings.llm_model == "qwen3.5-flash-2026-02-23"
    assert settings.asr_provider == "volcengine"
    assert settings.asr_fallback_provider == "dashscope"
    assert settings.asr_model == "paraformer-realtime-v2"
    assert settings.realtime_enabled is True
    assert settings.realtime_audio_enable_opus is True
    assert settings.realtime_tts_model == "qwen3-tts-vc-realtime-2026-01-15"
    assert (
        settings.tts_instructions
        == "请使用明亮、亲切、有一点活泼感的中文声音，语速自然，适合咖啡小问答播报。"
    )
    assert Settings.model_config.get("env_file") == ".env"
    assert Settings.model_config.get("extra") == "ignore"


def test_tiny_paths_use_coffee_data_and_do_not_use_old_domain_name(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    with mock.patch.object(settings, "project_root", tmp_path):
        assert settings.kb_dir == tmp_path / "data" / "coffee"
        assert settings.indices_dir == tmp_path / "indices"
        assert "coffee" in str(settings.kb_dir)
