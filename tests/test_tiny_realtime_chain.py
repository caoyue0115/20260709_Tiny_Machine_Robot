from __future__ import annotations

import asyncio
import json
from unittest import mock

from src.api import realtime


class _FakeWebSocket:
    def __init__(self, incoming: list[dict]) -> None:
        self._incoming = list(incoming)
        self.accepted = False
        self.sent_json: list[dict] = []
        self.close_code: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def receive(self) -> dict:
        if self._incoming:
            return self._incoming.pop(0)
        return {"type": "websocket.disconnect"}

    async def send_json(self, payload: dict) -> None:
        self.sent_json.append(payload)

    async def close(self, code: int = 1000) -> None:
        self.close_code = code


class _FakeRealtimeAsr:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def drain_events(self) -> list:
        return []


def test_normalized_realtime_default_uses_settings_asr_provider() -> None:
    with mock.patch.object(realtime.settings, "asr_provider", " VolcEngine "):
        provider = realtime._normalize_default_asr_provider()

    assert provider == "volcengine"


def test_normalized_realtime_default_falls_back_to_dashscope_for_invalid_settings() -> None:
    with mock.patch.object(realtime.settings, "asr_provider", "invalid-provider"):
        provider = realtime._normalize_default_asr_provider()

    assert provider == "dashscope"


def test_realtime_provider_choices_include_volcengine_and_dashscope() -> None:
    assert "volcengine" in realtime.ASR_PROVIDER_CHOICES
    assert "dashscope" in realtime.ASR_PROVIDER_CHOICES


def test_stream_start_uses_validated_default_when_settings_provider_is_invalid() -> None:
    websocket = _FakeWebSocket(
        [
            {"type": "websocket.receive", "text": json.dumps({"type": "start", "run_asr": True})},
            {"type": "websocket.receive", "text": json.dumps({"type": "end"})},
        ]
    )
    fake_asr = _FakeRealtimeAsr()

    with mock.patch.object(realtime.settings, "asr_provider", "invalid-provider"), mock.patch.object(
        realtime,
        "create_realtime_asr_session",
        return_value=fake_asr,
    ) as factory:
        asyncio.run(
            realtime.stream_opus_realtime_session(
                websocket,
                x_device_id="pc-stream",
                x_audio_packetization="framed-v1",
                x_audio_format="opus",
                x_opus_sample_rate=16000,
                x_opus_channels=1,
                x_opus_frame_duration_ms=60,
                x_original_pcm_bytes=None,
            )
        )

    factory.assert_called_once()
    assert factory.call_args.kwargs["provider"] == realtime.ASR_PROVIDER_DASHSCOPE
    assert fake_asr.started
    assert websocket.sent_json[-1]["error_code"] == "empty_decoded_audio"
    assert websocket.close_code == 1003
