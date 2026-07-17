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
    def test_build_segment_specs_preserves_runtime_ids(self) -> None:
        script = _load_script()
        with tempfile.TemporaryDirectory() as tmpdir:
            idiom_path = Path(tmpdir) / "idioms.json"
            _write_idiom_json(idiom_path)
            specs = script.build_segment_specs(idiom_path)

        by_id = {spec.segment_id: spec for spec in specs}
        self.assertEqual(by_id["idiom_game/start"].text, "好呀，我们玩成语接龙。小机仔先来：")
        self.assertEqual(by_id["idiom_game/presence"].text, "你还在吗？")
        self.assertEqual(by_id["idiom_game/idle_exit"].text, "那我们下次再玩吧。")
        self.assertEqual(by_id["idioms/画龙点睛"].text, "画龙点睛")
        self.assertEqual(by_id["pinyin/jing"].text, "jing")

    def test_dry_run_is_self_hosted_and_has_no_external_tts_cost(self) -> None:
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
                run_id="dryrun",
            )
            entry = json.loads(
                (root / "manifests" / "idiom_tts_manifest_dryrun.jsonl").read_text(encoding="utf-8")
            )

        self.assertEqual(summary["provider"], "self_hosted")
        self.assertEqual(summary["backend"], "self_hosted")
        self.assertEqual(summary["model"], "qwen3-tts-base-1_7b")
        self.assertEqual(summary["voice"], "clone_coffee_20s_v1")
        self.assertEqual(summary["formula_effective_price_usd_per_10k_chars"], 0.0)
        self.assertEqual(entry["provider"], "self_hosted")
        self.assertEqual(entry["backend"], "self_hosted")

    def test_prebuild_generates_and_skips_existing_file_with_injected_synthesizer(self) -> None:
        script = _load_script()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            idiom_path = root / "idioms.json"
            _write_idiom_json(idiom_path)
            calls: list[str] = []

            def fake(text: str, output_path: Path, context: dict) -> dict:
                calls.append(text)
                self.assertEqual(context["backend"], "self_hosted")
                _write_tiny_wav(output_path)
                return {"provider_request_id": "local-test"}

            first = script.prebuild_static_audio(
                idiom_path=idiom_path,
                output_root=root / "audio",
                manifest_dir=root / "manifests",
                categories=("idiom",),
                limit=1,
                dry_run=False,
                run_id="first",
                synthesizer=fake,
            )
            second = script.prebuild_static_audio(
                idiom_path=idiom_path,
                output_root=root / "audio",
                manifest_dir=root / "manifests",
                categories=("idiom",),
                limit=1,
                dry_run=False,
                run_id="second",
                synthesizer=fake,
            )

        self.assertEqual(calls, ["画龙点睛"])
        self.assertEqual(first["generated_count"], 1)
        self.assertEqual(second["skipped_count"], 1)

    def test_only_self_hosted_backend_is_accepted(self) -> None:
        script = _load_script()

        self.assertEqual(script.normalize_backend("self_hosted"), "self_hosted")
        for legacy in ("http", "realtime", "dashscope"):
            with self.assertRaisesRegex(ValueError, "unsupported_tts_backend"):
                script.normalize_backend(legacy)

    def test_cli_defaults_to_self_hosted_env_model_and_voice(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            idiom_path = root / "idioms.json"
            env_path = root / ".env"
            _write_idiom_json(idiom_path)
            env_path.write_text(
                "SELF_HOSTED_TTS_MODEL=qwen3-tts-base-1_7b\n"
                "SELF_HOSTED_TTS_VOICE=clone_coffee_20s_v1\n",
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
                    "cli",
                ],
                cwd=str(ROOT),
                env={**os.environ, "IDIOM_STATIC_AUDIO_ENV_FILE": str(env_path)},
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        summary = json.loads(completed.stdout)
        self.assertEqual(summary["provider"], "self_hosted")
        self.assertEqual(summary["backend"], "self_hosted")
        self.assertEqual(summary["model"], "qwen3-tts-base-1_7b")
        self.assertEqual(summary["voice"], "clone_coffee_20s_v1")

    def test_source_has_no_dashscope_tts_or_legacy_realtime_provider(self) -> None:
        source = (ROOT / "scripts" / "prebuild_idiom_static_audio.py").read_text(encoding="utf-8")

        self.assertNotIn("src.providers.realtime_tts", source)
        self.assertNotIn("synthesize_dashscope_wav", source)
        self.assertNotIn("DASHSCOPE_TTS", source)
        self.assertNotIn("requests.post", source)
        self.assertIn("scripts.prepare_idiom_fixed_audio", source)


if __name__ == "__main__":
    unittest.main()
