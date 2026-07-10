from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from tests._stubs import install_dependency_stubs

install_dependency_stubs()


def _write_wav(path: Path, pcm: bytes = b"\x01\x00\x02\x00") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(pcm)


class VoiceSkillRouterTests(unittest.TestCase):
    def test_router_returns_none_for_regular_coffee_question(self) -> None:
        from src.voice_skills.idiom_game import IdiomGameSkill, InMemoryIdiomGameStore, load_default_idioms
        from src.voice_skills.router import SkillRouter

        router = SkillRouter(
            idiom_skill=IdiomGameSkill(load_default_idioms(), store=InMemoryIdiomGameStore()),
            enabled_skills="idiom_game",
        )

        result = router.route(device_id="esp-1", text="手冲咖啡为什么偏酸", answer_mode="short", trace={})

        self.assertIsNone(result)

    def test_router_starts_idiom_game_and_builds_static_audio_plan(self) -> None:
        from src.voice_skills.idiom_game import IdiomGameSkill, InMemoryIdiomGameStore, load_default_idioms
        from src.voice_skills.router import SkillRouter

        router = SkillRouter(
            idiom_skill=IdiomGameSkill(load_default_idioms(), store=InMemoryIdiomGameStore()),
            enabled_skills="idiom_game",
        )

        result = router.route(device_id="esp-1", text="开始成语接龙", answer_mode="short", trace={})

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill_name, "idiom_game")
        self.assertIn("小机仔先来", result.answer_text or "")
        self.assertIsNotNone(result.audio_plan)
        self.assertGreaterEqual(len(result.audio_plan or []), 4)

    def test_router_exits_active_idiom_game_for_multinet_exit_phrases(self) -> None:
        from src.voice_skills.idiom_game import IdiomGameSkill, InMemoryIdiomGameStore, load_default_idioms
        from src.voice_skills.router import SkillRouter

        for phrase in ("退出游戏", "退出成语接龙", "结束成语接龙", "我不玩了", "推出游戏"):
            with self.subTest(phrase=phrase):
                store = InMemoryIdiomGameStore()
                router = SkillRouter(
                    idiom_skill=IdiomGameSkill(load_default_idioms(), store=store),
                    enabled_skills="idiom_game",
                )
                router.route(device_id="esp-1", text="开始成语接龙", answer_mode="short", trace={})

                result = router.route(device_id="esp-1", text=phrase, answer_mode="short", trace={})

                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(result.skill_name, "idiom_game")
                self.assertTrue(result.end_skill_state)
                self.assertIn("这局先到这里", result.answer_text or "")
                self.assertFalse(store.is_active("esp-1"))


class RealtimeSkillIntegrationTests(unittest.TestCase):
    def test_realtime_session_keeps_coffee_rag_when_no_skill_matches(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore

        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "answer.wav"
            _write_wav(wav_path)
            store = InMemoryRealtimeSessionStore(base_url="http://testserver")
            session = store.create_session(device_id="esp-1")
            question_text = "手冲咖啡为什么偏酸"
            store.update_session(session["session_id"], question_text=question_text)

            with mock.patch.object(
                realtime_session_service,
                "route_voice_skill",
                return_value=None,
            ), mock.patch.object(
                realtime_session_service,
                "retrieve_references",
                return_value=([{"source_title": "手冲", "snippet": "研磨偏粗会偏酸", "text": "研磨偏粗会偏酸"}], 0.9),
            ) as retrieve_references, mock.patch.object(
                realtime_session_service,
                "is_coffee_question",
                return_value=True,
            ), mock.patch.object(
                realtime_session_service,
                "stream_answer_text",
                return_value=iter(["可以磨细一点或提高水温。"]),
            ), mock.patch.object(
                realtime_session_service,
                "realtime_tts_health",
                return_value=False,
            ), mock.patch.object(
                realtime_session_service,
                "synthesize_audio",
                return_value=(str(wav_path), None),
            ):
                realtime_session_service.run_stub_realtime_session(store, session["session_id"])

        retrieve_references.assert_called_once_with(question_text, top_k=mock.ANY)
        updated = store.get_session(session["session_id"])
        self.assertEqual(updated["status"], "done")
        self.assertEqual(updated["trace"]["skill_name"], None)
        self.assertEqual(updated["trace"]["retrieval_top_score"], 0.9)

    def test_realtime_session_routes_idiom_game_before_coffee_rag_and_uses_static_audio(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.voice_skills.router import SkillResult

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio_plan = [
                "idiom_game/robot_reply",
                "idioms/国泰民安",
                "idiom_game/turn_prompt",
                "pinyin/an",
            ]
            for index, segment_id in enumerate(audio_plan, start=1):
                _write_wav(root / f"{segment_id}.wav", pcm=bytes([index, 0, index + 1, 0]))

            store = InMemoryRealtimeSessionStore(base_url="http://testserver")
            session = store.create_session(device_id="esp-1")
            store.update_session(session["session_id"], question_text="开始成语接龙")
            original_static_audio_dir = realtime_session_service.settings.static_audio_dir
            original_static_audio_enabled = realtime_session_service.settings.static_audio_enabled
            try:
                realtime_session_service.settings.static_audio_dir = str(root)
                realtime_session_service.settings.static_audio_enabled = True
                with mock.patch.object(
                    realtime_session_service,
                    "route_voice_skill",
                    return_value=SkillResult(
                        skill_name="idiom_game",
                        answer_text="小机仔接：国泰民安。轮到你啦，要接“an”。",
                        audio_plan=audio_plan,
                        trace={"skill_name": "idiom_game"},
                    ),
                ), mock.patch.object(
                    realtime_session_service,
                    "retrieve_references",
                    side_effect=AssertionError("coffee RAG should not run during idiom game"),
                ), mock.patch.object(
                    realtime_session_service,
                    "stream_realtime_tts_chunks",
                ) as stream_realtime_tts_chunks:
                    realtime_session_service.run_stub_realtime_session(store, session["session_id"])
            finally:
                realtime_session_service.settings.static_audio_dir = original_static_audio_dir
                realtime_session_service.settings.static_audio_enabled = original_static_audio_enabled

        updated = store.get_session(session["session_id"])
        self.assertEqual(updated["status"], "done")
        self.assertEqual(updated["trace"]["skill_name"], "idiom_game")
        self.assertEqual(updated["trace"]["static_audio_used"], True)
        self.assertEqual(updated["trace"]["static_audio_segment_count"], len(audio_plan))
        self.assertEqual(
            list(store.consume_audio_stream(session["session_id"], idle_timeout_ms=0)),
            [b"\x01\x00\x02\x00\x02\x00\x03\x00\x03\x00\x04\x00\x04\x00\x05\x00"],
        )
        stream_realtime_tts_chunks.assert_not_called()

    def test_static_audio_paths_are_merged_before_session_audio_queue(self) -> None:
        from src.providers.static_audio import merge_static_audio_paths

        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.wav"
            second = Path(tmp) / "second.wav"
            _write_wav(first, pcm=b"\x01\x00\x02\x00")
            _write_wav(second, pcm=b"\x03\x00\x04\x00")

            self.assertEqual(merge_static_audio_paths([first, second]), b"\x01\x00\x02\x00\x03\x00\x04\x00")

    def test_static_audio_chunk_size_default_is_large_enough_for_board_streaming(self) -> None:
        from src.settings import Settings

        settings = Settings(_env_file=None)

        self.assertEqual(settings.static_audio_chunk_size, 4096)


if __name__ == "__main__":
    unittest.main()
