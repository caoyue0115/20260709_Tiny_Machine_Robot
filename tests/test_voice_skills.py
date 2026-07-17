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
    @staticmethod
    def _build_small_router(*, judge_unknown_idiom=None):
        from src.voice_skills.idiom_game import IdiomEntry, IdiomGameSkill, InMemoryIdiomGameStore
        from src.voice_skills.router import SkillRouter

        store = InMemoryIdiomGameStore()
        skill = IdiomGameSkill(
            [
                IdiomEntry(word="画龙点睛", first_py="hua", last_py="jing"),
                IdiomEntry(word="精卫填海", first_py="jing", last_py="hai"),
                IdiomEntry(word="海阔天空", first_py="hai", last_py="kong"),
                IdiomEntry(word="国泰民安", first_py="guo", last_py="an"),
            ],
            store=store,
            opening_words=["画龙点睛"],
            judge_unknown_idiom=judge_unknown_idiom,
        )
        return SkillRouter(idiom_skill=skill, enabled_skills="idiom_game"), store

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
        self.assertEqual(
            result.audio_plan,
            ["idiom_game/start", f"idioms/{result.trace['idiom_robot_reply_word']}"],
        )
        self.assertEqual(result.turn_outcome, "meaningful")

    def test_start_reply_and_audio_plan_stop_after_opening_idiom(self) -> None:
        router, store = self._build_small_router()

        result = router.route(device_id="esp-1", text="开始成语接龙", answer_mode="short", trace={})

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.answer_text, "好呀，我们玩成语接龙。小机仔先来：画龙点睛。")
        self.assertEqual(
            result.audio_plan,
            ["idiom_game/start", "idioms/画龙点睛"],
        )
        state = store.get("esp-1")
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.last_robot_word, "画龙点睛")

    def test_legacy_normal_reply_text_also_builds_idiom_only_plan(self) -> None:
        from src.voice_skills.idiom_game import build_idiom_audio_plan

        self.assertEqual(
            build_idiom_audio_plan("小机仔接：海阔天空。轮到你啦，要接“kong”。"),
            ["idioms/海阔天空"],
        )

    def test_start_with_difficulty_keeps_the_same_fixed_opening(self) -> None:
        router, store = self._build_small_router()

        result = router.route(
            device_id="esp-1",
            text="简单模式开始成语接龙",
            answer_mode="short",
            trace={},
        )

        assert result is not None
        self.assertEqual(result.answer_text, "好呀，我们玩成语接龙。小机仔先来：画龙点睛。")
        self.assertEqual(
            result.audio_plan,
            ["idiom_game/start", "idioms/画龙点睛"],
        )
        state = store.get("esp-1")
        assert state is not None
        self.assertEqual(state.robot_difficulty, "easy")

    def test_all_existing_difficulty_switches_use_static_mode_audio(self) -> None:
        cases = {
            "简单模式": "idiom_game/mode_easy",
            "普通模式": "idiom_game/mode_normal",
            "困难模式": "idiom_game/mode_hard",
            "大师模式": "idiom_game/mode_full",
        }
        for phrase, segment in cases.items():
            with self.subTest(phrase=phrase):
                router, _store = self._build_small_router()
                router.route(device_id="esp-1", text="开始成语接龙", answer_mode="short", trace={})

                result = router.route(device_id="esp-1", text=phrase, answer_mode="short", trace={})

                assert result is not None
                self.assertEqual(result.audio_plan, [segment])
                self.assertEqual(result.turn_outcome, "meaningful")

    def test_target_turn_win_uses_its_own_static_audio(self) -> None:
        from src.voice_skills.idiom_game import IdiomEntry, IdiomGameSkill, InMemoryIdiomGameStore
        from src.voice_skills.router import SkillRouter

        router = SkillRouter(
            idiom_skill=IdiomGameSkill(
                [
                    IdiomEntry("画龙点睛", "hua", "jing"),
                    IdiomEntry("精卫填海", "jing", "hai"),
                ],
                store=InMemoryIdiomGameStore(),
                opening_words=["画龙点睛"],
                target_user_turns=1,
            ),
            enabled_skills="idiom_game",
        )
        router.route(device_id="esp-1", text="开始成语接龙", answer_mode="short", trace={})

        result = router.route(device_id="esp-1", text="精卫填海", answer_mode="short", trace={})

        assert result is not None
        self.assertTrue(result.end_skill_state)
        self.assertEqual(result.audio_plan, ["idiom_game/challenge_win"])

    def test_successful_turn_replies_with_only_the_next_idiom(self) -> None:
        router, store = self._build_small_router()
        router.route(device_id="esp-1", text="开始成语接龙", answer_mode="short", trace={})

        result = router.route(device_id="esp-1", text="精卫填海", answer_mode="short", trace={})

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.answer_text, "海阔天空")
        self.assertEqual(result.audio_plan, ["idioms/海阔天空"])
        self.assertEqual(result.turn_outcome, "meaningful")
        state = store.get("esp-1")
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.last_robot_word, "海阔天空")

    def test_no_robot_candidate_uses_only_static_concession_prompt(self) -> None:
        from src.voice_skills.idiom_game import IdiomEntry, IdiomGameSkill, InMemoryIdiomGameStore
        from src.voice_skills.router import SkillRouter

        router = SkillRouter(
            idiom_skill=IdiomGameSkill(
                [
                    IdiomEntry("画龙点睛", "hua", "jing"),
                    IdiomEntry("精卫填海", "jing", "hai"),
                ],
                store=InMemoryIdiomGameStore(),
                opening_words=["画龙点睛"],
            ),
            enabled_skills="idiom_game",
        )
        router.route(device_id="esp-1", text="开始成语接龙", answer_mode="short", trace={})

        result = router.route(device_id="esp-1", text="精卫填海", answer_mode="short", trace={})

        assert result is not None
        self.assertIn("小机仔暂时接不上啦", result.answer_text or "")
        self.assertEqual(result.audio_plan, ["idiom_game/robot_no_reply_user_win"])

    def test_repeated_idiom_explanation_does_not_require_idiom_audio(self) -> None:
        router, _store = self._build_small_router()
        router.route(device_id="esp-1", text="开始成语接龙", answer_mode="short", trace={})

        result = router.route(device_id="esp-1", text="画龙点睛", answer_mode="short", trace={})

        assert result is not None
        self.assertIn("刚刚用过啦", result.answer_text or "")
        self.assertEqual(result.turn_outcome, "invalid")
        self.assertEqual(
            result.audio_plan,
            ["idiom_game/repeated_prefix", "idiom_game/repeated_suffix"],
        )

    def test_repeat_phrases_return_last_robot_word_without_advancing_state(self) -> None:
        for phrase in ("没听清", "没听到", "再说一次", "重复一下", "刚才是什么"):
            with self.subTest(phrase=phrase):
                router, store = self._build_small_router()
                router.route(device_id="esp-1", text="开始成语接龙", answer_mode="short", trace={})
                before = store.get("esp-1")
                assert before is not None
                before_snapshot = (
                    before.expected_py,
                    set(before.used_words),
                    before.valid_user_turns,
                    before.robot_difficulty,
                )

                result = router.route(device_id="esp-1", text=phrase, answer_mode="short", trace={})

                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(result.answer_text, "画龙点睛")
                self.assertEqual(result.audio_plan, ["idioms/画龙点睛"])
                self.assertEqual(result.turn_outcome, "meaningful")
                after = store.get("esp-1")
                assert after is not None
                self.assertEqual(
                    (after.expected_py, after.used_words, after.valid_user_turns, after.robot_difficulty),
                    before_snapshot,
                )

    def test_broad_exit_phrases_clear_state_before_idiom_lookup(self) -> None:
        for phrase in ("退出", "不玩了", "结束游戏", "结束接龙", "先这样", "停止"):
            with self.subTest(phrase=phrase):
                router, store = self._build_small_router()
                router.route(device_id="esp-1", text="开始成语接龙", answer_mode="short", trace={})

                result = router.route(device_id="esp-1", text=phrase, answer_mode="short", trace={})

                self.assertIsNotNone(result)
                assert result is not None
                self.assertTrue(result.end_skill_state)
                self.assertEqual(result.turn_outcome, "exit")
                self.assertEqual(result.audio_plan, ["idiom_game/exit"])
                self.assertNotIn("成语词库", result.answer_text or "")
                self.assertFalse(store.is_active("esp-1"))

    def test_llm_exit_clears_state_without_dictionary_error(self) -> None:
        from src.voice_skills.idiom_game import IdiomJudgeDecision

        router, store = self._build_small_router(
            judge_unknown_idiom=lambda _text, _expected: IdiomJudgeDecision(
                intent="exit",
                word="",
                first_py="",
                last_py="",
                confidence=0.95,
                is_idiom=False,
                matches_expected_pinyin=False,
            )
        )
        router.route(device_id="esp-1", text="开始成语接龙", answer_mode="short", trace={})

        result = router.route(device_id="esp-1", text="今天先到这儿吧", answer_mode="short", trace={})

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.end_skill_state)
        self.assertEqual(result.turn_outcome, "exit")
        self.assertEqual(result.audio_plan, ["idiom_game/exit"])
        self.assertNotIn("成语词库", result.answer_text or "")
        self.assertFalse(store.is_active("esp-1"))

    def test_llm_repeat_returns_last_robot_word_without_advancing(self) -> None:
        from src.voice_skills.idiom_game import IdiomJudgeDecision

        router, store = self._build_small_router(
            judge_unknown_idiom=lambda _text, _expected: IdiomJudgeDecision(
                intent="repeat",
                word="",
                first_py="",
                last_py="",
                confidence=0.95,
                is_idiom=False,
                matches_expected_pinyin=False,
            )
        )
        router.route(device_id="esp-1", text="开始成语接龙", answer_mode="short", trace={})
        before = store.get("esp-1")
        assert before is not None
        before_snapshot = (before.expected_py, set(before.used_words), before.valid_user_turns)

        result = router.route(device_id="esp-1", text="你刚刚讲的什么呀", answer_mode="short", trace={})

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.answer_text, "画龙点睛")
        self.assertEqual(result.audio_plan, ["idioms/画龙点睛"])
        self.assertEqual(result.turn_outcome, "meaningful")
        self.assertEqual(result.trace["idiom_llm_intent"], "repeat")
        self.assertEqual(result.trace["idiom_llm_judge_confidence"], 0.95)
        self.assertFalse(result.trace["idiom_llm_matches_expected_pinyin"])
        after = store.get("esp-1")
        assert after is not None
        self.assertEqual((after.expected_py, after.used_words, after.valid_user_turns), before_snapshot)

    def test_llm_idiom_requires_server_side_normalized_pinyin_validation(self) -> None:
        from src.voice_skills.idiom_game import IdiomJudgeDecision

        decisions = iter(
            [
                IdiomJudgeDecision(
                    intent="idiom",
                    word="精忠报国",
                    first_py="hǎi",
                    last_py="guó",
                    confidence=0.95,
                    is_idiom=True,
                    matches_expected_pinyin=True,
                ),
                IdiomJudgeDecision(
                    intent="idiom",
                    word="精忠报国",
                    first_py="jīng",
                    last_py="guó",
                    confidence=0.95,
                    is_idiom=True,
                    matches_expected_pinyin=False,
                ),
            ]
        )
        router, store = self._build_small_router(
            judge_unknown_idiom=lambda _text, _expected: next(decisions)
        )
        router.route(device_id="esp-1", text="开始成语接龙", answer_mode="short", trace={})

        rejected = router.route(device_id="esp-1", text="第一种未知表达", answer_mode="short", trace={})
        accepted = router.route(device_id="esp-1", text="第二种未知表达", answer_mode="short", trace={})

        assert rejected is not None
        self.assertIn("换一个四字成语", rejected.answer_text or "")
        assert accepted is not None
        self.assertEqual(accepted.answer_text, "国泰民安")
        state = store.get("esp-1")
        assert state is not None
        self.assertEqual(state.last_robot_word, "国泰民安")

    def test_noise_only_game_input_does_not_call_llm(self) -> None:
        calls: list[tuple[str, str]] = []

        def judge(text: str, expected_py: str):
            calls.append((text, expected_py))
            return None

        for phrase in ("嗯", "啊啊", "呃", "……"):
            with self.subTest(phrase=phrase):
                router, _store = self._build_small_router(judge_unknown_idiom=judge)
                router.route(device_id="esp-1", text="开始成语接龙", answer_mode="short", trace={})

                result = router.route(device_id="esp-1", text=phrase, answer_mode="short", trace={})

                assert result is not None
                self.assertEqual(result.audio_plan, ["idiom_game/not_found"])
                self.assertEqual(result.turn_outcome, "invalid")
        self.assertEqual(calls, [])

    def test_llm_off_topic_exports_off_topic_turn_outcome(self) -> None:
        from src.voice_skills.idiom_game import IdiomJudgeDecision

        router, _store = self._build_small_router(
            judge_unknown_idiom=lambda _text, _expected: IdiomJudgeDecision(
                intent="off_topic",
                word="",
                first_py="",
                last_py="",
                confidence=0.95,
                is_idiom=False,
                matches_expected_pinyin=False,
            )
        )
        router.route(device_id="esp-1", text="开始成语接龙", answer_mode="short", trace={})

        result = router.route(device_id="esp-1", text="今天天气怎么样", answer_mode="short", trace={})

        assert result is not None
        self.assertEqual(result.turn_outcome, "off_topic")

    def test_llm_failure_uses_static_retry_without_advancing_state(self) -> None:
        router, store = self._build_small_router(
            judge_unknown_idiom=lambda _text, _expected: None
        )
        router.route(device_id="esp-1", text="开始成语接龙", answer_mode="short", trace={})
        before = store.get("esp-1")
        assert before is not None
        snapshot = (before.expected_py, set(before.used_words), before.valid_user_turns)

        result = router.route(device_id="esp-1", text="今天先到这里吧", answer_mode="short", trace={})

        assert result is not None
        self.assertEqual(result.answer_text, "我没听清，请再说一次。")
        self.assertEqual(result.audio_plan, ["idiom_game/retry"])
        after = store.get("esp-1")
        assert after is not None
        self.assertEqual((after.expected_py, after.used_words, after.valid_user_turns), snapshot)

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

    def test_idle_exit_clears_only_current_device_and_is_idempotent(self) -> None:
        router, store = self._build_small_router()
        router.route(device_id="esp-a", text="开始成语接龙", answer_mode="short", trace={})
        router.route(device_id="esp-b", text="开始成语接龙", answer_mode="short", trace={})

        self.assertTrue(router.end_idiom_game("esp-a"))
        self.assertFalse(store.is_active("esp-a"))
        self.assertTrue(store.is_active("esp-b"))

        self.assertFalse(router.end_idiom_game("esp-a"))
        self.assertTrue(store.is_active("esp-b"))


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
            audio_plan = ["idioms/国泰民安"]
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
                        answer_text="国泰民安",
                        audio_plan=audio_plan,
                        turn_outcome="meaningful",
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
        self.assertEqual(updated["trace"]["turn_outcome"], "meaningful")
        self.assertEqual(updated["trace"]["static_audio_used"], True)
        self.assertEqual(updated["trace"]["static_audio_segment_count"], len(audio_plan))
        self.assertEqual(
            b"".join(store.consume_audio_stream(session["session_id"], idle_timeout_ms=0)),
            b"\x01\x00\x02\x00" + (b"\x00\x00" * (500 * 16)),
        )
        stream_realtime_tts_chunks.assert_not_called()

    def test_idiom_missing_plan_uses_static_error_without_dynamic_tts(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.voice_skills.router import SkillResult

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            static_error_pcm = b"\x05\x00\x06\x00" + (b"\x00\x00" * (500 * 16))
            _write_wav(root / "idiom_game" / "static_error.wav", pcm=static_error_pcm)
            store = InMemoryRealtimeSessionStore(base_url="http://testserver")
            session = store.create_session(device_id="esp-1")
            store.update_session(session["session_id"], question_text="不存在的成语素材")
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
                        answer_text="海阔天空",
                        audio_plan=["idioms/海阔天空"],
                        trace={"skill_name": "idiom_game"},
                    ),
                ), mock.patch.object(
                    realtime_session_service,
                    "_stream_answer_audio",
                    side_effect=AssertionError("idiom mode must not call dynamic TTS"),
                ):
                    realtime_session_service.run_stub_realtime_session(store, session["session_id"])
            finally:
                realtime_session_service.settings.static_audio_dir = original_static_audio_dir
                realtime_session_service.settings.static_audio_enabled = original_static_audio_enabled

        updated = store.get_session(session["session_id"])
        self.assertEqual(updated["status"], "done")
        self.assertEqual(updated["trace"]["static_audio_used"], True)
        self.assertEqual(
            b"".join(store.consume_audio_stream(session["session_id"], idle_timeout_ms=0)),
            static_error_pcm,
        )

    def test_static_audio_paths_are_merged_before_session_audio_queue(self) -> None:
        from src.providers.static_audio import merge_static_audio_paths

        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.wav"
            second = Path(tmp) / "second.wav"
            _write_wav(first, pcm=b"\x01\x00\x02\x00")
            _write_wav(second, pcm=b"\x03\x00\x04\x00")

            self.assertEqual(merge_static_audio_paths([first, second]), b"\x01\x00\x02\x00\x03\x00\x04\x00")

    def test_idiom_static_audio_merge_keeps_fixed_tail_and_appends_one_idiom_post_roll(self) -> None:
        from src.providers import static_audio as static_audio_module
        from src.providers.pcm_tail import analyze_pcm16_tail

        fixed_pcm = b"\x01\x00\x02\x00" + (b"\x00\x00" * (500 * 16))
        idiom_pcm = b"\x21\x43\x65\x07"
        idiom_post_roll = b"\x00\x00" * (500 * 16)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixed = root / "idiom_game" / "start.wav"
            idiom = root / "idioms" / "画龙点睛.wav"
            _write_wav(fixed, pcm=fixed_pcm)
            _write_wav(idiom, pcm=idiom_pcm)

            with mock.patch.object(
                static_audio_module,
                "analyze_pcm16_tail",
                wraps=analyze_pcm16_tail,
            ) as analyze_tail:
                merged = static_audio_module.merge_idiom_static_audio_plan(
                    ["idiom_game/start", "idioms/画龙点睛"],
                    [fixed, idiom],
                )

        self.assertEqual(merged, fixed_pcm + idiom_pcm + idiom_post_roll)
        self.assertEqual(merged[len(fixed_pcm) - 16000 : len(fixed_pcm)], b"\x00" * 16000)
        self.assertEqual(merged[len(fixed_pcm) : len(fixed_pcm) + len(idiom_pcm)], idiom_pcm)
        self.assertEqual(merged[-16000:], b"\x00" * 16000)
        analyze_tail.assert_called_once_with(fixed_pcm)

    def test_idiom_static_audio_merge_does_not_add_post_roll_after_fixed_only_plan(self) -> None:
        from src.providers.static_audio import merge_idiom_static_audio_plan

        fixed_pcm = b"\x01\x00\x02\x00" + (b"\x00\x00" * (500 * 16))
        with tempfile.TemporaryDirectory() as tmp:
            fixed = Path(tmp) / "idiom_game" / "retry.wav"
            _write_wav(fixed, pcm=fixed_pcm)

            merged = merge_idiom_static_audio_plan(
                ["idiom_game/retry"],
                [fixed],
            )

        self.assertEqual(merged, fixed_pcm)

    def test_idiom_static_audio_merge_rejects_unsafe_fixed_boundary(self) -> None:
        from src.providers.static_audio import StaticAudioError, merge_idiom_static_audio_plan

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixed = root / "idiom_game" / "start.wav"
            idiom = root / "idioms" / "画龙点睛.wav"
            _write_wav(fixed, pcm=b"\xb0\x04" * 320)
            _write_wav(idiom, pcm=b"\x21\x43\x65\x07")

            with self.assertRaisesRegex(
                StaticAudioError,
                "static_audio_unsafe_tail:idiom_game/start",
            ):
                merge_idiom_static_audio_plan(
                    ["idiom_game/start", "idioms/画龙点睛"],
                    [fixed, idiom],
                )

    def test_static_audio_chunk_size_default_is_large_enough_for_board_streaming(self) -> None:
        from src.settings import Settings

        settings = Settings(_env_file=None)

        self.assertEqual(settings.static_audio_chunk_size, 4096)


if __name__ == "__main__":
    unittest.main()
