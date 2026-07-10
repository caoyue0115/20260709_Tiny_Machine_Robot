from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.realtime_session import start_realtime_session_from_question
from src.settings import settings
from src.storage.realtime_store import InMemoryRealtimeSessionStore


def run_probe(question: str = "开始成语接龙") -> dict:
    store = InMemoryRealtimeSessionStore(base_url="http://127.0.0.1:18111")
    session = store.create_session(device_id=f"diagnose-idiom-static-{int(time.time() * 1000)}")
    started = time.perf_counter()
    start_realtime_session_from_question(
        store,
        session["session_id"],
        question,
        answer_mode="short",
    )
    store.wait_for_first_audio_chunk(
        session["session_id"],
        timeout_ms=settings.realtime_stream_first_chunk_timeout_ms,
    )
    first_audio_ms = int(round((time.perf_counter() - started) * 1000))
    chunks = list(
        store.consume_audio_stream(
            session["session_id"],
            idle_timeout_ms=settings.realtime_stream_idle_timeout_ms,
        )
    )
    elapsed_ms = int(round((time.perf_counter() - started) * 1000))
    updated = store.get_session(session["session_id"]) or {}
    trace = updated.get("trace") or {}
    return {
        "session_id": session["session_id"],
        "question": question,
        "status": updated.get("status"),
        "answer_text": updated.get("answer_text"),
        "static_audio_enabled": settings.static_audio_enabled,
        "static_audio_dir": str(settings.static_audio_path),
        "static_audio_chunk_size": settings.static_audio_chunk_size,
        "static_audio_used": trace.get("static_audio_used"),
        "static_audio_missing": trace.get("static_audio_missing"),
        "static_audio_segment_count": trace.get("static_audio_segment_count"),
        "first_audio_ms": first_audio_ms,
        "elapsed_ms": elapsed_ms,
        "audio_chunk_count": trace.get("audio_chunk_count"),
        "consumed_chunk_count": len(chunks),
        "audio_bytes": trace.get("audio_bytes"),
        "consumed_bytes": sum(len(chunk) for chunk in chunks),
        "done_ms": trace.get("done_ms"),
        "skill_name": trace.get("skill_name"),
        "error_code": updated.get("error_code"),
        "error_message": updated.get("error_message"),
    }


def main() -> int:
    result = run_probe()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "done":
        return 1
    if result["skill_name"] != "idiom_game":
        return 1
    if result["static_audio_used"] is not True:
        return 1
    if int(result["audio_chunk_count"] or 0) > 200:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
