from __future__ import annotations

import wave
from collections.abc import Iterable, Iterator
from pathlib import Path

from src.settings import settings


STATIC_AUDIO_SUFFIXES = (".pcm", ".wav")


class StaticAudioError(ValueError):
    pass


def resolve_static_audio_plan(segment_ids: Iterable[str], root: Path | None = None) -> list[Path] | None:
    if not settings.static_audio_enabled:
        return None
    base = (root or settings.static_audio_path).resolve()
    paths: list[Path] = []
    for segment_id in segment_ids:
        segment_path = _resolve_segment_path(str(segment_id or "").strip(), base)
        if segment_path is None:
            return None
        paths.append(segment_path)
    return paths or None


def stream_static_audio_paths(paths: Iterable[Path], chunk_size: int | None = None) -> Iterator[bytes]:
    size = max(1, int(chunk_size or settings.static_audio_chunk_size))
    for path in paths:
        yield from _iter_audio_file(path, chunk_size=size)


def _resolve_segment_path(segment_id: str, base: Path) -> Path | None:
    if not segment_id:
        return None
    raw = Path(segment_id)
    if raw.is_absolute() or ".." in raw.parts:
        return None
    stem_path = (base / raw).resolve()
    if not stem_path.is_relative_to(base):
        return None
    candidates = [stem_path] if stem_path.suffix.lower() in STATIC_AUDIO_SUFFIXES else [
        stem_path.with_suffix(suffix) for suffix in STATIC_AUDIO_SUFFIXES
    ]
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate.is_file() and candidate.is_relative_to(base):
            return candidate
    return None


def _iter_audio_file(path: Path, *, chunk_size: int) -> Iterator[bytes]:
    suffix = path.suffix.lower()
    if suffix == ".pcm":
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        return
    if suffix == ".wav":
        with wave.open(str(path), "rb") as reader:
            while True:
                frames = reader.readframes(max(1, chunk_size // max(1, reader.getsampwidth() * reader.getnchannels())))
                if not frames:
                    break
                yield frames
        return
    raise StaticAudioError(f"static_audio_unsupported_format:{suffix}")

