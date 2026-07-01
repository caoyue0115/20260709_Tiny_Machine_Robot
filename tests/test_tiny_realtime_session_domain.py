from __future__ import annotations

from tests._stubs import install_dependency_stubs

install_dependency_stubs()

from src.services import realtime_session


def test_coffee_asr_normalization_rules_are_named() -> None:
    normalized, rules = realtime_session.normalize_coffee_asr_text("美式和拿帖有什么区别")

    assert normalized == "美式和拿铁有什么区别"
    assert rules == ["拿帖->拿铁"]


def test_reject_prompt_is_coffee_specific() -> None:
    assert realtime_session.COFFEE_RETRY_TEXT == "我还没听清，可以再问我一个咖啡问题吗？"
