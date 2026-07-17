from __future__ import annotations

import asyncio
import struct
import tempfile
import wave
from pathlib import Path
from unittest import mock

import pytest

from tests._stubs import install_dependency_stubs


install_dependency_stubs()


def _write_wav(
    path: Path,
    *,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
    pcm: bytes = struct.pack("<2h", 1, 2) + (b"\x00\x00" * (500 * 16)),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(sample_width)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)


def test_static_audio_validator_requires_16k_mono_pcm16_wav() -> None:
    from src.providers.static_audio import StaticAudioError, validate_static_audio_segment

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_wav(root / "valid.wav")
        _write_wav(root / "wrong_rate.wav", sample_rate=8000)
        _write_wav(root / "stereo.wav", channels=2, pcm=b"\x01\x00\x02\x00" * 2)
        _write_wav(root / "pcm8.wav", sample_width=1, pcm=b"\x01\x02")
        (root / "broken.wav").write_bytes(b"not a wave")

        assert validate_static_audio_segment("valid", root=root) == (root / "valid.wav").resolve()
        for segment_id in ("wrong_rate", "stereo", "pcm8", "broken", "missing"):
            with pytest.raises(StaticAudioError):
                validate_static_audio_segment(segment_id, root=root)


def test_raw_pcm_validator_rejects_empty_or_unaligned_data() -> None:
    from src.providers.static_audio import StaticAudioError, validate_static_audio_segment

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "valid.pcm").write_bytes(b"\x01\x00\x02\x00")
        (root / "empty.pcm").write_bytes(b"")
        (root / "odd.pcm").write_bytes(b"\x01")

        assert validate_static_audio_segment("valid", root=root) == (root / "valid.pcm").resolve()
        for segment_id in ("empty", "odd"):
            with pytest.raises(StaticAudioError):
                validate_static_audio_segment(segment_id, root=root)


def test_catalog_excludes_unplayable_idioms_and_ignores_pinyin_assets() -> None:
    from src.voice_skills.idiom_audio import build_idiom_audio_catalog
    from src.voice_skills.idiom_game import IdiomEntry

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_wav(root / "idiom_game" / "static_error.wav")
        _write_wav(root / "idioms" / "画龙点睛.wav")
        _write_wav(root / "idioms" / "海阔天空.wav", sample_rate=8000)
        _write_wav(root / "pinyin" / "jing.wav", sample_rate=8000)

        catalog = build_idiom_audio_catalog(
            [
                IdiomEntry("画龙点睛", "hua", "jing"),
                IdiomEntry("海阔天空", "hai", "kong"),
            ],
            root=root,
        )

        assert catalog.playable_words == frozenset({"画龙点睛"})
        assert "海阔天空" in catalog.invalid_idiom_words
        assert all(not segment.startswith("pinyin/") for segment in catalog.invalid_fixed_segments)


def test_catalog_requires_usable_static_error() -> None:
    from src.providers.static_audio import StaticAudioError
    from src.voice_skills.idiom_audio import build_idiom_audio_catalog
    from src.voice_skills.idiom_game import IdiomEntry

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with pytest.raises(StaticAudioError, match="static_error"):
            build_idiom_audio_catalog([IdiomEntry("画龙点睛", "hua", "jing")], root=root)


def test_catalog_requires_safe_static_error_tail() -> None:
    from src.providers.static_audio import StaticAudioError
    from src.voice_skills.idiom_audio import build_idiom_audio_catalog
    from src.voice_skills.idiom_game import IdiomEntry

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_wav(
            root / "idiom_game" / "static_error.wav",
            pcm=struct.pack("<320h", *([1200] * 320)),
        )

        with pytest.raises(StaticAudioError, match="static_audio_unsafe_tail:idiom_game/static_error"):
            build_idiom_audio_catalog([IdiomEntry("画龙点睛", "hua", "jing")], root=root)


def test_cloud_idle_prompts_are_required_tail_validated_fixed_segments() -> None:
    from src.voice_skills.idiom_audio import (
        REQUIRED_FIXED_SEGMENTS,
        TAIL_VALIDATED_FIXED_SEGMENTS,
    )

    for segment_id in ("idiom_game/presence", "idiom_game/idle_exit"):
        assert segment_id in REQUIRED_FIXED_SEGMENTS
        assert segment_id in TAIL_VALIDATED_FIXED_SEGMENTS


def test_catalog_marks_unsafe_runtime_fixed_tail_without_tail_scanning_idioms() -> None:
    from src.providers.static_audio import validate_fixed_audio_tail
    from src.voice_skills import idiom_audio as idiom_audio_module
    from src.voice_skills.idiom_game import IdiomEntry

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_wav(root / "idiom_game" / "static_error.wav")
        _write_wav(
            root / "idiom_game" / "mode_easy.wav",
            pcm=struct.pack("<320h", *([1200] * 320)),
        )
        _write_wav(root / "idioms" / "画龙点睛.wav", pcm=struct.pack("<2h", 1200, 1200))

        with mock.patch.object(
            idiom_audio_module,
            "validate_fixed_audio_tail",
            wraps=validate_fixed_audio_tail,
        ) as validate_tail:
            catalog = idiom_audio_module.build_idiom_audio_catalog(
                [IdiomEntry("画龙点睛", "hua", "jing")],
                root=root,
            )

        assert "idiom_game/mode_easy" in catalog.invalid_fixed_segments
        assert all(
            not str(call.args[0]).startswith("idioms/")
            for call in validate_tail.call_args_list
        )


def test_missing_fixed_segment_maps_to_static_error() -> None:
    from src.voice_skills.idiom_audio import build_idiom_audio_catalog
    from src.voice_skills.idiom_game import IdiomEntry

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_wav(root / "idiom_game" / "static_error.wav")
        _write_wav(root / "idioms" / "画龙点睛.wav")

        catalog = build_idiom_audio_catalog(
            [IdiomEntry("画龙点睛", "hua", "jing")],
            root=root,
        )

        assert "idiom_game/mode_easy" in catalog.invalid_fixed_segments
        assert catalog.resolve_plan(["idiom_game/mode_easy"]) == ["idiom_game/static_error"]


def test_skill_robot_pools_exclude_unplayable_idioms() -> None:
    from src.voice_skills.idiom_game import IdiomEntry, IdiomGameSkill, InMemoryIdiomGameStore

    skill = IdiomGameSkill(
        [
            IdiomEntry("画龙点睛", "hua", "jing"),
            IdiomEntry("精卫填海", "jing", "hai"),
            IdiomEntry("精忠报国", "jing", "guo"),
            IdiomEntry("海阔天空", "hai", "kong"),
        ],
        store=InMemoryIdiomGameStore(),
        opening_words=["精忠报国", "画龙点睛"],
        playable_words={"画龙点睛", "精卫填海"},
    )

    assert skill.start("esp-1") == "好呀，我们玩成语接龙。小机仔先来：画龙点睛。"
    assert skill.handle("esp-1", "精卫填海") == "你接上了“精卫填海”，小机仔暂时接不上啦，这局你赢。"


def test_fastapi_startup_initializes_idiom_audio_catalog() -> None:
    from src import app as app_module

    async def run_lifespan() -> None:
        async with app_module._app_lifespan(app_module.app):
            pass

    with mock.patch.object(app_module, "initialize_idiom_audio_catalog") as initialize:
        asyncio.run(run_lifespan())
    initialize.assert_called_once_with()


def test_router_maps_invalid_fixed_audio_to_static_error_catalog_entry() -> None:
    from src.voice_skills.idiom_audio import build_idiom_audio_catalog
    from src.voice_skills.idiom_game import IdiomEntry, IdiomGameSkill, InMemoryIdiomGameStore
    from src.voice_skills.router import SkillRouter

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_wav(root / "idiom_game" / "static_error.wav")
        _write_wav(root / "idiom_game" / "mode_easy.wav", sample_rate=8000)
        _write_wav(root / "idioms" / "画龙点睛.wav")
        catalog = build_idiom_audio_catalog(
            [IdiomEntry("画龙点睛", "hua", "jing")],
            root=root,
        )
        router = SkillRouter(
            idiom_skill=IdiomGameSkill(
                [IdiomEntry("画龙点睛", "hua", "jing")],
                store=InMemoryIdiomGameStore(),
                opening_words=["画龙点睛"],
            ),
            enabled_skills="idiom_game",
        )

        with mock.patch("src.voice_skills.router.get_idiom_audio_catalog", return_value=catalog):
            router.route(device_id="esp-1", text="开始成语接龙", trace={})
            result = router.route(device_id="esp-1", text="简单模式", trace={})

        assert result is not None
        assert result.audio_plan == ["idiom_game/static_error"]
