from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests._stubs import install_dependency_stubs

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

install_dependency_stubs()


class LlmProviderTests(unittest.TestCase):
    def test_default_llm_model_uses_flash_model(self) -> None:
        from src.settings import Settings

        self.assertEqual(Settings().llm_model, "qwen3.5-flash-2026-02-23")

    def test_build_messages_uses_coffee_persona_and_scope(self) -> None:
        from src.providers.llm import _build_messages

        messages = _build_messages(
            "手冲咖啡为什么会偏酸",
            [{"source_title": "手冲咖啡", "snippet": "研磨偏粗或水温偏低时，酸味会更明显。"}],
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("小机仔", messages[0]["content"])
        self.assertIn("咖啡", messages[0]["content"])
        self.assertIn("中文", messages[0]["content"])
        self.assertIn("1到3句", messages[0]["content"])
        self.assertIn("适合语音播报", messages[0]["content"])
        self.assertIn("不要编造品牌、价格、门店、活动", messages[0]["content"])
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("问题：手冲咖啡为什么会偏酸", messages[1]["content"])
        self.assertIn("手冲咖啡", messages[1]["content"])
        self.assertIn("研磨偏粗", messages[1]["content"])

    def test_short_answer_mode_uses_stricter_length_prompt(self) -> None:
        from src.providers.llm import _build_messages

        messages = _build_messages(
            "拿铁和卡布奇诺有什么区别",
            [{"source_title": "拿铁", "snippet": "拿铁奶量更多，卡布奇诺奶泡更厚。"}],
            answer_mode="short",
        )

        self.assertIn("小机仔", messages[0]["content"])
        self.assertIn("咖啡", messages[0]["content"])
        self.assertIn("1到3句", messages[0]["content"])
        self.assertIn("不超过70字", messages[0]["content"])
        self.assertIn("不要编造品牌、价格、门店、活动", messages[0]["content"])
        self.assertIn("不超过70字", messages[1]["content"])

    def test_stream_answer_disables_thinking_for_dashscope_flash_model(self) -> None:
        from src.providers import llm

        captured_kwargs: dict = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured_kwargs.update(kwargs)
                chunk = SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="酸味通常来自萃取不足。"))]
                )
                return iter([chunk])

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )

        with patch.object(llm, "_build_client", return_value=fake_client):
            chunks = list(llm.stream_answer_text("手冲咖啡为什么会偏酸", []))

        self.assertEqual(chunks, ["酸味通常来自萃取不足。"])
        self.assertEqual(captured_kwargs["model"], "qwen3.5-flash-2026-02-23")
        self.assertEqual(captured_kwargs["extra_body"], {"enable_thinking": False})
        self.assertTrue(captured_kwargs["stream"])

    def test_stream_answer_short_mode_uses_fixed_smaller_max_tokens(self) -> None:
        from src.providers import llm

        captured_kwargs: dict = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured_kwargs.update(kwargs)
                chunk = SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="拿铁奶感更重。"))]
                )
                return iter([chunk])

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )

        with patch.object(llm, "_build_client", return_value=fake_client):
            chunks = list(llm.stream_answer_text("拿铁和卡布奇诺有什么区别", [], answer_mode="short"))

        self.assertEqual(chunks, ["拿铁奶感更重。"])
        self.assertLessEqual(captured_kwargs["max_tokens"], 96)
        self.assertIn("不超过70字", captured_kwargs["messages"][0]["content"])


if __name__ == "__main__":
    unittest.main()
