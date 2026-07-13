from __future__ import annotations

import json
import re
from collections.abc import Iterator

from openai import OpenAI

from src.settings import settings


ANSWER_MODE_DEFAULT = "default"
ANSWER_MODE_SHORT = "short"
SHORT_ANSWER_MAX_TOKENS = 96
TINY_COFFEE_SYSTEM_PROMPT = (
    "你是小机仔，也叫Tiny Coffee Machine，一名咖啡小机器人。"
    "优先回答咖啡豆、饮品、器具、研磨、萃取、烘焙、风味、冲煮和伴手礼相关问题。"
    "身份、寒暄和常识类简短问题也要尽量直接回答，并保持咖啡小机器人的角色。"
    "请用中文口语化回答，适合语音播报，控制在1到3句话。"
    "咖啡专业问题优先依据给定咖啡资料证据作答；资料不足就说明不确定，再给通用建议。"
    "不要编造品牌、价格、门店或活动信息，也不要编造库存或优惠信息。"
)
IDIOM_JUDGE_SYSTEM_PROMPT = (
    "你是成语接龙意图分类器和裁判。"
    "先判断用户意图是idiom、exit、repeat、easy、hard、invalid或off_topic。"
    "当意图是idiom时，从语音识别文本中找出用户真正想接的一个成语，忽略“我接”“答案是”等口语噪声，"
    "判断它是否是规范成语，并给出首字和末字的普通话拼音。"
    "拼音必须小写、无声调、只保留英文字母，例如 jing、guo。"
    "只返回JSON，不要解释。"
)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)


def llm_health() -> bool:
    return bool(settings.dashscope_api_key)


def _build_client() -> OpenAI:
    return OpenAI(
        api_key=settings.dashscope_api_key,
        base_url=f"{settings.dashscope_base_url.rstrip('/')}/compatible-mode/v1",
        timeout=float(settings.request_timeout_seconds),
    )


def _normalize_answer_mode(answer_mode: str | None) -> str:
    return ANSWER_MODE_SHORT if str(answer_mode or "").strip().lower() == ANSWER_MODE_SHORT else ANSWER_MODE_DEFAULT


def _build_messages(
    question_text: str,
    references: list[dict],
    *,
    answer_mode: str | None = None,
) -> list[dict[str, str]]:
    evidence = "\n".join(f"- {item['source_title']}: {item['snippet']}" for item in references)
    if not evidence:
        evidence = "（本题没有检索到可用咖啡资料。）"
    if _normalize_answer_mode(answer_mode) == ANSWER_MODE_SHORT:
        return [
            {
                "role": "system",
                "content": TINY_COFFEE_SYSTEM_PROMPT + "短答时尽量1到2句，总字数不超过70字。",
            },
            {
                "role": "user",
                "content": (
                    f"问题：{question_text}\n"
                    f"证据：\n{evidence}\n"
                    "回答要求：请用中文回答，适合语音播报，1到3句内，总字数不超过70字。"
                    "先直接回答用户问题，再给一句可操作的理解或建议。"
                    "不要因为资料为空就说没听清；不确定时说明不确定。"
                    "不要把资料来源直接说出口。"
                ),
            },
        ]
    return [
        {
            "role": "system",
            "content": TINY_COFFEE_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": (
                f"问题：{question_text}\n"
                f"证据：\n{evidence}\n"
                "回答要求：先直接回答用户问题，再给一句简短原因或建议。"
                "不要因为资料为空就说没听清；不确定时说明不确定。"
                "不要把资料来源直接说出口。"
            ),
        },
    ]


def _max_tokens_for_answer_mode(answer_mode: str | None) -> int:
    if _normalize_answer_mode(answer_mode) == ANSWER_MODE_SHORT:
        return min(settings.llm_max_tokens, SHORT_ANSWER_MAX_TOKENS)
    return settings.llm_max_tokens


def _iter_chunk_text(response_stream: object) -> Iterator[str]:
    for chunk in response_stream:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        content = getattr(delta, "content", None)
        if isinstance(content, str):
            if content:
                yield content
            continue
        if isinstance(content, list):
            for item in content:
                text = getattr(item, "text", None) or getattr(item, "content", None)
                if text:
                    yield str(text)


def _response_message_text(response: object) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            text = getattr(item, "text", None) or getattr(item, "content", None)
            if text:
                chunks.append(str(text))
        return "".join(chunks).strip()
    return ""


def _parse_json_object(text: str) -> dict | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(text)
        if match is None:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def stream_answer_text(
    question_text: str,
    references: list[dict],
    *,
    answer_mode: str | None = None,
) -> Iterator[str]:
    client = _build_client()
    response_stream = client.chat.completions.create(
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=_max_tokens_for_answer_mode(answer_mode),
        messages=_build_messages(question_text, references, answer_mode=answer_mode),
        stream=True,
        extra_body={"enable_thinking": False},
    )
    yield from _iter_chunk_text(response_stream)


def generate_answer(question_text: str, references: list[dict]) -> str:
    return "".join(stream_answer_text(question_text, references)).strip()


def judge_idiom_answer(raw_text: str, expected_py: str) -> dict | None:
    if not llm_health():
        return None
    client = _build_client()
    response = client.chat.completions.create(
        model=settings.llm_model,
        temperature=0,
        max_tokens=128,
        messages=[
            {"role": "system", "content": IDIOM_JUDGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"当前需要接的首字拼音：{expected_py}\n"
                    f"用户ASR文本：{raw_text}\n"
                    "请返回如下JSON："
                    '{"intent": "idiom | exit | repeat | easy | hard | invalid | off_topic", '
                    '"normalized_idiom": "四字成语或空字符串", "first_py": "首字拼音或空", '
                    '"last_py": "末字拼音或空", "is_idiom": true, '
                    '"matches_expected_pinyin": false, "confidence": 0.0}\n'
                    "控制意图忽略成语和拼音字段。没有清晰成语时is_idiom=false。"
                    "即使首字拼音不匹配，也返回实际first_py；matches_expected_pinyin仅用于诊断。"
                ),
            },
        ],
        stream=False,
        extra_body={"enable_thinking": False},
    )
    return _parse_json_object(_response_message_text(response))
