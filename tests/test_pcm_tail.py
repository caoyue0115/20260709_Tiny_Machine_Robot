from __future__ import annotations

import struct

import pytest

from src.providers.pcm_tail import (
    PcmTailError,
    analyze_pcm16_tail,
    ensure_safe_pcm16_tail,
)


def _pcm(samples: list[int]) -> bytes:
    return struct.pack(f"<{len(samples)}h", *samples)


def test_rejects_audible_endpoint_instead_of_hiding_it_with_zero_padding() -> None:
    audible_tail = _pcm([0] * 1600 + [1200] * 320)

    report = analyze_pcm16_tail(audible_tail)

    assert report.source_complete is False
    assert report.safe_tail is False
    with pytest.raises(PcmTailError, match="fixed_audio_source_tail_incomplete"):
        ensure_safe_pcm16_tail(audible_tail)


def test_pads_only_a_complete_source_to_five_hundred_ms() -> None:
    complete_short_tail = _pcm([800] * 1600 + [0] * 320)

    padded = ensure_safe_pcm16_tail(complete_short_tail)
    report = analyze_pcm16_tail(padded)

    assert padded.startswith(complete_short_tail)
    assert len(padded) == len(complete_short_tail) + (480 * 16 * 2)
    assert report.source_complete is True
    assert report.safe_tail is True
    assert report.quiet_tail_ms == 500


def test_keeps_an_already_safe_tail_byte_for_byte() -> None:
    already_safe = _pcm([-900] * 1600 + [0] * (500 * 16))

    assert ensure_safe_pcm16_tail(already_safe) == already_safe


@pytest.mark.parametrize("pcm", [b"", b"\x00"])
def test_rejects_empty_or_unaligned_pcm16(pcm: bytes) -> None:
    with pytest.raises(PcmTailError, match="invalid_pcm16_length"):
        analyze_pcm16_tail(pcm)


def test_final_sample_threshold_is_enforced_even_when_tail_rms_is_low() -> None:
    endpoint_jump = _pcm([0] * 319 + [-101])

    report = analyze_pcm16_tail(endpoint_jump)

    assert report.last_20ms_rms < 100
    assert report.last_sample_abs == 101
    assert report.source_complete is False
