from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    host: str = "0.0.0.0"
    port: int = 8010
    redis_url: str = "redis://redis:6379/0"
    sqlite_path: str = "./data/tasks.db"
    public_base_url: str = "http://localhost:8010"
    ota_artifact_dir: str = "./data/ota_artifacts"
    queue_name: str = "tiny_coffee_tasks"
    enabled_skills: str = "idiom_game"
    idiom_game_ttl_seconds: int = 900
    idiom_game_robot_difficulty: str = "easy"
    idiom_game_target_user_turns: int = 0
    idiom_game_llm_judge_enabled: bool = True
    idiom_game_llm_judge_min_confidence: float = 0.8
    max_upload_mb: int = 3
    max_audio_seconds: int = 8
    chunk_size: int = 300
    chunk_overlap: int = 50
    top_k: int = 2
    bm25_weight: float = 0.55
    min_top_score: float = 0.35
    min_top_score_no_keyword: float = 0.5
    embedding_model: str = "hash-jieba-768"
    embedding_dim: int = 768
    llm_provider: str = "dashscope"
    llm_model: str = "qwen3.5-flash-2026-02-23"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 256
    asr_provider: str = "dashscope"
    asr_fallback_provider: str = "dashscope"
    asr_provider_override_device_ids: str = ""
    asr_provider_override_provider: str = ""
    asr_model: str = "paraformer-realtime-v2"
    asr_timeout_seconds: float = 30.0
    asr_language_hints: str = "zh"
    asr_vocabulary_id: str = ""
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com"
    dashscope_tts_model: str = "qwen3-tts-vc-2026-01-22"
    tts_voice: str = ""
    realtime_tts_model: str = "qwen3-tts-flash-realtime-2025-11-27"
    realtime_tts_voice: str = ""
    realtime_tts_provider: str = "self_hosted"
    self_hosted_tts_ws_url: str = "ws://127.0.0.1:18122/tts/realtime"
    self_hosted_tts_health_url: str = "http://127.0.0.1:18122/health"
    self_hosted_tts_model: str = "qwen3-tts-base-1_7b"
    self_hosted_tts_voice: str = "clone_coffee_20s_v1"
    self_hosted_tts_post_roll_ms: int = 500
    self_hosted_tts_fixed_tempo: float = 0.9
    tts_language_type: str = "Chinese"
    tts_instructions: str = "请使用明亮、亲切、有一点活泼感的中文声音，语速自然，适合咖啡小问答播报。"
    tts_timeout_seconds: int = 20
    dashscope_playback_rate: float = 1.0
    request_timeout_seconds: int = 30
    default_sample_rate: int = 16000
    default_sample_width_bits: int = 16
    default_channels: int = 1
    audio_content_type: str = "audio/wav"
    realtime_enabled: bool = True
    realtime_session_ttl_seconds: int = 900
    realtime_stream_first_chunk_timeout_ms: int = 5000
    realtime_stream_idle_timeout_ms: int = 8000
    realtime_audio_sample_rate: int = 16000
    realtime_audio_sample_width_bits: int = 16
    realtime_audio_channels: int = 1
    realtime_audio_endian: str = "little"
    realtime_audio_enable_opus: bool = True
    realtime_audio_opus_sample_rate: int = 16000
    realtime_audio_opus_channels: int = 1
    realtime_audio_opus_frame_duration_ms: int = 60
    realtime_audio_opus_bitrate: int = 24000
    realtime_tts_min_chars: int = 8
    realtime_tts_max_chars: int = 40
    realtime_tts_first_segment_min_chars: int = 6
    realtime_tts_first_segment_max_chars: int = 10
    realtime_tts_warmup_enabled: bool = True
    realtime_llm_compact_top_k: int = 1
    realtime_llm_compact_snippet_chars: int = 36
    static_audio_enabled: bool = True
    static_audio_dir: str = "./data/static_audio"
    static_audio_chunk_size: int = 4096
    project_name: str = "Tiny Coffee Machine"
    version: str = "0.1.0"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def project_root(self) -> Path:
        override = getattr(self, "_project_root_override", None)
        if override is not None:
            return override
        return Path(__file__).resolve().parents[1]

    @project_root.setter
    def project_root(self, value: Path) -> None:
        object.__setattr__(self, "_project_root_override", Path(value))

    @project_root.deleter
    def project_root(self) -> None:
        object.__setattr__(self, "_project_root_override", None)

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def incoming_dir(self) -> Path:
        return self.data_dir / "incoming"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @property
    def static_audio_path(self) -> Path:
        raw = Path(self.static_audio_dir)
        if raw.is_absolute():
            return raw
        return (self.project_root / raw).resolve()

    @property
    def ota_artifact_path(self) -> Path:
        raw = Path(self.ota_artifact_dir)
        if raw.is_absolute():
            return raw
        return (self.project_root / raw).resolve()

    @property
    def kb_dir(self) -> Path:
        override = getattr(self, "_kb_dir_override", None)
        if override is not None:
            return override
        return self.data_dir / "coffee"

    @kb_dir.setter
    def kb_dir(self, value: Path) -> None:
        object.__setattr__(self, "_kb_dir_override", Path(value))

    @kb_dir.deleter
    def kb_dir(self) -> None:
        object.__setattr__(self, "_kb_dir_override", None)

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def indices_dir(self) -> Path:
        override = getattr(self, "_indices_dir_override", None)
        if override is not None:
            return override
        return self.project_root / "indices"

    @indices_dir.setter
    def indices_dir(self, value: Path) -> None:
        object.__setattr__(self, "_indices_dir_override", Path(value))

    @indices_dir.deleter
    def indices_dir(self) -> None:
        object.__setattr__(self, "_indices_dir_override", None)

    @property
    def sqlite_file(self) -> Path:
        raw = Path(self.sqlite_path)
        if raw.is_absolute():
            return raw
        return (self.project_root / raw).resolve()

    @property
    def asr_language_hints_list(self) -> list[str]:
        return [part.strip() for part in self.asr_language_hints.split(",") if part.strip()]


settings = Settings()
