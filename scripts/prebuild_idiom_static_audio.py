from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Callable, NamedTuple
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _read_dotenv_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env_value(key: str, default: str) -> str:
    return os.getenv(key) or _DOTENV_VALUES.get(key, default)


try:
    from src.settings import settings
except ModuleNotFoundError as exc:  # pragma: no cover - exercised by subprocess CLI tests
    if exc.name != "pydantic_settings":
        raise

    _DOTENV_VALUES = _read_dotenv_values(Path(os.getenv("IDIOM_STATIC_AUDIO_ENV_FILE", ROOT / ".env")))

    class _FallbackSettings:
        dashscope_api_key = _env_value("DASHSCOPE_API_KEY", "")
        dashscope_base_url = _env_value("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com")
        dashscope_tts_model = _env_value("DASHSCOPE_TTS_MODEL", "qwen3-tts-vc-2026-01-22")
        tts_voice = _env_value("TTS_VOICE", "")
        realtime_tts_model = _env_value("REALTIME_TTS_MODEL", "qwen3-tts-flash-realtime-2025-11-27")
        realtime_tts_voice = _env_value("REALTIME_TTS_VOICE", "")
        tts_language_type = _env_value("TTS_LANGUAGE_TYPE", "Chinese")
        tts_instructions = _env_value(
            "TTS_INSTRUCTIONS",
            "请使用明亮、亲切、有一点活泼感的中文声音，语速自然，适合成语接龙播报。",
        )
        tts_timeout_seconds = int(_env_value("TTS_TIMEOUT_SECONDS", "20"))
        realtime_audio_sample_rate = int(_env_value("REALTIME_AUDIO_SAMPLE_RATE", "16000"))
        realtime_audio_sample_width_bits = int(_env_value("REALTIME_AUDIO_SAMPLE_WIDTH_BITS", "16"))
        realtime_audio_channels = int(_env_value("REALTIME_AUDIO_CHANNELS", "1"))

        @property
        def static_audio_path(self) -> Path:
            raw = Path(_env_value("STATIC_AUDIO_DIR", "./data/static_audio"))
            if raw.is_absolute():
                return raw
            return (ROOT / raw).resolve()

    settings = _FallbackSettings()

try:
    from src.providers.realtime_tts import stream_realtime_tts_chunks
except Exception:  # pragma: no cover - depends on optional realtime SDK availability
    stream_realtime_tts_chunks = None


DEFAULT_PRICE_USD_PER_10K_CHARS = 0.114682
DEFAULT_AUDIO_SUFFIX = ".wav"

PHRASE_SEGMENTS: tuple[tuple[str, str], ...] = (
    ("idiom_game/start", "好呀，我们玩成语接龙。"),
    ("idiom_game/robot_first", "小机仔先来"),
    ("idiom_game/robot_reply", "小机仔接"),
    ("idiom_game/turn_prompt", "轮到你啦，要接"),
    ("idiom_game/need_prefix", "要接"),
    ("idiom_game/need_suffix", "开头的成语哦。你可以再来一次。"),
    ("idiom_game/repeated_prefix", "这个成语"),
    ("idiom_game/repeated_suffix", "刚刚用过啦，成语接龙不能重复哦。"),
    ("idiom_game/user_connected_prefix", "你接上了"),
    ("idiom_game/robot_no_reply_user_win", "小机仔暂时接不上啦，这局你赢。"),
    ("idiom_game/not_found", "这个我还没在成语词库里找到。你可以换一个四字成语再接。"),
    ("idiom_game/exit", "这局先到这里，小机仔把小本本合上啦。"),
)


class SegmentSpec(NamedTuple):
    segment_id: str
    text: str
    category: str


Synthesizer = Callable[[str, Path, dict], dict | None]


def build_segment_specs(
    idiom_path: str | Path,
    categories: tuple[str, ...] | list[str] | set[str] | None = None,
) -> list[SegmentSpec]:
    enabled = _normalize_categories(categories)
    idioms = _load_idiom_rows(Path(idiom_path))
    specs: list[SegmentSpec] = []

    if "phrase" in enabled:
        specs.extend(SegmentSpec(segment_id, text, "phrase") for segment_id, text in PHRASE_SEGMENTS)

    if "idiom" in enabled:
        specs.extend(SegmentSpec(f"idioms/{item['word']}", item["word"], "idiom") for item in idioms)

    if "pinyin" in enabled:
        pinyin_values = sorted({item["first_py"] for item in idioms} | {item["last_py"] for item in idioms})
        specs.extend(SegmentSpec(f"pinyin/{value}", value, "pinyin") for value in pinyin_values)

    return specs


def prebuild_static_audio(
    *,
    idiom_path: str | Path,
    output_root: str | Path,
    manifest_dir: str | Path,
    categories: tuple[str, ...] | list[str] | set[str] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
    run_id: str | None = None,
    backend: str = "http",
    price_usd_per_10k_chars: float | None = None,
    effective_price_usd_per_10k_chars: float | None = None,
    free_tier: bool = False,
    synthesizer: Synthesizer | None = None,
    audio_suffix: str = DEFAULT_AUDIO_SUFFIX,
    request_interval_seconds: float = 0.0,
    model: str | None = None,
    voice: str | None = None,
) -> dict:
    run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path(output_root).resolve()
    manifest_dir = Path(manifest_dir).resolve()
    manifest_dir.mkdir(parents=True, exist_ok=True)
    specs = build_segment_specs(idiom_path, categories)
    if limit is not None:
        specs = specs[: max(0, int(limit))]

    manifest_path = manifest_dir / f"idiom_tts_manifest_{run_id}.jsonl"
    summary_path = manifest_dir / f"idiom_tts_summary_{run_id}.json"
    backend = normalize_backend(backend)
    model = model or _default_model_for_backend(backend)
    voice = voice or _default_voice_for_backend(backend)
    synthesizer = synthesizer or _default_synthesizer_for_backend(backend)
    list_price = (
        float(price_usd_per_10k_chars)
        if price_usd_per_10k_chars is not None
        else default_formula_price_usd_per_10k_chars(model)
    )
    effective_price = (
        0.0
        if free_tier
        else (
            float(effective_price_usd_per_10k_chars)
            if effective_price_usd_per_10k_chars is not None
            else list_price
        )
    )

    summary = {
        "run_id": run_id,
        "dry_run": bool(dry_run),
        "output_root": str(output_root),
        "manifest_path": str(manifest_path),
        "summary_path": str(summary_path),
        "provider": "dashscope",
        "backend": backend,
        "model": model,
        "voice": voice,
        "pricing_mode": "free_tier" if free_tier else "formula_effective_price",
        "formula_list_price_usd_per_10k_chars": list_price,
        "formula_effective_price_usd_per_10k_chars": effective_price,
        "cost_data_source": "local_formula_estimate_not_cloud_bill",
        "planned_count": len(specs),
        "generated_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "total_chars": 0,
        "billable_chars": 0,
        "formula_estimated_list_price_total_value_usd": 0.0,
        "formula_estimated_effective_total_cost_usd": 0.0,
        "formula_estimated_list_price_billable_value_usd": 0.0,
        "formula_estimated_effective_billable_cost_usd": 0.0,
        "output_bytes": 0,
    }

    with manifest_path.open("w", encoding="utf-8", newline="\n") as manifest:
        for spec in specs:
            entry = _base_manifest_entry(
                spec,
                run_id=run_id,
                output_root=output_root,
                audio_suffix=audio_suffix,
                backend=backend,
                list_price_usd_per_10k_chars=list_price,
                effective_price_usd_per_10k_chars=effective_price,
                model=model,
                voice=voice,
            )
            summary["total_chars"] += entry["char_count"]
            summary["formula_estimated_list_price_total_value_usd"] = _round_cost(
                float(summary["formula_estimated_list_price_total_value_usd"])
                + entry["formula_estimated_list_price_value_usd"]
            )
            summary["formula_estimated_effective_total_cost_usd"] = _round_cost(
                float(summary["formula_estimated_effective_total_cost_usd"])
                + entry["formula_estimated_effective_cost_usd"]
            )

            if dry_run:
                entry["status"] = "planned"
                _write_jsonl(manifest, entry)
                continue

            output_path = Path(entry["output_path"])
            if output_path.exists() and not overwrite:
                _attach_existing_audio_info(entry, output_path)
                entry["status"] = "skipped"
                summary["skipped_count"] += 1
                summary["output_bytes"] += int(entry.get("output_bytes") or 0)
                _write_jsonl(manifest, entry)
                continue

            started = time.perf_counter()
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                provider_metadata = synthesizer(
                    spec.text,
                    output_path,
                    {
                        "segment_id": spec.segment_id,
                        "category": spec.category,
                        "backend": backend,
                        "model": model,
                        "voice": voice,
                    },
                ) or {}
                entry["elapsed_ms"] = _elapsed_ms(started)
                entry["status"] = "success"
                entry.update(provider_metadata)
                _attach_existing_audio_info(entry, output_path)
                summary["generated_count"] += 1
                summary["billable_chars"] += entry["char_count"]
                summary["formula_estimated_list_price_billable_value_usd"] = _round_cost(
                    float(summary["formula_estimated_list_price_billable_value_usd"])
                    + entry["formula_estimated_list_price_value_usd"]
                )
                summary["formula_estimated_effective_billable_cost_usd"] = _round_cost(
                    float(summary["formula_estimated_effective_billable_cost_usd"])
                    + entry["formula_estimated_effective_cost_usd"]
                )
                summary["output_bytes"] += int(entry.get("output_bytes") or 0)
                if request_interval_seconds > 0:
                    time.sleep(float(request_interval_seconds))
            except Exception as exc:
                entry["elapsed_ms"] = _elapsed_ms(started)
                entry["status"] = "failed"
                entry["error"] = str(exc) or exc.__class__.__name__
                summary["failed_count"] += 1
            _write_jsonl(manifest, entry)

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _copy_latest(manifest_path, manifest_dir / "idiom_tts_manifest.latest.jsonl")
    _copy_latest(summary_path, manifest_dir / "idiom_tts_summary.latest.json")
    return summary


def synthesize_dashscope_wav(text: str, output_path: Path, context: dict) -> dict:
    api_key = settings.dashscope_api_key
    model = str(context.get("model") or settings.dashscope_tts_model)
    voice = str(context.get("voice") or settings.tts_voice)
    if not api_key:
        raise RuntimeError("missing DASHSCOPE_API_KEY")
    if not voice:
        raise RuntimeError("missing TTS_VOICE")

    payload = {
        "model": model,
        "input": {
            "text": text,
            "voice": voice,
            "language_type": settings.tts_language_type,
        },
        "parameters": {
            "instructions": settings.tts_instructions,
            "output_format": "wav",
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    api_url = settings.dashscope_base_url.rstrip("/") + "/api/v1/services/aigc/multimodal-generation/generation"
    response = requests.post(api_url, headers=headers, json=payload, timeout=settings.tts_timeout_seconds)
    try:
        body = response.json()
    except Exception as exc:
        raise RuntimeError("dashscope_invalid_json") from exc
    if response.status_code != 200:
        raise RuntimeError(f"dashscope_http_{response.status_code}:{body}")

    output_audio = (body.get("output") or {}).get("audio", {})
    audio_url = output_audio.get("url")
    audio_base64 = output_audio.get("data")
    audio_bytes = _load_dashscope_audio_bytes(audio_url=audio_url, audio_base64=audio_base64)
    tmp_path = output_path.with_suffix(f".tmp{output_path.suffix}")
    tmp_path.write_bytes(audio_bytes)
    if tmp_path.stat().st_size <= 0:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError("empty_audio")
    tmp_path.replace(output_path)
    return {
        "backend": "http",
        "provider_request_id": body.get("request_id"),
        "dashscope_audio_url": audio_url,
    }


def synthesize_realtime_wav(text: str, output_path: Path, context: dict) -> dict:
    if stream_realtime_tts_chunks is None:
        raise RuntimeError("realtime_tts_unavailable")
    model = str(context.get("model") or getattr(settings, "realtime_tts_model", ""))
    voice = str(context.get("voice") or getattr(settings, "realtime_tts_voice", ""))
    if not model:
        raise RuntimeError("missing REALTIME_TTS_MODEL")
    if not voice:
        raise RuntimeError("missing REALTIME_TTS_VOICE")

    old_model = getattr(settings, "realtime_tts_model", None)
    old_voice = getattr(settings, "realtime_tts_voice", None)
    if hasattr(settings, "realtime_tts_model"):
        setattr(settings, "realtime_tts_model", model)
    if hasattr(settings, "realtime_tts_voice"):
        setattr(settings, "realtime_tts_voice", voice)

    sample_rate = int(getattr(settings, "realtime_audio_sample_rate", 16000))
    sample_width_bits = int(getattr(settings, "realtime_audio_sample_width_bits", 16))
    channels = int(getattr(settings, "realtime_audio_channels", 1))
    sample_width_bytes = max(1, sample_width_bits // 8)
    tmp_path = output_path.with_suffix(f".tmp{output_path.suffix}")
    audio_bytes = 0
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(tmp_path), "wb") as writer:
            writer.setnchannels(channels)
            writer.setsampwidth(sample_width_bytes)
            writer.setframerate(sample_rate)
            for chunk in stream_realtime_tts_chunks([text]):
                if chunk:
                    writer.writeframes(chunk)
                    audio_bytes += len(chunk)
        if audio_bytes <= 0 or tmp_path.stat().st_size <= 0:
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError("empty_realtime_audio")
        tmp_path.replace(output_path)
    finally:
        if old_model is not None and hasattr(settings, "realtime_tts_model"):
            setattr(settings, "realtime_tts_model", old_model)
        if old_voice is not None and hasattr(settings, "realtime_tts_voice"):
            setattr(settings, "realtime_tts_voice", old_voice)
    return {
        "backend": "realtime",
        "audio_format": "wav_from_pcm",
        "pcm_bytes": audio_bytes,
    }


def _load_idiom_rows(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, str]] = []
    for item in payload:
        word = str(item.get("word") or "").strip()
        first_py = str(item.get("first_py") or "").strip()
        last_py = str(item.get("last_py") or "").strip()
        if word and first_py and last_py:
            rows.append({"word": word, "first_py": first_py, "last_py": last_py})
    return rows


def _normalize_categories(categories: tuple[str, ...] | list[str] | set[str] | None) -> set[str]:
    if categories is None:
        return {"phrase", "idiom", "pinyin"}
    normalized = {str(item).strip() for item in categories if str(item).strip()}
    if "all" in normalized:
        return {"phrase", "idiom", "pinyin"}
    return normalized


def _base_manifest_entry(
    spec: SegmentSpec,
    *,
    run_id: str,
    output_root: Path,
    audio_suffix: str,
    backend: str,
    list_price_usd_per_10k_chars: float,
    effective_price_usd_per_10k_chars: float,
    model: str,
    voice: str,
) -> dict:
    output_path = _segment_output_path(output_root, spec.segment_id, audio_suffix)
    char_count = len(spec.text)
    return {
        "run_id": run_id,
        "segment_id": spec.segment_id,
        "category": spec.category,
        "text": spec.text,
        "char_count": char_count,
        "provider": "dashscope",
        "backend": backend,
        "model": model,
        "voice": voice,
        "formula_estimated_list_price_value_usd": estimate_cost_usd(char_count, list_price_usd_per_10k_chars),
        "formula_estimated_effective_cost_usd": estimate_cost_usd(char_count, effective_price_usd_per_10k_chars),
        "output_path": str(output_path),
        "output_bytes": 0,
        "duration_ms": None,
        "elapsed_ms": 0,
        "status": "pending",
        "error": None,
    }


def estimate_cost_usd(char_count: int, price_usd_per_10k_chars: float) -> float:
    return _round_cost((max(0, int(char_count)) / 10000.0) * float(price_usd_per_10k_chars))


def normalize_backend(value: str) -> str:
    backend = str(value or "http").strip().lower()
    if backend not in {"http", "realtime"}:
        raise ValueError(f"unsupported_tts_backend:{value}")
    return backend


def _default_model_for_backend(backend: str) -> str:
    if backend == "realtime":
        return str(getattr(settings, "realtime_tts_model", "") or "")
    return str(getattr(settings, "dashscope_tts_model", "") or "")


def _default_voice_for_backend(backend: str) -> str:
    if backend == "realtime":
        return str(getattr(settings, "realtime_tts_voice", "") or "")
    return str(getattr(settings, "tts_voice", "") or "")


def _default_synthesizer_for_backend(backend: str) -> Synthesizer:
    return synthesize_realtime_wav if backend == "realtime" else synthesize_dashscope_wav


def default_formula_price_usd_per_10k_chars(model: str) -> float:
    normalized = str(model or "").strip().lower()
    if "realtime" in normalized:
        return 0.143353
    if "instruct-flash" in normalized:
        return 0.115
    if "-vc" in normalized or normalized.endswith("vc"):
        return 0.115
    if "flash" in normalized:
        return 0.114682
    return DEFAULT_PRICE_USD_PER_10K_CHARS


def _segment_output_path(output_root: Path, segment_id: str, audio_suffix: str) -> Path:
    relative = Path(segment_id)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe segment id: {segment_id}")
    suffix = audio_suffix if audio_suffix.startswith(".") else f".{audio_suffix}"
    return (output_root / relative).with_suffix(suffix).resolve()


def _attach_existing_audio_info(entry: dict, output_path: Path) -> None:
    entry["output_bytes"] = output_path.stat().st_size if output_path.exists() else 0
    entry["duration_ms"] = audio_duration_ms(output_path)


def audio_duration_ms(path: Path) -> int | None:
    if not path.exists():
        return None
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as reader:
                frames = reader.getnframes()
                rate = reader.getframerate()
            return int(round((frames / max(1, rate)) * 1000))
        except Exception:
            return None
    return None


def _load_dashscope_audio_bytes(*, audio_url: str | None, audio_base64: str | None) -> bytes:
    if audio_url:
        parsed = urlparse(audio_url)
        suffix = Path(parsed.path).suffix.lower()
        if suffix and suffix != ".wav":
            raise RuntimeError(f"unsupported_audio_suffix:{suffix}")
        response = requests.get(audio_url, timeout=settings.tts_timeout_seconds)
        if response.status_code != 200 or not response.content:
            raise RuntimeError(f"audio_download_failed_{response.status_code}")
        return response.content
    if audio_base64:
        try:
            return base64.b64decode(audio_base64)
        except Exception as exc:
            raise RuntimeError("audio_base64_decode_failed") from exc
    raise RuntimeError("dashscope_missing_audio")


def _elapsed_ms(started: float) -> int:
    return int(round((time.perf_counter() - started) * 1000))


def _round_cost(value: float) -> float:
    return round(float(value), 6)


def _write_jsonl(handle, payload: dict) -> None:
    handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    handle.write("\n")


def _copy_latest(source: Path, target: Path) -> None:
    try:
        shutil.copyfile(source, target)
    except OSError:
        return


def _parse_categories(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Prebuild static audio segments for idiom game replies.")
    parser.add_argument("--idiom-path", default=str(ROOT / "src" / "voice_skills" / "idioms.json"))
    parser.add_argument("--output-root", default=str(settings.static_audio_path))
    parser.add_argument("--manifest-dir", default=str(settings.static_audio_path / "manifests"))
    parser.add_argument("--categories", default="phrase,idiom,pinyin")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--backend", default="http", choices=["http", "realtime"])
    parser.add_argument("--price-usd-per-10k-chars", type=float)
    parser.add_argument("--effective-price-usd-per-10k-chars", type=float)
    parser.add_argument("--free-tier", action="store_true")
    parser.add_argument("--request-interval-seconds", type=float, default=0.0)
    parser.add_argument("--model")
    parser.add_argument("--voice")
    args = parser.parse_args()

    summary = prebuild_static_audio(
        idiom_path=args.idiom_path,
        output_root=args.output_root,
        manifest_dir=args.manifest_dir,
        categories=_parse_categories(args.categories),
        limit=args.limit,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        run_id=args.run_id,
        backend=args.backend,
        price_usd_per_10k_chars=args.price_usd_per_10k_chars,
        effective_price_usd_per_10k_chars=args.effective_price_usd_per_10k_chars,
        free_tier=args.free_tier,
        request_interval_seconds=args.request_interval_seconds,
        model=args.model,
        voice=args.voice,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
