from __future__ import annotations

import json
import sys
import tempfile
import wave
from pathlib import Path
from unittest import mock

from tests._stubs import install_dependency_stubs


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
install_dependency_stubs()


def test_settings_default_to_approved_self_hosted_model_voice_and_tail() -> None:
    from src.settings import Settings

    configured = Settings(_env_file=None)

    assert configured.realtime_tts_provider == "self_hosted"
    assert configured.self_hosted_tts_model == "qwen3-tts-base-1_7b"
    assert configured.self_hosted_tts_voice == "clone_coffee_20s_v1"
    assert configured.self_hosted_tts_post_roll_ms == 500
    assert configured.self_hosted_tts_fixed_tempo == 0.9


def test_stream_appends_one_five_hundred_ms_post_roll_after_all_segments() -> None:
    from src.providers.self_hosted_realtime_tts import PreparedSelfHostedRealtimeTtsSession

    session = PreparedSelfHostedRealtimeTtsSession(
        ws_url="ws://127.0.0.1:18122/tts/realtime",
        voice="clone_coffee_20s_v1",
        language="Chinese",
        timeout_seconds=1.0,
        post_roll_ms=500,
    )
    rendered: list[tuple[str, int]] = []

    def fake_stream(text: str, segment_index: int):
        rendered.append((text, segment_index))
        yield bytes([segment_index, 0]) * 4

    with mock.patch.object(session, "_stream_segment_raw", side_effect=fake_stream):
        chunks = list(session.stream_text_chunks(["第一段", "第二段"]))

    assert rendered == [("第一段", 1), ("第二段", 2)]
    assert b"".join(chunks) == (
        (b"\x01\x00" * 4)
        + (b"\x02\x00" * 4)
        + (b"\x00\x00" * (500 * 16))
    )


def test_stream_with_no_text_does_not_emit_silence_only_audio() -> None:
    from src.providers.self_hosted_realtime_tts import PreparedSelfHostedRealtimeTtsSession

    session = PreparedSelfHostedRealtimeTtsSession(
        ws_url="ws://127.0.0.1:18122/tts/realtime",
        voice="clone_coffee_20s_v1",
        language="Chinese",
        timeout_seconds=1.0,
        post_roll_ms=500,
    )

    assert list(session.stream_text_chunks(["", ""])) == []


def test_health_requires_ok_service_and_configured_voice() -> None:
    from src.providers import self_hosted_realtime_tts as provider

    payload = {
        "status": "ok",
        "model": "qwen3-tts-base-1_7b",
        "voices": {"payload": {"voices": ["clone_coffee_20s_v1"]}},
    }
    response = mock.MagicMock()
    response.status = 200
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__.return_value = response

    with mock.patch.object(provider.settings, "self_hosted_tts_voice", "clone_coffee_20s_v1"), mock.patch.object(
        provider.settings, "self_hosted_tts_model", "qwen3-tts-base-1_7b"
    ), mock.patch.object(provider.urllib.request, "urlopen", return_value=response):
        assert provider.self_hosted_realtime_tts_health() is True

    payload["voices"]["payload"]["voices"] = ["other-voice"]
    response.read.return_value = json.dumps(payload).encode("utf-8")
    with mock.patch.object(provider.urllib.request, "urlopen", return_value=response):
        assert provider.self_hosted_realtime_tts_health() is False


def test_one_shot_synthesis_writes_16k_pcm_wav_atomically() -> None:
    from src.providers import self_hosted_realtime_tts as provider

    pcm = b"\x01\x00\x02\x00" + (b"\x00\x00" * (500 * 16))
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "reply.wav"
        with mock.patch.object(provider, "stream_self_hosted_realtime_tts_chunks", return_value=iter([pcm])), mock.patch.object(
            provider, "output_audio_path", return_value=output
        ):
            path, error = provider.synthesize_self_hosted_audio("你好")

        assert error is None
        assert path == str(output)
        with wave.open(str(output), "rb") as reader:
            assert (reader.getframerate(), reader.getnchannels(), reader.getsampwidth()) == (16000, 1, 2)
            assert reader.readframes(reader.getnframes()) == pcm


def test_active_runtime_has_no_dashscope_tts_import_or_http_fallback() -> None:
    session_source = (ROOT / "src" / "services" / "realtime_session.py").read_text(encoding="utf-8")
    worker_source = (ROOT / "src" / "workers" / "pipeline.py").read_text(encoding="utf-8")
    app_source = (ROOT / "src" / "app.py").read_text(encoding="utf-8")

    assert "src.providers.realtime_tts" not in session_source
    assert "src.providers.tts" not in session_source
    assert "synthesize_self_hosted_audio as synthesize_audio" in session_source
    assert "src.providers.tts" not in worker_source
    assert "synthesize_self_hosted_audio" in worker_source
    assert "src.providers.tts" not in app_source
