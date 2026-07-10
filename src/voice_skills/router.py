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


_START_IDIOM_GAME_PHRASES = ("开始成语接龙", "玩成语接龙", "来成语接龙", "成语接龙")
_EXIT_IDIOM_GAME_PHRASES = ("退出", "结束", "不玩了", "退出游戏", "结束游戏")


@dataclass
class SkillResult:
    skill_name: str
    answer_text: str | None = None
    answer_stream: Iterable[str] | None = None
    audio_plan: list[str] | None = None
    end_skill_state: bool = False
    trace: dict = field(default_factory=dict)


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
        confidence=_payload_float(payload.get("confidence")),
        is_idiom=_payload_bool(payload.get("is_idiom")),
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
            answer_text = self._idiom_skill.handle(device_id, raw_text)
            return self._text_result(
                "idiom_game",
                answer_text,
                self._idiom_trace(base_trace),
                audio_plan=build_idiom_audio_plan(answer_text),
            )

        if self._matches_any(cleaned_text, _START_IDIOM_GAME_PHRASES):
            answer_text = self._idiom_skill.start(device_id, raw_text)
            return self._text_result(
                "idiom_game",
                answer_text,
                self._idiom_trace(base_trace),
                audio_plan=build_idiom_audio_plan(answer_text),
            )

        return None

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
        return SkillResult(
            skill_name=skill_name,
            answer_text=answer_text,
            audio_plan=audio_plan,
            end_skill_state=end_skill_state,
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


def get_default_skill_router() -> SkillRouter:
    global _default_router
    if _default_router is None:
        _default_router = SkillRouter(
            idiom_skill=IdiomGameSkill(
                load_default_idioms(),
                store=InMemoryIdiomGameStore(ttl_seconds=settings.idiom_game_ttl_seconds),
                judge_unknown_idiom=(
                    _judge_unknown_idiom_with_llm if settings.idiom_game_llm_judge_enabled else None
                ),
                judge_min_confidence=settings.idiom_game_llm_judge_min_confidence,
                robot_difficulty=settings.idiom_game_robot_difficulty,
                target_user_turns=settings.idiom_game_target_user_turns,
            ),
            enabled_skills=settings.enabled_skills,
        )
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
