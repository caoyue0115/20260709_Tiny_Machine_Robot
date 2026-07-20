from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from src.providers.llm import judge_idiom_answer
from src.settings import settings
from src.voice_skills.idiom_game import (
    IdiomGameSkill,
    IdiomJudgeDecision,
    InMemoryIdiomGameStore,
    build_idiom_audio_plan,
    clean_idiom_text,
    load_default_idioms,
)
from src.voice_skills.idiom_audio import get_idiom_audio_catalog


_START_IDIOM_GAME_PHRASES = ("开始成语接龙", "玩成语接龙", "来成语接龙", "成语接龙")
_EXIT_IDIOM_GAME_PHRASES = (
    "退出",
    "推出",
    "结束",
    "不玩了",
    "不想玩了",
    "我不玩了",
    "退出游戏",
    "推出游戏",
    "结束游戏",
    "退出成语接龙",
    "推出成语接龙",
    "结束成语接龙",
    "退出接龙",
    "结束接龙",
    "先这样",
    "停止",
    "结束吧",
)
_REPEAT_IDIOM_GAME_PHRASES = (
    "没听清",
    "没听到",
    "再说一次",
    "再说一遍",
    "重复一下",
    "重复一遍",
    "刚才是什么",
)


@dataclass
class SkillResult:
    skill_name: str
    answer_text: str | None = None
    answer_stream: Iterable[str] | None = None
    audio_plan: list[str] | None = None
    end_skill_state: bool = False
    skill_active: bool | None = None
    turn_outcome: str | None = None
    trace: dict = field(default_factory=dict)


def _idiom_turn_outcome(trace: dict, *, end_skill_state: bool) -> str:
    if end_skill_state:
        return "exit"
    event = str(trace.get("idiom_event") or "")
    if event in {"start", "robot_reply", "repeat", "legacy_difficulty_ignored"}:
        return "meaningful"
    if event == "off_topic":
        return "off_topic"
    return "invalid"


def _parse_enabled_skills(raw: str | Iterable[str] | None) -> set[str]:
    if raw is None:
        return {"idiom_game"}
    if isinstance(raw, str):
        return {part.strip() for part in raw.split(",") if part.strip()}
    return {str(part).strip() for part in raw if str(part).strip()}


def _payload_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _payload_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _judge_unknown_idiom_with_llm(text: str, expected_py: str) -> IdiomJudgeDecision | None:
    payload = judge_idiom_answer(text, expected_py)
    if payload is None:
        return None
    return IdiomJudgeDecision(
        word=str(payload.get("normalized_idiom") or payload.get("word") or ""),
        first_py=str(payload.get("first_py") or ""),
        last_py=str(payload.get("last_py") or ""),
        intent=str(payload.get("intent") or "unknown"),
        confidence=_payload_float(payload.get("confidence")),
        is_idiom=_payload_bool(payload.get("is_idiom")),
        matches_expected_pinyin=_payload_bool(payload.get("matches_expected_pinyin")),
    )


class SkillRouter:
    def __init__(
        self,
        *,
        idiom_skill: IdiomGameSkill,
        enabled_skills: str | Iterable[str] | None = None,
    ) -> None:
        self._idiom_skill = idiom_skill
        self._enabled_skills = _parse_enabled_skills(enabled_skills)

    def route(
        self,
        *,
        device_id: str,
        text: str,
        answer_mode: str | None = None,
        trace: dict | None = None,
    ) -> SkillResult | None:
        del answer_mode
        raw_text = str(text or "").strip()
        cleaned_text = clean_idiom_text(raw_text)
        base_trace = dict(trace or {})

        if "idiom_game" not in self._enabled_skills:
            return None

        if self._idiom_skill.store.is_active(device_id):
            if self._matches_any(cleaned_text, _EXIT_IDIOM_GAME_PHRASES):
                answer_text = self._idiom_skill.exit(device_id)
                return self._text_result(
                    "idiom_game",
                    answer_text,
                    self._idiom_trace(base_trace),
                    audio_plan=build_idiom_audio_plan(answer_text),
                    end_skill_state=True,
                )
            if self._matches_any(cleaned_text, _REPEAT_IDIOM_GAME_PHRASES):
                answer_text = self._idiom_skill.repeat(device_id)
                idiom_trace = self._idiom_trace(base_trace)
                return self._text_result(
                    "idiom_game",
                    answer_text,
                    idiom_trace,
                    audio_plan=build_idiom_audio_plan(answer_text, idiom_trace),
                )
            answer_text = self._idiom_skill.handle(device_id, raw_text)
            idiom_trace = self._idiom_trace(base_trace)
            end_skill_state = not self._idiom_skill.store.is_active(device_id)
            return self._text_result(
                "idiom_game",
                answer_text,
                idiom_trace,
                audio_plan=build_idiom_audio_plan(answer_text, idiom_trace),
                end_skill_state=end_skill_state,
            )

        if self._matches_any(cleaned_text, _START_IDIOM_GAME_PHRASES):
            answer_text = self._idiom_skill.start(device_id, raw_text)
            idiom_trace = self._idiom_trace(base_trace)
            return self._text_result(
                "idiom_game",
                answer_text,
                idiom_trace,
                audio_plan=build_idiom_audio_plan(answer_text, idiom_trace),
            )

        return None

    def end_idiom_game(self, device_id: str) -> bool:
        if not self._idiom_skill.store.is_active(device_id):
            return False
        self._idiom_skill.exit(device_id)
        return True

    @staticmethod
    def _matches_any(cleaned_text: str, phrases: tuple[str, ...]) -> bool:
        return any(phrase in cleaned_text for phrase in phrases)

    def _text_result(
        self,
        skill_name: str,
        answer_text: str,
        trace: dict,
        *,
        audio_plan: list[str] | None = None,
        end_skill_state: bool = False,
    ) -> SkillResult:
        catalog = get_idiom_audio_catalog() if skill_name == "idiom_game" else None
        if catalog is not None and audio_plan:
            resolved_plan = catalog.resolve_plan(audio_plan)
            if resolved_plan != audio_plan:
                trace = dict(trace)
                trace["idiom_audio_plan_fallback"] = catalog.static_error_segment
            audio_plan = resolved_plan
        return SkillResult(
            skill_name=skill_name,
            answer_text=answer_text,
            audio_plan=audio_plan,
            end_skill_state=end_skill_state,
            skill_active=not end_skill_state,
            turn_outcome=(
                _idiom_turn_outcome(trace, end_skill_state=end_skill_state)
                if skill_name == "idiom_game"
                else None
            ),
            trace=self._trace(trace, skill_name),
        )

    @staticmethod
    def _trace(trace: dict, skill_name: str) -> dict:
        result = dict(trace)
        result["skill_name"] = skill_name
        return result

    def _idiom_trace(self, trace: dict) -> dict:
        result = dict(trace)
        result.update(self._idiom_skill.last_trace())
        return result


_default_router: SkillRouter | None = None
_default_router_catalog: object | None = None


def get_default_skill_router() -> SkillRouter:
    global _default_router, _default_router_catalog
    catalog = get_idiom_audio_catalog()
    if _default_router is None or catalog is not _default_router_catalog:
        _default_router = SkillRouter(
            idiom_skill=IdiomGameSkill(
                load_default_idioms(),
                store=InMemoryIdiomGameStore(ttl_seconds=settings.idiom_game_ttl_seconds),
                judge_unknown_idiom=(
                    _judge_unknown_idiom_with_llm if settings.idiom_game_llm_judge_enabled else None
                ),
                judge_min_confidence=settings.idiom_game_llm_judge_min_confidence,
                playable_words=catalog.playable_words if catalog is not None else None,
            ),
            enabled_skills=settings.enabled_skills,
        )
        _default_router_catalog = catalog
    return _default_router


def route_voice_skill(
    *,
    device_id: str,
    text: str,
    answer_mode: str | None = None,
    trace: dict | None = None,
) -> SkillResult | None:
    return get_default_skill_router().route(
        device_id=device_id,
        text=text,
        answer_mode=answer_mode,
        trace=trace,
    )


def end_idiom_game(device_id: str) -> bool:
    return get_default_skill_router().end_idiom_game(device_id)
