from __future__ import annotations

COFFEE_RETRY_TEXT = "我还没听清，可以再问我一个咖啡问题吗？"
COFFEE_IDENTITY_TEXT = "我是小机仔，一个咖啡小机器人，可以陪你聊咖啡、冲煮和伴手礼。"

_IDENTITY_QUESTION_TERMS = (
    "你是谁",
    "你谁",
    "你叫什么",
    "你的名字",
    "介绍一下自己",
    "自我介绍",
    "你是什么",
    "你能做什么",
    "小机仔是谁",
    "tinycoffeemachine是谁",
)


def answer_identity_question(question: str) -> str | None:
    normalized = "".join(str(question or "").casefold().split())
    if not normalized:
        return None
    if any(term in normalized for term in _IDENTITY_QUESTION_TERMS):
        return COFFEE_IDENTITY_TEXT
    return None
