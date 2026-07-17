from __future__ import annotations

from array import array
from collections.abc import Sequence
from dataclasses import dataclass
import math
import sys


PCM_SAMPLE_RATE = 16000
PCM_SAMPLE_WIDTH_BYTES = 2
QUIET_WINDOW_MS = 10
SOURCE_TAIL_MS = 20
PCM_POST_ROLL_MS = 500
SAFE_TAIL_MS = PCM_POST_ROLL_MS
QUIET_RMS_THRESHOLD = 100.0
LAST_SAMPLE_ABS_THRESHOLD = 100


class PcmTailError(ValueError):
    pass


def pcm16_silence(duration_ms: int) -> bytes:
    if duration_ms < 0:
        raise PcmTailError("invalid_silence_duration")
    sample_count = PCM_SAMPLE_RATE * duration_ms // 1000
    return b"\x00\x00" * sample_count


@dataclass(frozen=True)
class PcmTailReport:
    last_20ms_rms: float
    last_sample_abs: int
    quiet_tail_ms: int
    source_complete: bool
    safe_tail: bool


def _samples_from_pcm16le(pcm: bytes) -> array:
    if not pcm or len(pcm) % PCM_SAMPLE_WIDTH_BYTES:
        raise PcmTailError("invalid_pcm16_length")
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def _rms(samples: Sequence[int]) -> float:
    return math.sqrt(
        sum(int(value) * int(value) for value in samples) / len(samples)
    )


def analyze_pcm16_tail(pcm: bytes) -> PcmTailReport:
    samples = _samples_from_pcm16le(pcm)
    window_samples = PCM_SAMPLE_RATE * QUIET_WINDOW_MS // 1000
    source_samples = PCM_SAMPLE_RATE * SOURCE_TAIL_MS // 1000
    source_tail = samples[-min(len(samples), source_samples) :]
    source_rms = _rms(source_tail)

    quiet_windows = 0
    end = len(samples)
    while end >= window_samples:
        start = end - window_samples
        if _rms(samples[start:end]) > QUIET_RMS_THRESHOLD:
            break
        quiet_windows += 1
        end = start

    quiet_tail_ms = quiet_windows * QUIET_WINDOW_MS
    last_sample_abs = abs(int(samples[-1]))
    source_complete = (
        source_rms <= QUIET_RMS_THRESHOLD
        and last_sample_abs <= LAST_SAMPLE_ABS_THRESHOLD
    )
    return PcmTailReport(
        last_20ms_rms=source_rms,
        last_sample_abs=last_sample_abs,
        quiet_tail_ms=quiet_tail_ms,
        source_complete=source_complete,
        safe_tail=source_complete and quiet_tail_ms >= SAFE_TAIL_MS,
    )


def ensure_safe_pcm16_tail(pcm: bytes) -> bytes:
    report = analyze_pcm16_tail(pcm)
    if not report.source_complete:
        raise PcmTailError("fixed_audio_source_tail_incomplete")
    missing_ms = max(0, SAFE_TAIL_MS - report.quiet_tail_ms)
    return pcm + pcm16_silence(missing_ms)
