from __future__ import annotations

import pytest

from tests._stubs import install_dependency_stubs

install_dependency_stubs()

from src.domain import coffee
from src.domain.coffee import COFFEE_RETRY_TEXT as DOMAIN_COFFEE_RETRY_TEXT
from src.services import realtime_session


def test_coffee_asr_normalization_rules_are_named() -> None:
    normalized, rules = realtime_session.normalize_coffee_asr_text("美式和拿帖有什么区别")

    assert normalized == "美式和拿铁有什么区别"
    assert rules == ["拿帖->拿铁"]


@pytest.mark.parametrize(
    ("raw_text", "expected_text", "expected_rules"),
    [
        ("拿贴有什么区别", "拿铁有什么区别", ["拿贴->拿铁"]),
        ("卡布其诺怎么做", "卡布奇诺怎么做", ["卡布其诺->卡布奇诺"]),
        ("卡布奇洛怎么做", "卡布奇诺怎么做", ["卡布奇洛->卡布奇诺"]),
        ("意式浓锁怎么萃取", "意式浓缩怎么萃取", ["意式浓锁->意式浓缩"]),
        ("手充咖啡怎么冲", "手冲咖啡怎么冲", ["手充->手冲"]),
        ("手冲加啡怎么冲", "手冲咖啡怎么冲", ["手冲加啡->手冲咖啡"]),
        ("咖非怎么选豆", "咖啡怎么选豆", ["咖非->咖啡"]),
        ("格夏豆适合手冲吗", "瑰夏豆适合手冲吗", ["格夏->瑰夏"]),
        ("手充咖啡用格夏豆", "手冲咖啡用瑰夏豆", ["手充->手冲", "格夏->瑰夏"]),
    ],
)
def test_coffee_asr_normalization_covers_direct_coffee_terms(
    raw_text: str,
    expected_text: str,
    expected_rules: list[str],
) -> None:
    normalized, rules = realtime_session.normalize_coffee_asr_text(raw_text)

    assert normalized == expected_text
    assert rules == expected_rules


def test_coffee_asr_normalization_chains_order_dependent_rules() -> None:
    normalized, rules = realtime_session.normalize_coffee_asr_text("手充加啡怎么冲")

    assert normalized == "手冲咖啡怎么冲"
    assert rules == ["手充->手冲", "手冲加啡->手冲咖啡"]


def test_reject_prompt_is_coffee_specific() -> None:
    assert realtime_session.COFFEE_RETRY_TEXT == "我还没听清，可以再问我一个咖啡问题吗？"
    assert DOMAIN_COFFEE_RETRY_TEXT == realtime_session.COFFEE_RETRY_TEXT


def test_coffee_asr_normalization_recovers_missing_coffee_for_acid_cup() -> None:
    normalized, rules = realtime_session.normalize_coffee_asr_text("\u676f\u662f\u9178\u7684\u3002")

    assert normalized == "\u5496\u5561\u662f\u9178\u7684\u3002"
    assert rules == ["\u676f\u662f\u9178\u7684->\u5496\u5561\u662f\u9178\u7684"]


def test_identity_questions_have_direct_coffee_robot_answer() -> None:
    assert coffee.answer_identity_question("你是谁") == coffee.COFFEE_IDENTITY_TEXT
    assert coffee.answer_identity_question("你谁？") == coffee.COFFEE_IDENTITY_TEXT
    assert coffee.answer_identity_question("你叫什么名字？") == coffee.COFFEE_IDENTITY_TEXT
    assert "咖啡小机器人" in coffee.COFFEE_IDENTITY_TEXT
    assert coffee.answer_identity_question("手冲咖啡为什么会偏酸") is None
