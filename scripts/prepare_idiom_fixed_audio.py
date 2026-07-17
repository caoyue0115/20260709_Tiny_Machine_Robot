from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from typing import Callable, Iterable
import wave

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if (PROJECT_ROOT / "src").is_dir() and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from src.providers.pcm_tail import (
        PCM_SAMPLE_RATE,
        QUIET_RMS_THRESHOLD,
        QUIET_WINDOW_MS,
        analyze_pcm16_tail,
        ensure_safe_pcm16_tail,
    )
except ModuleNotFoundError:  # pragma: no cover - used by the remote /tmp candidate workspace
    from pcm_tail import (  # type: ignore[no-redef]
        PCM_SAMPLE_RATE,
        QUIET_RMS_THRESHOLD,
        QUIET_WINDOW_MS,
        analyze_pcm16_tail,
        ensure_safe_pcm16_tail,
    )

CLOUD_FIXED_TEXTS = {
    "idiom_game/start": "好呀，我们玩成语接龙。小机仔先来：",
    "idiom_game/presence": "你还在吗？",
    "idiom_game/idle_exit": "那我们下次再玩吧。",
    "idiom_game/robot_no_reply_user_win": "小机仔暂时接不上啦，这局你赢。",
    "idiom_game/challenge_win": "挑战成功，这局你赢。",
    "idiom_game/mode_easy": "已切换到简单模式，连续接对轮数已重新计算。",
    "idiom_game/mode_normal": "已切换到普通模式，连续接对轮数已重新计算。",
    "idiom_game/mode_hard": "已切换到困难模式，连续接对轮数已重新计算。",
    "idiom_game/mode_full": "已切换到大师模式，连续接对轮数已重新计算。",
    "idiom_game/exit": "这局先到这里，小机仔把小本本合上啦。",
    "idiom_game/continue_prompt": "我们继续成语接龙吧，请说一个能接上的四字成语。",
    "idiom_game/retry": "我没听清，请再说一次。",
    "idiom_game/not_found": "这个我还没在成语词库里找到。你可以换一个四字成语再接。",
    "idiom_game/static_error": "成语语音暂时不可用，请稍后再试。",
}

SYNTHESIS_TEXT_OVERRIDES = {
    "idiom_game/start": "好呀，我们玩成语接龙。小机仔先来，",
}


class FixedCandidateError(ValueError):
    pass


Synthesizer = Callable[[str, Path, dict], dict | None]


def read_wav_pcm16(path: Path) -> bytes:
    try:
        with wave.open(str(path), "rb") as reader:
            valid = (
                reader.getframerate() == 16000
                and reader.getnchannels() == 1
                and reader.getsampwidth() == 2
                and reader.getcomptype() == "NONE"
            )
            if not valid:
                raise FixedCandidateError(f"fixed_audio_invalid_wav:{path.name}")
            pcm = reader.readframes(reader.getnframes())
    except (OSError, EOFError, wave.Error) as exc:
        raise FixedCandidateError(f"fixed_audio_unreadable_wav:{path.name}") from exc
    if not pcm or len(pcm) % 2:
        raise FixedCandidateError(f"fixed_audio_invalid_pcm16:{path.name}")
    return pcm


def write_wav_pcm16_atomic(path: Path, pcm: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with wave.open(str(temporary), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(16000)
            writer.writeframes(pcm)
        if read_wav_pcm16(temporary) != pcm:
            raise FixedCandidateError(f"fixed_audio_wav_verify_failed:{path.name}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_pcm16_atomic(path: Path, pcm: bytes) -> None:
    if not pcm or len(pcm) % 2:
        raise FixedCandidateError(f"fixed_audio_invalid_pcm16:{path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(pcm)
        if temporary.read_bytes() != pcm:
            raise FixedCandidateError(f"fixed_audio_pcm_verify_failed:{path.name}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _trim_excess_leading_quiet(pcm: bytes, *, keep_ms: int = 20) -> bytes:
    sample_count = len(pcm) // 2
    samples = struct.unpack(f"<{sample_count}h", pcm)
    window_samples = PCM_SAMPLE_RATE * QUIET_WINDOW_MS // 1000
    quiet_windows = 0
    start = 0
    while start + window_samples <= sample_count:
        window = samples[start : start + window_samples]
        rms = math.sqrt(sum(value * value for value in window) / len(window))
        if rms > QUIET_RMS_THRESHOLD:
            break
        quiet_windows += 1
        start += window_samples
    removable_ms = max(0, quiet_windows * QUIET_WINDOW_MS - keep_ms)
    removable_bytes = PCM_SAMPLE_RATE * removable_ms // 1000 * 2
    return pcm[removable_bytes:]


def prepare_candidate_pcm(pcm: bytes, *, max_bytes: int | None = None) -> bytes:
    try:
        prepared = ensure_safe_pcm16_tail(pcm)
    except ValueError as exc:
        raise FixedCandidateError(str(exc)) from exc
    if max_bytes is not None and len(prepared) > max_bytes:
        prepared = _trim_excess_leading_quiet(prepared)
    if max_bytes is not None and len(prepared) > max_bytes:
        raise FixedCandidateError("fixed_audio_board_size_exceeded")
    return prepared


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _candidate_specs(segment_ids: Iterable[str] | None = None) -> list[dict[str, object]]:
    specs: list[dict[str, object]] = []
    for segment_id, text in CLOUD_FIXED_TEXTS.items():
        relative = Path("cloud") / Path(segment_id).with_suffix(".wav")
        specs.append(
            {
                "kind": "cloud",
                "segment_id": segment_id,
                "text": text,
                "display_text": text,
                "synthesis_text": SYNTHESIS_TEXT_OVERRIDES.get(segment_id, text),
                "relative_path": relative.as_posix(),
                "max_bytes": None,
            }
        )
    if segment_ids is None:
        return specs

    requested = {str(item).strip() for item in segment_ids if str(item).strip()}
    if not requested:
        raise FixedCandidateError("fixed_audio_empty_segment_selection")
    for segment_id in requested:
        if "idioms/" in segment_id or "pinyin/" in segment_id:
            raise FixedCandidateError(f"fixed_audio_forbidden_segment:{segment_id}")
    known = {str(spec["segment_id"]) for spec in specs}
    unknown = requested - known
    if unknown:
        raise FixedCandidateError(f"fixed_audio_unknown_segment:{sorted(unknown)[0]}")
    return [spec for spec in specs if str(spec["segment_id"]) in requested]


def generate_candidate_batch(
    *,
    output_root: Path,
    manifest_path: Path,
    synthesizer: Synthesizer,
    model: str,
    voice: str,
    max_attempts: int,
    segment_ids: Iterable[str] | None = None,
    tempo_factor: float = 0.9,
    tail_ms: int = 500,
) -> dict:
    if max_attempts <= 0:
        raise FixedCandidateError("fixed_audio_invalid_max_attempts")
    output_root = Path(output_root).resolve()
    manifest_path = Path(manifest_path).resolve()
    raw_root = output_root / ".raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    failed_count = 0
    specs = _candidate_specs(segment_ids)
    if not 0.5 <= float(tempo_factor) <= 2.0:
        raise FixedCandidateError("fixed_audio_invalid_tempo_factor")
    if int(tail_ms) < 0:
        raise FixedCandidateError("fixed_audio_invalid_tail_ms")

    for spec in specs:
        segment_id = str(spec["segment_id"])
        if "idioms/" in segment_id or "pinyin/" in segment_id:
            raise FixedCandidateError(f"fixed_audio_forbidden_segment:{segment_id}")
        target = (output_root / str(spec["relative_path"])).resolve()
        if not target.is_relative_to(output_root):
            raise FixedCandidateError(f"fixed_audio_unsafe_output:{segment_id}")
        last_error = "fixed_audio_generation_failed"
        provider_metadata: dict = {}
        prepared: bytes | None = None
        for attempt in range(1, max_attempts + 1):
            raw_path = raw_root / f"{len(entries):03d}_{attempt}.wav"
            raw_path.unlink(missing_ok=True)
            try:
                provider_metadata = synthesizer(
                    str(spec["synthesis_text"]),
                    raw_path,
                    {
                        "segment_id": segment_id,
                        "category": "fixed",
                        "backend": "self_hosted",
                        "model": model,
                        "voice": voice,
                        "tempo_factor": float(tempo_factor),
                        "tail_ms": int(tail_ms),
                    },
                ) or {}
                source_pcm = read_wav_pcm16(raw_path)
                prepared = prepare_candidate_pcm(
                    source_pcm,
                    max_bytes=(
                        int(spec["max_bytes"])
                        if spec["max_bytes"] is not None
                        else None
                    ),
                )
                break
            except Exception as exc:
                last_error = str(exc) or exc.__class__.__name__
            finally:
                raw_path.unlink(missing_ok=True)

        if prepared is None:
            failed_count += 1
            entries.append(
                {
                    **spec,
                    "status": "failed",
                    "error": last_error,
                    "attempts": max_attempts,
                }
            )
            continue

        if spec["kind"] == "cloud":
            write_wav_pcm16_atomic(target, prepared)
        else:
            _write_pcm16_atomic(target, prepared)
        report = analyze_pcm16_tail(prepared)
        entries.append(
            {
                **spec,
                "status": "success",
                "error": None,
                "attempts": attempt,
                "bytes": target.stat().st_size,
                "pcm_bytes": len(prepared),
                "sha256": _sha256(target),
                "last_20ms_rms": round(report.last_20ms_rms, 3),
                "last_sample_abs": report.last_sample_abs,
                "quiet_tail_ms": report.quiet_tail_ms,
                "provider_request_id": provider_metadata.get("provider_request_id"),
                "provider": "self_hosted",
                "tempo_factor": float(tempo_factor),
                "tail_silence_ms": int(tail_ms),
            }
        )

    manifest = {
        "provider": "self_hosted",
        "model": model,
        "voice": voice,
        "failed_count": failed_count,
        "generated_count": len(entries) - failed_count,
        "requested_segment_ids": [str(spec["segment_id"]) for spec in specs],
        "tempo_factor": float(tempo_factor),
        "tail_silence_ms": int(tail_ms),
        "entries": entries,
    }
    _write_json_atomic(manifest_path, manifest)
    summary = {
        "failed_count": failed_count,
        "generated_count": manifest["generated_count"],
        "manifest_path": str(manifest_path),
        "output_root": str(output_root),
    }
    if failed_count:
        raise FixedCandidateError("fixed_audio_batch_failed")
    return summary


def _load_manifest(manifest_path: Path) -> dict:
    try:
        payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FixedCandidateError("fixed_audio_manifest_invalid") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise FixedCandidateError("fixed_audio_manifest_invalid")
    return payload


def validate_candidate_batch(*, candidate_root: Path, manifest_path: Path) -> dict:
    candidate_root = Path(candidate_root).resolve()
    manifest = _load_manifest(Path(manifest_path))
    if int(manifest.get("failed_count") or 0) != 0:
        raise FixedCandidateError("fixed_audio_manifest_has_failures")
    all_segment_ids = set(CLOUD_FIXED_TEXTS)
    requested = manifest.get("requested_segment_ids")
    if requested is None:
        expected_segment_ids = all_segment_ids
    elif isinstance(requested, list):
        expected_segment_ids = {str(item) for item in requested}
    else:
        raise FixedCandidateError("fixed_audio_manifest_segment_selection")
    if not expected_segment_ids or not expected_segment_ids.issubset(all_segment_ids):
        raise FixedCandidateError("fixed_audio_manifest_segment_selection")
    expected_count = len(expected_segment_ids)
    entries = manifest["entries"]
    if len(entries) != expected_count:
        raise FixedCandidateError("fixed_audio_manifest_entry_count")

    seen: set[str] = set()
    for entry in entries:
        segment_id = str(entry.get("segment_id") or "")
        if not segment_id or segment_id in seen:
            raise FixedCandidateError("fixed_audio_manifest_duplicate_segment")
        seen.add(segment_id)
        if "idioms/" in segment_id or "pinyin/" in segment_id:
            raise FixedCandidateError(f"fixed_audio_forbidden_segment:{segment_id}")
        candidate = (candidate_root / str(entry.get("relative_path") or "")).resolve()
        if not candidate.is_relative_to(candidate_root) or not candidate.is_file():
            raise FixedCandidateError(f"fixed_audio_candidate_missing:{segment_id}")
        if _sha256(candidate) != str(entry.get("sha256") or ""):
            raise FixedCandidateError(f"fixed_audio_sha256_mismatch:{segment_id}")
        pcm = read_wav_pcm16(candidate) if candidate.suffix.lower() == ".wav" else candidate.read_bytes()
        report = analyze_pcm16_tail(pcm)
        if not report.safe_tail:
            raise FixedCandidateError(f"fixed_audio_unsafe_tail:{segment_id}")
    if seen != expected_segment_ids:
        raise FixedCandidateError("fixed_audio_manifest_segment_selection")
    return {"entry_count": len(entries), "failed_count": 0}


def _copy_atomic(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def synthesize_self_hosted_wav(text: str, output_path: Path, context: dict) -> dict:
    from src.providers.self_hosted_realtime_tts import stream_self_hosted_realtime_tts_chunks
    from src.settings import settings as runtime_settings

    model = str(context.get("model") or runtime_settings.self_hosted_tts_model)
    voice = str(context.get("voice") or runtime_settings.self_hosted_tts_voice)
    tempo_factor = float(context.get("tempo_factor", runtime_settings.self_hosted_tts_fixed_tempo))
    tail_ms = int(context.get("tail_ms", runtime_settings.self_hosted_tts_post_roll_ms))
    if not model:
        raise FixedCandidateError("missing_self_hosted_tts_model")
    if not voice:
        raise FixedCandidateError("missing_self_hosted_tts_voice")
    if not 0.5 <= tempo_factor <= 2.0:
        raise FixedCandidateError("fixed_audio_invalid_tempo_factor")
    if tail_ms < 0:
        raise FixedCandidateError("fixed_audio_invalid_tail_ms")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    source_path = output_path.with_name(f".{output_path.stem}.source.wav")
    rendered_path = output_path.with_name(f".{output_path.stem}.rendered.wav")
    old_model = runtime_settings.self_hosted_tts_model
    old_voice = runtime_settings.self_hosted_tts_voice
    try:
        runtime_settings.self_hosted_tts_model = model
        runtime_settings.self_hosted_tts_voice = voice
        pcm = b"".join(
            stream_self_hosted_realtime_tts_chunks(
                [text],
                post_roll_ms=0,
            )
        )
        if not pcm or len(pcm) % 2:
            raise FixedCandidateError("self_hosted_tts_empty_audio")
        write_wav_pcm16_atomic(source_path, pcm)
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source_path),
                "-af",
                f"atempo={tempo_factor:.8f},apad=pad_dur={tail_ms / 1000.0:.3f}",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(rendered_path),
            ],
            check=True,
        )
        rendered_pcm = read_wav_pcm16(rendered_path)
        write_wav_pcm16_atomic(output_path, rendered_pcm)
    except FileNotFoundError as exc:
        raise FixedCandidateError("ffmpeg_not_found") from exc
    except subprocess.CalledProcessError as exc:
        raise FixedCandidateError("fixed_audio_ffmpeg_failed") from exc
    finally:
        runtime_settings.self_hosted_tts_model = old_model
        runtime_settings.self_hosted_tts_voice = old_voice
        source_path.unlink(missing_ok=True)
        rendered_path.unlink(missing_ok=True)
    return {
        "provider": "self_hosted",
        "backend": "self_hosted",
        "model": model,
        "voice": voice,
        "tempo_factor": tempo_factor,
        "tail_silence_ms": tail_ms,
    }


def install_cloud_candidates(
    *,
    candidate_root: Path,
    static_audio_root: Path,
    manifest_path: Path,
) -> None:
    validate_candidate_batch(candidate_root=candidate_root, manifest_path=manifest_path)
    manifest = _load_manifest(manifest_path)
    candidate_root = Path(candidate_root).resolve()
    static_audio_root = Path(static_audio_root).resolve()
    installed: set[str] = set()
    for entry in manifest["entries"]:
        if entry.get("kind") != "cloud":
            continue
        segment_id = str(entry["segment_id"])
        if segment_id not in CLOUD_FIXED_TEXTS:
            raise FixedCandidateError(f"fixed_audio_unexpected_cloud_segment:{segment_id}")
        source = candidate_root / str(entry["relative_path"])
        target = (static_audio_root / segment_id).with_suffix(".wav")
        _copy_atomic(source, target)
        if _sha256(target) != entry["sha256"]:
            raise FixedCandidateError(f"fixed_audio_install_verify_failed:{segment_id}")
        installed.add(segment_id)
    if installed != set(CLOUD_FIXED_TEXTS):
        raise FixedCandidateError("fixed_audio_cloud_install_incomplete")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare fixed idiom-game audio candidates.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate")
    generate.add_argument("--output-root", required=True)
    generate.add_argument("--manifest-path", required=True)
    generate.add_argument("--backend", choices=("self_hosted",), default="self_hosted")
    generate.add_argument("--max-attempts", type=int, default=3)
    generate.add_argument("--model")
    generate.add_argument("--voice")
    generate.add_argument("--tempo-factor", type=float, default=0.9)
    generate.add_argument("--tail-ms", type=int, default=500)
    generate.add_argument("--segment", dest="segment_ids", action="append")

    validate = subparsers.add_parser("validate")
    validate.add_argument("--candidate-root", required=True)
    validate.add_argument("--manifest-path", required=True)

    install_cloud = subparsers.add_parser("install-cloud")
    install_cloud.add_argument("--candidate-root", required=True)
    install_cloud.add_argument("--static-audio-root", required=True)
    install_cloud.add_argument("--manifest-path", required=True)

    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.command == "generate":
        from src.settings import settings as runtime_settings

        result = generate_candidate_batch(
            output_root=Path(args.output_root),
            manifest_path=Path(args.manifest_path),
            synthesizer=synthesize_self_hosted_wav,
            model=str(args.model or runtime_settings.self_hosted_tts_model),
            voice=str(args.voice or runtime_settings.self_hosted_tts_voice),
            max_attempts=args.max_attempts,
            segment_ids=args.segment_ids,
            tempo_factor=args.tempo_factor,
            tail_ms=args.tail_ms,
        )
    elif args.command == "validate":
        result = validate_candidate_batch(
            candidate_root=Path(args.candidate_root),
            manifest_path=Path(args.manifest_path),
        )
    else:
        install_cloud_candidates(
            candidate_root=Path(args.candidate_root),
            static_audio_root=Path(args.static_audio_root),
            manifest_path=Path(args.manifest_path),
        )
        result = {"installed": "cloud"}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
