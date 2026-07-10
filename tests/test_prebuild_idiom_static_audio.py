from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

from tests._stubs import install_dependency_stubs

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

install_dependency_stubs()


def _load_script():
    script_path = ROOT / "scripts" / "prebuild_idiom_static_audio.py"
    spec = importlib.util.spec_from_file_location("tests.prebuild_idiom_static_audio", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _write_idiom_json(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {"word": "画龙点睛", "first_py": "hua", "last_py": "jing"},
                {"word": "精忠报国", "first_py": "jing", "last_py": "guo"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_tiny_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x01\x00" * 16)


class PrebuildIdiomStaticAudioTests(unittest.TestCase):
    def test_build_segment_specs_match_runtime_audio_plan_ids(self) -> None:
        script = _load_script()

        with tempfile.TemporaryDirectory() as tmpdir:
            idiom_path = Path(tmpdir) / "idioms.json"
            _write_idiom_json(idiom_path)

            specs = script.build_segment_specs(idiom_path)

        by_id = {spec.segment_id: spec for spec in specs}
        self.assertEqual(by_id["idiom_game/robot_reply"].text, "小机仔接")
        self.assertEqual(by_id["idioms/画龙点睛"].text, "画龙点睛")
        self.assertEqual(by_id["pinyin/jing"].text, "jing")
        self.assertEqual(by_id["pinyin/guo"].category, "pinyin")

    def test_phrase_segments_are_safe_for_tts_requests(self) -> None:
        script = _load_script()

        with tempfile.TemporaryDirectory() as tmpdir:
            idiom_path = Path(tmpdir) / "idioms.json"
            _write_idiom_json(idiom_path)
            specs = script.build_segment_specs(idiom_path, categories=("phrase",))

        for spec in specs:
            with self.subTest(segment_id=spec.segment_id):
                self.assertRegex(spec.text, r"[\w\u4e00-\u9fff]")
                self.assertNotRegex(spec.text, r"^[，。！？、：“”‘’\"']+$")
                self.assertNotRegex(spec.text, r"^[，。！？、：“”‘’\"']")
                self.assertNotRegex(spec.text, r"[：“”‘’\"']$")

    def test_dry_run_writes_manifest_and_summary_without_calling_tts(self) -> None:
        script = _load_script()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            idiom_path = root / "idioms.json"
            output_root = root / "static_audio"
            manifest_dir = root / "manifests"
            _write_idiom_json(idiom_path)

            def _unexpected_synthesizer(*args, **kwargs):
                raise AssertionError("dry-run must not call TTS")

            summary = script.prebuild_static_audio(
                idiom_path=idiom_path,
                output_root=output_root,
                manifest_dir=manifest_dir,
                categories=("idiom",),
                limit=1,
                dry_run=True,
                run_id="dryrun",
                price_usd_per_10k_chars=1.0,
                synthesizer=_unexpected_synthesizer,
            )

            manifest_path = manifest_dir / "idiom_tts_manifest_dryrun.jsonl"
            summary_path = manifest_dir / "idiom_tts_summary_dryrun.json"
            entries = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()]

            self.assertEqual(summary["dry_run"], True)
            self.assertEqual(summary["planned_count"], 1)
            self.assertEqual(summary["generated_count"], 0)
            self.assertEqual(summary["formula_estimated_list_price_total_value_usd"], 0.0004)
            self.assertEqual(summary["formula_estimated_effective_total_cost_usd"], 0.0004)
            self.assertNotIn("estimated_cost_usd", summary)
            self.assertEqual(entries[0]["status"], "planned")
            self.assertEqual(entries[0]["formula_estimated_list_price_value_usd"], 0.0004)
            self.assertEqual(entries[0]["formula_estimated_effective_cost_usd"], 0.0004)
            self.assertNotIn("estimated_cost_usd", entries[0])
            self.assertFalse((output_root / "idioms" / "画龙点睛.wav").exists())
            self.assertTrue(summary_path.exists())

    def test_prebuild_generates_wav_records_cost_and_skips_existing_file(self) -> None:
        script = _load_script()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            idiom_path = root / "idioms.json"
            output_root = root / "static_audio"
            manifest_dir = root / "manifests"
            _write_idiom_json(idiom_path)
            calls: list[str] = []

            def _fake_synthesizer(text: str, output_path: Path, context: dict) -> dict:
                calls.append(text)
                _write_tiny_wav(output_path)
                return {"provider_request_id": f"fake-{len(calls)}"}

            first_summary = script.prebuild_static_audio(
                idiom_path=idiom_path,
                output_root=output_root,
                manifest_dir=manifest_dir,
                categories=("idiom",),
                limit=1,
                dry_run=False,
                run_id="first",
                price_usd_per_10k_chars=1.0,
                synthesizer=_fake_synthesizer,
            )
            second_summary = script.prebuild_static_audio(
                idiom_path=idiom_path,
                output_root=output_root,
                manifest_dir=manifest_dir,
                categories=("idiom",),
                limit=1,
                dry_run=False,
                run_id="second",
                price_usd_per_10k_chars=1.0,
                synthesizer=_fake_synthesizer,
            )

            second_entries = [
                json.loads(line)
                for line in (manifest_dir / "idiom_tts_manifest_second.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]

            self.assertEqual(calls, ["画龙点睛"])
            self.assertEqual(first_summary["generated_count"], 1)
            self.assertEqual(first_summary["formula_estimated_effective_billable_cost_usd"], 0.0004)
            self.assertNotIn("billable_estimated_cost_usd", first_summary)
            self.assertEqual(second_summary["skipped_count"], 1)
            self.assertEqual(second_entries[0]["status"], "skipped")
            self.assertIn("formula_estimated_list_price_value_usd", second_entries[0])
            self.assertIn("formula_estimated_effective_cost_usd", second_entries[0])
            self.assertEqual(second_entries[0]["output_bytes"], (output_root / "idioms" / "画龙点睛.wav").stat().st_size)
            self.assertGreater(second_entries[0]["duration_ms"], 0)

    def test_prebuild_realtime_backend_uses_realtime_model_and_voice(self) -> None:
        script = _load_script()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            idiom_path = root / "idioms.json"
            _write_idiom_json(idiom_path)
            calls: list[tuple[str, str, str]] = []

            def _fake_synthesizer(text: str, output_path: Path, context: dict) -> dict:
                calls.append((text, context["model"], context["voice"]))
                _write_tiny_wav(output_path)
                return {"backend": context["backend"]}

            summary = script.prebuild_static_audio(
                idiom_path=idiom_path,
                output_root=root / "static_audio",
                manifest_dir=root / "manifests",
                categories=("idiom",),
                limit=1,
                dry_run=False,
                run_id="realtime",
                backend="realtime",
                model="qwen3-tts-flash-realtime-2025-11-27",
                voice="Mochi",
                synthesizer=_fake_synthesizer,
            )

            entry = json.loads((root / "manifests" / "idiom_tts_manifest_realtime.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(summary["backend"], "realtime")
            self.assertEqual(summary["model"], "qwen3-tts-flash-realtime-2025-11-27")
            self.assertEqual(summary["voice"], "Mochi")
            self.assertEqual(calls, [("画龙点睛", "qwen3-tts-flash-realtime-2025-11-27", "Mochi")])
            self.assertEqual(entry["backend"], "realtime")

    def test_synthesize_realtime_wav_wraps_pcm_stream_as_wav(self) -> None:
        script = _load_script()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "reply.wav"
            captured_chunks: list[list[str]] = []

            def _fake_stream_realtime_tts_chunks(text_chunks, **kwargs):
                captured_chunks.append(list(text_chunks))
                return iter([b"\x01\x00" * 4, b"\x02\x00" * 4])

            original_stream = getattr(script, "stream_realtime_tts_chunks", None)
            script.stream_realtime_tts_chunks = _fake_stream_realtime_tts_chunks
            try:
                metadata = script.synthesize_realtime_wav(
                    "小机仔接",
                    output_path,
                    {"model": "rt-model", "voice": "Mochi"},
                )
            finally:
                if original_stream is not None:
                    script.stream_realtime_tts_chunks = original_stream
                else:
                    delattr(script, "stream_realtime_tts_chunks")

            with wave.open(str(output_path), "rb") as reader:
                self.assertEqual(reader.getnchannels(), 1)
                self.assertEqual(reader.getsampwidth(), 2)
                self.assertEqual(reader.getframerate(), 16000)
                self.assertEqual(reader.getnframes(), 8)

            self.assertEqual(captured_chunks, [["小机仔接"]])
            self.assertEqual(metadata["backend"], "realtime")
            self.assertEqual(metadata["audio_format"], "wav_from_pcm")

    def test_free_tier_mode_records_zero_effective_cost_but_keeps_list_price_value(self) -> None:
        script = _load_script()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            idiom_path = root / "idioms.json"
            _write_idiom_json(idiom_path)

            summary = script.prebuild_static_audio(
                idiom_path=idiom_path,
                output_root=root / "static_audio",
                manifest_dir=root / "manifests",
                categories=("idiom",),
                limit=1,
                dry_run=True,
                run_id="free",
                price_usd_per_10k_chars=1.0,
                free_tier=True,
            )
            entry = json.loads((root / "manifests" / "idiom_tts_manifest_free.jsonl").read_text(encoding="utf-8"))

            self.assertEqual(summary["pricing_mode"], "free_tier")
            self.assertEqual(summary["formula_estimated_list_price_total_value_usd"], 0.0004)
            self.assertEqual(summary["formula_estimated_effective_total_cost_usd"], 0.0)
            self.assertEqual(entry["formula_estimated_list_price_value_usd"], 0.0004)
            self.assertEqual(entry["formula_estimated_effective_cost_usd"], 0.0)

    def test_cli_dry_run_can_run_without_full_backend_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            idiom_path = root / "idioms.json"
            _write_idiom_json(idiom_path)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "prebuild_idiom_static_audio.py"),
                    "--dry-run",
                    "--idiom-path",
                    str(idiom_path),
                    "--output-root",
                    str(root / "audio"),
                    "--manifest-dir",
                    str(root / "manifests"),
                    "--categories",
                    "idiom",
                    "--limit",
                    "1",
                    "--run-id",
                    "cli",
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            self.assertEqual(summary["dry_run"], True)
            self.assertEqual(summary["planned_count"], 1)

    def test_cli_fallback_settings_can_read_env_file_without_full_backend_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            idiom_path = root / "idioms.json"
            env_path = root / ".env"
            _write_idiom_json(idiom_path)
            env_path.write_text(
                "\n".join(
                    [
                        "DASHSCOPE_TTS_MODEL=qwen3-tts-flash-test",
                        "TTS_VOICE=voice-from-env-file",
                    ]
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "prebuild_idiom_static_audio.py"),
                    "--dry-run",
                    "--idiom-path",
                    str(idiom_path),
                    "--output-root",
                    str(root / "audio"),
                    "--manifest-dir",
                    str(root / "manifests"),
                    "--categories",
                    "idiom",
                    "--limit",
                    "1",
                    "--run-id",
                    "cli-env",
                ],
                cwd=str(ROOT),
                env={**os.environ, "IDIOM_STATIC_AUDIO_ENV_FILE": str(env_path)},
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            self.assertEqual(summary["model"], "qwen3-tts-flash-test")
            self.assertEqual(summary["voice"], "voice-from-env-file")

    def test_cli_realtime_backend_defaults_to_realtime_env_model_and_voice(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            idiom_path = root / "idioms.json"
            env_path = root / ".env"
            _write_idiom_json(idiom_path)
            env_path.write_text(
                "\n".join(
                    [
                        "DASHSCOPE_TTS_MODEL=http-model",
                        "TTS_VOICE=http-voice",
                        "REALTIME_TTS_MODEL=realtime-model",
                        "REALTIME_TTS_VOICE=realtime-voice",
                    ]
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "prebuild_idiom_static_audio.py"),
                    "--backend",
                    "realtime",
                    "--dry-run",
                    "--idiom-path",
                    str(idiom_path),
                    "--output-root",
                    str(root / "audio"),
                    "--manifest-dir",
                    str(root / "manifests"),
                    "--categories",
                    "idiom",
                    "--limit",
                    "1",
                    "--run-id",
                    "cli-realtime",
                ],
                cwd=str(ROOT),
                env={**os.environ, "IDIOM_STATIC_AUDIO_ENV_FILE": str(env_path)},
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            self.assertEqual(summary["backend"], "realtime")
            self.assertEqual(summary["model"], "realtime-model")
            self.assertEqual(summary["voice"], "realtime-voice")

    def test_default_formula_price_matches_selected_model_family(self) -> None:
        script = _load_script()

        self.assertEqual(script.default_formula_price_usd_per_10k_chars("qwen3-tts-vc-2026-01-22"), 0.115)
        self.assertEqual(script.default_formula_price_usd_per_10k_chars("qwen3-tts-flash-2025-11-27"), 0.114682)
        self.assertEqual(script.default_formula_price_usd_per_10k_chars("qwen3-tts-flash-realtime-2025-11-27"), 0.143353)


if __name__ == "__main__":
    unittest.main()
