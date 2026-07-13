from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.providers.static_audio import StaticAudioError, validate_static_audio_segment
from src.voice_skills.idiom_game import IdiomEntry, load_default_idioms


STATIC_ERROR_SEGMENT = "idiom_game/static_error"
REQUIRED_FIXED_SEGMENTS = frozenset(
    {
        "idiom_game/start",
        "idiom_game/robot_first",
        "idiom_game/need_prefix",
        "idiom_game/need_suffix",
        "idiom_game/repeated_prefix",
        "idiom_game/repeated_suffix",
        "idiom_game/user_connected_prefix",
        "idiom_game/robot_no_reply_user_win",
        "idiom_game/not_found",
        "idiom_game/exit",
        "idiom_game/mode_easy",
        "idiom_game/mode_normal",
        "idiom_game/mode_hard",
        "idiom_game/mode_full",
        "idiom_game/challenge_win",
        "idiom_game/continue_prompt",
        "idiom_game/retry",
        STATIC_ERROR_SEGMENT,
    }
)


@dataclass(frozen=True)
class IdiomAudioCatalog:
    playable_words: frozenset[str]
    invalid_idiom_words: frozenset[str]
    invalid_fixed_segments: frozenset[str]
    static_error_segment: str = STATIC_ERROR_SEGMENT

    def resolve_plan(self, segment_ids: Iterable[str]) -> list[str]:
        plan = [str(segment_id) for segment_id in segment_ids]
        for segment_id in plan:
            if segment_id in self.invalid_fixed_segments:
                return [self.static_error_segment]
            if segment_id.startswith("idioms/") and segment_id.removeprefix("idioms/") not in self.playable_words:
                return [self.static_error_segment]
        return plan


_catalog: IdiomAudioCatalog | None = None


def build_idiom_audio_catalog(
    idioms: Iterable[IdiomEntry], root: Path | None = None
) -> IdiomAudioCatalog:
    validate_static_audio_segment(STATIC_ERROR_SEGMENT, root=root)
    invalid_fixed: set[str] = set()
    for segment_id in REQUIRED_FIXED_SEGMENTS - {STATIC_ERROR_SEGMENT}:
        try:
            validate_static_audio_segment(segment_id, root=root)
        except StaticAudioError:
            invalid_fixed.add(segment_id)

    playable: set[str] = set()
    invalid_idioms: set[str] = set()
    for idiom in idioms:
        try:
            validate_static_audio_segment(f"idioms/{idiom.word}", root=root)
        except StaticAudioError:
            invalid_idioms.add(idiom.word)
        else:
            playable.add(idiom.word)
    return IdiomAudioCatalog(
        playable_words=frozenset(playable),
        invalid_idiom_words=frozenset(invalid_idioms),
        invalid_fixed_segments=frozenset(invalid_fixed),
    )


def initialize_idiom_audio_catalog() -> IdiomAudioCatalog:
    global _catalog
    _catalog = build_idiom_audio_catalog(load_default_idioms())
    return _catalog


def get_idiom_audio_catalog() -> IdiomAudioCatalog | None:
    return _catalog
