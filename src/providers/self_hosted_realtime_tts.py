from __future__ import annotations

import asyncio
import json
import queue
import threading
import urllib.request
import wave
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import websockets

from src.providers.pcm_tail import pcm16_silence
from src.settings import settings
from src.storage.files import output_audio_path


_PCM_FRAME_BYTES = 640


class SelfHostedRealtimeTtsError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _configured_voices(payload: dict[str, Any]) -> set[str]:
    voices = payload.get("voices")
    if isinstance(voices, list):
        return {str(item) for item in voices}
    if not isinstance(voices, dict):
        return set()
    nested = voices.get("payload")
    if not isinstance(nested, dict) or not isinstance(nested.get("voices"), list):
        return set()
    return {str(item) for item in nested["voices"]}


def self_hosted_realtime_tts_health() -> bool:
    if not (
        settings.self_hosted_tts_ws_url
        and settings.self_hosted_tts_health_url
        and settings.self_hosted_tts_model
        and settings.self_hosted_tts_voice
    ):
        return False
    try:
        with urllib.request.urlopen(
            settings.self_hosted_tts_health_url,
            timeout=2,
        ) as response:
            if not 200 <= int(response.status) < 300:
                return False
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False
    if payload.get("status") != "ok":
        return False
    service_model = str(payload.get("model") or "").strip()
    if service_model and service_model != settings.self_hosted_tts_model:
        return False
    voices = _configured_voices(payload)
    return not voices or settings.self_hosted_tts_voice in voices


def _split_pcm_frames(pcm: bytes, frame_bytes: int = _PCM_FRAME_BYTES) -> Iterator[bytes]:
    for offset in range(0, len(pcm), frame_bytes):
        yield pcm[offset : offset + frame_bytes]


class PreparedSelfHostedRealtimeTtsSession:
    def __init__(
        self,
        ws_url: str,
        voice: str,
        language: str,
        timeout_seconds: float,
        post_roll_ms: int,
    ) -> None:
        self.ws_url = ws_url
        self.voice = voice
        self.language = language
        self.timeout_seconds = timeout_seconds
        self.post_roll_ms = max(0, int(post_roll_ms))
        self._closed = threading.Event()

    def stream_text_chunks(self, text_chunks: Iterable[str]) -> Iterator[bytes]:
        segment_index = 0
        emitted_audio = False
        for raw_text in text_chunks:
            if self._closed.is_set():
                return
            text = str(raw_text or "").strip()
            if not text:
                continue
            segment_index += 1
            for chunk in self._stream_segment_raw(text, segment_index):
                if chunk:
                    emitted_audio = True
                    yield chunk
        if emitted_audio and self.post_roll_ms > 0 and not self._closed.is_set():
            yield from _split_pcm_frames(pcm16_silence(self.post_roll_ms))

    def _stream_segment_raw(self, text: str, segment_index: int) -> Iterator[bytes]:
        events: queue.Queue[tuple[str, Any]] = queue.Queue()
        request_id = f"robot-{threading.get_ident()}-{segment_index}"
        worker = threading.Thread(
            target=lambda: asyncio.run(self._run_segment_ws(text, request_id, events)),
            daemon=True,
        )
        worker.start()
        try:
            while not self._closed.is_set():
                item_type, payload = self._get_event(events)
                if item_type == "audio":
                    yield bytes(payload)
                    continue
                if item_type == "done":
                    return
                if item_type == "error":
                    self._raise_payload_error(payload)
        finally:
            worker.join(timeout=0.2)

    async def _run_segment_ws(
        self,
        text: str,
        request_id: str,
        events: queue.Queue[tuple[str, Any]],
    ) -> None:
        try:
            async with websockets.connect(
                self.ws_url,
                max_size=None,
                open_timeout=5,
                close_timeout=1,
            ) as websocket:
                await websocket.send(
                    json.dumps(
                        {
                            "type": "start",
                            "request_id": request_id,
                            "text": text,
                            "language": self.language,
                            "speaker": self.voice,
                        },
                        ensure_ascii=False,
                    )
                )
                while not self._closed.is_set():
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                    if isinstance(message, bytes):
                        if message:
                            events.put(("audio", message))
                        continue
                    payload = json.loads(message)
                    message_type = payload.get("type")
                    if message_type == "ready":
                        continue
                    if message_type == "done":
                        events.put(("done", payload))
                        return
                    if message_type == "error":
                        events.put(("error", payload))
                        return
                await websocket.send(json.dumps({"type": "cancel", "request_id": request_id}))
        except Exception as exc:
            events.put(
                (
                    "error",
                    {"code": "self_hosted_tts_error", "message": str(exc) or type(exc).__name__},
                )
            )

    def _get_event(self, events: queue.Queue[tuple[str, Any]]) -> tuple[str, Any]:
        try:
            return events.get(timeout=self.timeout_seconds)
        except queue.Empty as exc:
            self.close()
            raise SelfHostedRealtimeTtsError(
                "self_hosted_tts_timeout",
                "self-hosted tts timed out",
            ) from exc

    def _raise_payload_error(self, payload: Any) -> None:
        if isinstance(payload, dict):
            code = str(payload.get("code") or "self_hosted_tts_error")
            message = str(payload.get("message") or payload.get("error") or payload)
        else:
            code = "self_hosted_tts_error"
            message = str(payload)
        raise SelfHostedRealtimeTtsError(code, message)

    def close(self) -> None:
        self._closed.set()


def warmup_self_hosted_realtime_tts_session(
    *,
    post_roll_ms: int | None = None,
) -> PreparedSelfHostedRealtimeTtsSession:
    if not self_hosted_realtime_tts_health():
        raise SelfHostedRealtimeTtsError(
            "self_hosted_tts_unavailable",
            "self-hosted tts service is not healthy",
        )
    return PreparedSelfHostedRealtimeTtsSession(
        ws_url=settings.self_hosted_tts_ws_url,
        voice=settings.self_hosted_tts_voice,
        language=settings.tts_language_type,
        timeout_seconds=float(settings.tts_timeout_seconds),
        post_roll_ms=(
            settings.self_hosted_tts_post_roll_ms
            if post_roll_ms is None
            else int(post_roll_ms)
        ),
    )


def stream_self_hosted_realtime_tts_chunks(
    text_chunks: Iterable[str],
    prepared_session: PreparedSelfHostedRealtimeTtsSession | None = None,
    *,
    post_roll_ms: int | None = None,
) -> Iterator[bytes]:
    session = prepared_session or warmup_self_hosted_realtime_tts_session(
        post_roll_ms=post_roll_ms,
    )
    try:
        yield from session.stream_text_chunks(text_chunks)
    finally:
        session.close()


def synthesize_self_hosted_audio(text: str) -> tuple[str | None, str | None]:
    if not str(text or "").strip():
        return None, "empty_text"
    try:
        pcm = b"".join(stream_self_hosted_realtime_tts_chunks([text]))
    except SelfHostedRealtimeTtsError as exc:
        return None, exc.code
    except Exception:
        return None, "self_hosted_tts_error"
    if not pcm or len(pcm) % 2:
        return None, "self_hosted_tts_empty_audio"

    output = output_audio_path(suffix=".wav")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}.tmp{output.suffix}")
    try:
        with wave.open(str(temporary), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(16000)
            writer.writeframes(pcm)
        if temporary.stat().st_size <= 44:
            return None, "self_hosted_tts_empty_audio"
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return str(output), None
