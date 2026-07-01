from __future__ import annotations

from tests._stubs import install_dependency_stubs

install_dependency_stubs()

from src.providers import llm


def test_short_answer_prompt_is_coffee_robot_persona() -> None:
    messages = llm._build_messages(
        "手冲咖啡为什么会酸",
        [{"source_title": "CF02", "snippet": "偏酸时可以磨细一点、提高水温或延长萃取。"}],
        answer_mode="short",
    )

    joined = "\n".join(message["content"] for message in messages)
    assert "小机仔" in joined
    assert "咖啡" in joined
    assert "1到3句话" in joined
    assert "不要编造品牌、价格、门店或活动信息" in joined


def test_prompt_references_coffee_evidence_without_source_speech() -> None:
    messages = llm._build_messages(
        "拿铁和卡布奇诺有什么区别",
        [{"source_title": "CF03", "snippet": "拿铁奶量更多，卡布奇诺奶泡更明显。"}],
    )

    user_message = messages[1]["content"]
    assert "拿铁奶量更多" in user_message
    assert "不要把资料来源直接说出口" in user_message
