from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import pytest

from tests._stubs import install_dependency_stubs


ROOT = Path(__file__).resolve().parents[1]
install_dependency_stubs()


def _load_script():
    script_path = ROOT / "scripts" / "prepare_idiom_fixed_audio.py"
    spec = importlib.util.spec_from_file_location("tests.prepare_idiom_fixed_audio", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _write_wav(path: Path, pcm: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(pcm)


def _complete_short_tail_pcm() -> bytes:
    return struct.pack("<160h", *([800] * 160)) + (b"\x00\x00" * (20 * 16))


def _generate_fake_batch(script, root: Path) -> tuple[Path, Path]:
    def fake_synthesizer(text: str, output_path: Path, context: dict) -> dict:
        _write_wav(output_path, _complete_short_tail_pcm())
        return {"provider_request_id": f"fake-{context['segment_id']}"}

    candidate_root = root / "output"
    manifest_path = root / "manifest.json"
    script.generate_candidate_batch(
        output_root=candidate_root,
        manifest_path=manifest_path,
        synthesizer=fake_synthesizer,
        model="qwen3-tts-base-1_7b",
        voice="clone_coffee_20s_v1",
        max_attempts=1,
        tempo_factor=0.9,
        tail_ms=500,
    )
    return candidate_root, manifest_path


def test_fixed_inventory_contains_only_fourteen_cloud_prompts() -> None:
    script = _load_script()
    from scripts.prebuild_idiom_static_audio import PHRASE_SEGMENTS

    runtime_phrases = dict(PHRASE_SEGMENTS)
    assert len(script.CLOUD_FIXED_TEXTS) == 14
    assert script.CLOUD_FIXED_TEXTS["idiom_game/start"] == "好呀，我们玩成语接龙。小机仔先来："
    assert script.SYNTHESIS_TEXT_OVERRIDES["idiom_game/start"].endswith("，")
    assert script.CLOUD_FIXED_TEXTS == {
        segment_id: runtime_phrases[segment_id]
        for segment_id in script.CLOUD_FIXED_TEXTS
    }
    assert not hasattr(script, "BOARD_PROMPTS")
    assert all("idioms/" not in item and "pinyin/" not in item for item in script.CLOUD_FIXED_TEXTS)


def test_generate_subset_records_approved_self_hosted_parameters() -> None:
    script = _load_script()
    calls: list[tuple[str, dict]] = []

    def fake_synthesizer(text: str, output_path: Path, context: dict) -> dict:
        calls.append((text, context.copy()))
        _write_wav(output_path, _complete_short_tail_pcm())
        return {"provider_request_id": f"fake-{context['segment_id']}"}

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manifest_path = root / "manifest.json"
        summary = script.generate_candidate_batch(
            output_root=root / "output",
            manifest_path=manifest_path,
            synthesizer=fake_synthesizer,
            model="qwen3-tts-base-1_7b",
            voice="clone_coffee_20s_v1",
            max_attempts=1,
            segment_ids={"idiom_game/start", "idiom_game/presence"},
            tempo_factor=0.9,
            tail_ms=500,
        )
        validated = script.validate_candidate_batch(
            candidate_root=root / "output",
            manifest_path=manifest_path,
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert summary["generated_count"] == 2
    assert validated == {"entry_count": 2, "failed_count": 0}
    assert manifest["provider"] == "self_hosted"
    assert manifest["model"] == "qwen3-tts-base-1_7b"
    assert manifest["voice"] == "clone_coffee_20s_v1"
    assert manifest["tempo_factor"] == 0.9
    assert manifest["tail_silence_ms"] == 500
    assert [item[0] for item in calls] == ["好呀，我们玩成语接龙。小机仔先来，", "你还在吗？"]
    assert all(item[1]["backend"] == "self_hosted" for item in calls)
    assert all(item[1]["tempo_factor"] == 0.9 for item in calls)
    assert all(item[1]["tail_ms"] == 500 for item in calls)
    assert all(entry["quiet_tail_ms"] >= 500 for entry in manifest["entries"])


@pytest.mark.parametrize("segment_id", ["idioms/画龙点睛", "pinyin/jing", "unknown/fixed"])
def test_generate_subset_rejects_forbidden_or_unknown_segment(segment_id: str) -> None:
    script = _load_script()

    with tempfile.TemporaryDirectory() as tmp, pytest.raises(
        script.FixedCandidateError,
        match="fixed_audio_(forbidden|unknown)_segment",
    ):
        script.generate_candidate_batch(
            output_root=Path(tmp) / "output",
            manifest_path=Path(tmp) / "manifest.json",
            synthesizer=lambda *_: None,
            model="qwen3-tts-base-1_7b",
            voice="clone_coffee_20s_v1",
            max_attempts=1,
            segment_ids={segment_id},
            tempo_factor=0.9,
            tail_ms=500,
        )


def test_cli_generate_defaults_to_approved_backend_tempo_and_tail() -> None:
    script = _load_script()

    args = script._build_parser().parse_args(
        ["generate", "--output-root", "output", "--manifest-path", "manifest.json"]
    )

    assert args.backend == "self_hosted"
    assert args.tempo_factor == 0.9
    assert args.tail_ms == 500


def test_validate_cli_does_not_require_tts_backend_dependencies() -> None:
    script = _load_script()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate_root, manifest_path = _generate_fake_batch(script, root)
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "prepare_idiom_fixed_audio.py"),
                "validate",
                "--candidate-root",
                str(candidate_root),
                "--manifest-path",
                str(manifest_path),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"entry_count": 14, "failed_count": 0}


def test_prepare_candidate_pcm_pads_complete_tail_to_five_hundred_ms() -> None:
    script = _load_script()

    prepared = script.prepare_candidate_pcm(_complete_short_tail_pcm())
    assert prepared.endswith(b"\x00\x00" * (500 * 16))
    assert script.analyze_pcm16_tail(prepared).quiet_tail_ms == 500


def test_generate_batch_writes_validated_outputs_and_sha256_manifest() -> None:
    script = _load_script()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate_root, manifest_path = _generate_fake_batch(script, root)
        validated = script.validate_candidate_batch(
            candidate_root=candidate_root,
            manifest_path=manifest_path,
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        assert validated["entry_count"] == 14
        for entry in manifest["entries"]:
            candidate = candidate_root / entry["relative_path"]
            assert hashlib.sha256(candidate.read_bytes()).hexdigest() == entry["sha256"]
            assert entry["quiet_tail_ms"] >= 500
            assert entry["kind"] == "cloud"


def test_incomplete_endpoint_never_overwrites_existing_candidate() -> None:
    script = _load_script()
    audible_pcm = struct.pack("<320h", *([1200] * 320))

    def clipped_synthesizer(text: str, output_path: Path, context: dict) -> None:
        _write_wav(output_path, audible_pcm)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        existing = root / "output" / "cloud" / "idiom_game" / "start.wav"
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_bytes(b"previous-good-candidate")

        with pytest.raises(script.FixedCandidateError, match="fixed_audio_batch_failed"):
            script.generate_candidate_batch(
                output_root=root / "output",
                manifest_path=root / "manifest.json",
                synthesizer=clipped_synthesizer,
                model="qwen3-tts-base-1_7b",
                voice="clone_coffee_20s_v1",
                max_attempts=1,
                tempo_factor=0.9,
                tail_ms=500,
            )

        assert existing.read_bytes() == b"previous-good-candidate"


def test_install_copies_only_manifested_cloud_fixed_assets() -> None:
    script = _load_script()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate_root, manifest_path = _generate_fake_batch(script, root)
        cloud_output = root / "cloud-output"

        script.install_cloud_candidates(
            candidate_root=candidate_root,
            static_audio_root=cloud_output,
            manifest_path=manifest_path,
        )

        assert {
            path.relative_to(cloud_output).with_suffix("").as_posix()
            for path in cloud_output.rglob("*.wav")
        } == set(script.CLOUD_FIXED_TEXTS)
        assert not (cloud_output / "idioms").exists()


def test_fixed_generator_source_has_no_dashscope_tts_route() -> None:
    source = (ROOT / "scripts" / "prepare_idiom_fixed_audio.py").read_text(encoding="utf-8")

    assert "src.providers.realtime_tts" not in source
    assert "synthesize_realtime_wav" not in source
    assert "dashscope" not in source.lower()
    assert "stream_self_hosted_realtime_tts_chunks" in source
