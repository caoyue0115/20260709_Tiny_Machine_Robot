from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Callable, NamedTuple

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
        self_hosted_tts_model = _env_value("SELF_HOSTED_TTS_MODEL", "qwen3-tts-base-1_7b")
        self_hosted_tts_voice = _env_value("SELF_HOSTED_TTS_VOICE", "clone_coffee_20s_v1")
        self_hosted_tts_fixed_tempo = float(_env_value("SELF_HOSTED_TTS_FIXED_TEMPO", "0.9"))
        self_hosted_tts_post_roll_ms = int(_env_value("SELF_HOSTED_TTS_POST_ROLL_MS", "500"))

        @property
        def static_audio_path(self) -> Path:
            raw = Path(_env_value("STATIC_AUDIO_DIR", "./data/static_audio"))
            if raw.is_absolute():
                return raw
            return (ROOT / raw).resolve()

    settings = _FallbackSettings()

DEFAULT_PRICE_USD_PER_10K_CHARS = 0.0
DEFAULT_AUDIO_SUFFIX = ".wav"

PHRASE_SEGMENTS: tuple[tuple[str, str], ...] = (
    ("idiom_game/start", "好呀，我们玩成语接龙。小机仔先来："),
    ("idiom_game/presence", "你还在吗？"),
    ("idiom_game/idle_exit", "那我们下次再玩吧。"),
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
    ("idiom_game/mode_easy", "已切换到简单模式，连续接对轮数已重新计算。"),
    ("idiom_game/mode_normal", "已切换到普通模式，连续接对轮数已重新计算。"),
    ("idiom_game/mode_hard", "已切换到困难模式，连续接对轮数已重新计算。"),
    ("idiom_game/mode_full", "已切换到大师模式，连续接对轮数已重新计算。"),
    ("idiom_game/challenge_win", "挑战成功，这局你赢。"),
    ("idiom_game/continue_prompt", "我们继续成语接龙吧，请说一个能接上的四字成语。"),
    ("idiom_game/retry", "我没听清，请再说一次。"),
    ("idiom_game/static_error", "成语语音暂时不可用，请稍后再试。"),
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
    backend: str = "self_hosted",
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
        "provider": "self_hosted",
        "backend": backend,
        "model": model,
        "voice": voice,
        "pricing_mode": "free_tier" if free_tier else "formula_effective_price",
        "formula_list_price_usd_per_10k_chars": list_price,
        "formula_effective_price_usd_per_10k_chars": effective_price,
        "cost_data_source": "self_hosted_no_external_tts_bill",
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


def synthesize_self_hosted_wav(text: str, output_path: Path, context: dict) -> dict:
    from scripts.prepare_idiom_fixed_audio import synthesize_self_hosted_wav as render

    render_context = dict(context)
    render_context.setdefault("tempo_factor", float(settings.self_hosted_tts_fixed_tempo))
    render_context.setdefault("tail_ms", int(settings.self_hosted_tts_post_roll_ms))
    return render(text, output_path, render_context)


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
        "provider": "self_hosted",
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
    backend = str(value or "self_hosted").strip().lower()
    if backend != "self_hosted":
        raise ValueError(f"unsupported_tts_backend:{value}")
    return backend


def _default_model_for_backend(backend: str) -> str:
    return str(getattr(settings, "self_hosted_tts_model", "") or "")


def _default_voice_for_backend(backend: str) -> str:
    return str(getattr(settings, "self_hosted_tts_voice", "") or "")


def _default_synthesizer_for_backend(backend: str) -> Synthesizer:
    return synthesize_self_hosted_wav


def default_formula_price_usd_per_10k_chars(model: str) -> float:
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
    parser.add_argument("--backend", default="self_hosted", choices=["self_hosted"])
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
