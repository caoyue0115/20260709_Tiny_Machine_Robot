from __future__ import annotations

import json
import random
import re
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path


_TEXT_CLEAN_RE = re.compile(r"[\s,，。.!！?？:：;；、\"'“”‘’（）()\[\]【】]+")
_START_REPLY_RE = re.compile(r"小机仔先来：(?P<word>[^。]+)。")
_CHAIN_REPLY_RE = re.compile(r"小机仔接：(?P<word>[^。]+)。轮到你啦，要接“(?P<py>[^”]+)”")
_NEED_REPLY_RE = re.compile(r"要接“(?P<py>[^”]+)”开头的成语哦")
_REPEATED_REPLY_RE = re.compile(r"“(?P<word>[^”]+)”刚刚用过啦")
_WIN_REPLY_RE = re.compile(r"你接上了“(?P<word>[^”]+)”，小机仔暂时接不上啦")
_PINYIN_TONE_TRANS = str.maketrans(
    {
        "ā": "a",
        "á": "a",
        "ǎ": "a",
        "à": "a",
        "ē": "e",
        "é": "e",
        "ě": "e",
        "è": "e",
        "ī": "i",
        "í": "i",
        "ǐ": "i",
        "ì": "i",
        "ō": "o",
        "ó": "o",
        "ǒ": "o",
        "ò": "o",
        "ū": "u",
        "ú": "u",
        "ǔ": "u",
        "ù": "u",
        "ǖ": "v",
        "ǘ": "v",
        "ǚ": "v",
        "ǜ": "v",
        "ü": "v",
    }
)
_ASSISTANT_PREFIXES = ("小机仔", "小明同学")
_LEADING_NOISE_PHRASES = tuple(
    sorted(
        (
            "那我来接一个",
            "那我接一个",
            "我来接一个",
            "我想接一个",
            "我要接一个",
            "我接一个",
            "接一个",
            "那我来接",
            "那我接",
            "我来接",
            "我想接",
            "我要接",
            "我接",
            "答案是",
            "成语是",
            "接",
        ),
        key=len,
        reverse=True,
    )
)
_TRAILING_NOISE_PARTICLES = ("吧", "呀", "啊", "哦", "啦", "了", "呢")
_DEFAULT_OPENING_WORDS = (
    "画龙点睛",
    "精卫填海",
    "海阔天空",
    "空前绝后",
    "后来居上",
    "上善若水",
    "水到渠成",
    "成竹在胸",
    "胸有成竹",
    "竹报平安",
    "安居乐业",
    "叶公好龙",
    "龙马精神",
    "神采飞扬",
    "扬眉吐气",
    "气象万千",
    "千言万语",
    "语重心长",
    "长驱直入",
    "入木三分",
)
_ROBOT_REPLY_LIMITS: dict[str, int | None] = {
    "easy": 500,
    "normal": 3000,
    "hard": 10000,
    "full": None,
}
_DIFFICULTY_TARGET_TURNS = {
    "easy": 8,
    "normal": 15,
    "hard": 25,
    "full": 50,
}
_DIFFICULTY_LABELS = {
    "easy": "简单",
    "normal": "普通",
    "hard": "困难",
    "full": "大师",
}
_DIFFICULTY_COMMAND_PATTERNS = (
    (
        "easy",
        (
            "简单模式",
            "容易模式",
            "简单难度",
            "低难度",
            "切换简单",
            "切换到简单",
            "换成简单",
            "改成简单",
            "调成简单",
            "简单一点",
            "容易一点",
        ),
    ),
    (
        "normal",
        (
            "普通模式",
            "正常模式",
            "标准模式",
            "普通难度",
            "切换普通",
            "切换到普通",
            "换成普通",
            "改成普通",
            "调成普通",
        ),
    ),
    (
        "hard",
        (
            "困难模式",
            "难度模式",
            "挑战模式",
            "困难难度",
            "高难度",
            "切换困难",
            "切换到困难",
            "换成困难",
            "改成困难",
            "调成困难",
            "难一点",
        ),
    ),
    (
        "full",
        (
            "大师模式",
            "全量模式",
            "专家模式",
            "全部词库",
            "完整词库",
            "切换大师",
            "切换到大师",
            "换成大师",
        ),
    ),
)
_REPEAT_COMMAND_PATTERNS = (
    "没听清",
    "没听到",
    "再说一次",
    "再说一遍",
    "重复一下",
    "重复一遍",
    "刚才是什么",
)
_FOUR_HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]{4}")
_NOISE_ONLY_RE = re.compile(r"[啊呀哦嗯呃额诶唉哈哼唔…]+")


@dataclass(frozen=True)
class IdiomEntry:
    word: str
    first_py: str
    last_py: str


@dataclass(frozen=True)
class IdiomJudgeDecision:
    word: str
    first_py: str
    last_py: str
    intent: str = "idiom"
    confidence: float = 1.0
    is_idiom: bool = True
    matches_expected_pinyin: bool = False


JudgeUnknownIdiom = Callable[[str, str], IdiomJudgeDecision | None]


@dataclass
class IdiomGameState:
    expected_py: str
    used_words: set[str] = field(default_factory=set)
    valid_user_turns: int = 0
    robot_difficulty: str = "full"
    last_robot_word: str = ""
    updated_at: float = field(default_factory=time.time)


def normalize_pinyin(value: str) -> str:
    normalized = str(value or "").strip().lower().translate(_PINYIN_TONE_TRANS)
    return re.sub(r"[^a-z]", "", normalized)


def clean_idiom_text(text: str) -> str:
    cleaned = _TEXT_CLEAN_RE.sub("", str(text or ""))
    for prefix in _ASSISTANT_PREFIXES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    for prefix in _LEADING_NOISE_PHRASES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break
    while len(cleaned) > 4 and cleaned.endswith(_TRAILING_NOISE_PARTICLES):
        cleaned = cleaned[:-1]
    return cleaned


def normalize_robot_difficulty(value: str) -> str:
    difficulty = str(value or "").strip().lower()
    return difficulty if difficulty in _ROBOT_REPLY_LIMITS else "normal"


def robot_difficulty_label(value: str) -> str:
    return _DIFFICULTY_LABELS[normalize_robot_difficulty(value)]


def robot_difficulty_target_turns(value: str) -> int:
    return _DIFFICULTY_TARGET_TURNS[normalize_robot_difficulty(value)]


def detect_idiom_difficulty(text: str) -> str | None:
    cleaned = clean_idiom_text(text)
    for difficulty, patterns in _DIFFICULTY_COMMAND_PATTERNS:
        if any(pattern in cleaned for pattern in patterns):
            return difficulty
    return None


def detect_idiom_repeat(text: str) -> bool:
    cleaned = clean_idiom_text(text)
    return any(pattern in cleaned for pattern in _REPEAT_COMMAND_PATTERNS)


def build_idiom_audio_plan(answer_text: str, trace: dict | None = None) -> list[str] | None:
    text = str(answer_text or "")
    event = str((trace or {}).get("idiom_event") or "")
    result = str((trace or {}).get("idiom_result") or "")
    robot_word = str((trace or {}).get("idiom_robot_reply_word") or "")
    if result == "user_win_robot_no_reply":
        return ["idiom_game/robot_no_reply_user_win"]
    if result == "user_win_target_turns":
        return ["idiom_game/challenge_win"]
    if event == "start" and robot_word:
        return ["idiom_game/start", "idiom_game/robot_first", f"idioms/{robot_word}"]
    if event in {"robot_reply", "repeat"} and robot_word:
        return [f"idioms/{robot_word}"]
    if event == "difficulty_switch":
        difficulty = str((trace or {}).get("idiom_robot_difficulty") or "")
        if difficulty in {"easy", "normal", "hard", "full"}:
            return [f"idiom_game/mode_{difficulty}"]
    if event == "exit":
        return ["idiom_game/exit"]
    if event == "off_topic":
        return ["idiom_game/continue_prompt"]
    if event == "judge_retry":
        return ["idiom_game/retry"]

    if "已切换到" in text and "模式" in text:
        return None

    start_match = _START_REPLY_RE.search(text)
    if start_match:
        return [
            "idiom_game/start",
            "idiom_game/robot_first",
            f"idioms/{start_match.group('word')}",
        ]

    chain_match = _CHAIN_REPLY_RE.search(text)
    if chain_match:
        return [f"idioms/{chain_match.group('word')}"]

    need_match = _NEED_REPLY_RE.search(text)
    if need_match:
        return [
            "idiom_game/need_prefix",
            f"pinyin/{need_match.group('py')}",
            "idiom_game/need_suffix",
        ]

    repeated_match = _REPEATED_REPLY_RE.search(text)
    if repeated_match:
        return [
            "idiom_game/repeated_prefix",
            "idiom_game/repeated_suffix",
        ]

    win_match = _WIN_REPLY_RE.search(text)
    if win_match:
        return [
            "idiom_game/user_connected_prefix",
            f"idioms/{win_match.group('word')}",
            "idiom_game/robot_no_reply_user_win",
        ]

    if "这个我还没在成语词库里找到" in text:
        return ["idiom_game/not_found"]
    if "这局先到这里" in text:
        return ["idiom_game/exit"]
    return None


def load_default_idioms(path: Path | None = None) -> list[IdiomEntry]:
    idiom_path = path or Path(__file__).with_name("idioms.json")
    payload = json.loads(idiom_path.read_text(encoding="utf-8"))
    return [
        IdiomEntry(
            word=str(item["word"]),
            first_py=normalize_pinyin(str(item["first_py"])),
            last_py=normalize_pinyin(str(item["last_py"])),
        )
        for item in payload
    ]


class InMemoryIdiomGameStore:
    def __init__(self, ttl_seconds: int = 900) -> None:
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._states: dict[str, IdiomGameState] = {}

    def get(self, device_id: str) -> IdiomGameState | None:
        state = self._states.get(device_id)
        if state is None:
            return None
        if time.time() - state.updated_at > self._ttl_seconds:
            self._states.pop(device_id, None)
            return None
        return state

    def save(self, device_id: str, state: IdiomGameState) -> None:
        state.updated_at = time.time()
        self._states[device_id] = state

    def clear(self, device_id: str) -> None:
        self._states.pop(device_id, None)

    def is_active(self, device_id: str) -> bool:
        return self.get(device_id) is not None


class IdiomGameSkill:
    skill_name = "idiom_game"

    def __init__(
        self,
        idioms: list[IdiomEntry],
        store: InMemoryIdiomGameStore | None = None,
        *,
        opening_words: Iterable[str] | None = None,
        judge_unknown_idiom: JudgeUnknownIdiom | None = None,
        judge_min_confidence: float = 0.8,
        robot_difficulty: str = "full",
        robot_reply_limit: int | None = None,
        target_user_turns: int = 0,
        playable_words: Iterable[str] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        if not idioms:
            raise ValueError("idiom_game_requires_idioms")
        self._idioms = idioms
        self._by_word = {entry.word: entry for entry in idioms}
        self._by_first_py: dict[str, list[IdiomEntry]] = defaultdict(list)
        for entry in idioms:
            self._by_first_py[entry.first_py].append(entry)
        self._default_robot_difficulty = normalize_robot_difficulty(robot_difficulty)
        self._playable_words = set(playable_words) if playable_words is not None else set(self._by_word)
        playable_idioms = [entry for entry in self._idioms if entry.word in self._playable_words]
        if not playable_idioms:
            raise ValueError("idiom_game_requires_playable_idioms")
        self._bot_by_first_py_by_difficulty: dict[str, dict[str, list[IdiomEntry]]] = {}
        for difficulty in _ROBOT_REPLY_LIMITS:
            self._bot_by_first_py_by_difficulty[difficulty] = self._build_reply_index(
                self._select_robot_reply_pool(difficulty, robot_reply_limit)
            )
        self._known_words = sorted(self._by_word, key=len, reverse=True)
        opening_pool_words = tuple(opening_words or _DEFAULT_OPENING_WORDS)
        self._opening_pool = [
            self._by_word[word]
            for word in opening_pool_words
            if word in self._by_word and word in self._playable_words
        ]
        if not self._opening_pool:
            self._opening_pool = playable_idioms[: min(64, len(playable_idioms))]
        self._judge_unknown_idiom = judge_unknown_idiom
        self._judge_min_confidence = max(0.0, min(1.0, float(judge_min_confidence)))
        self._target_user_turns_override = max(0, int(target_user_turns))
        self._rng = rng or random.SystemRandom()
        self._store = store or InMemoryIdiomGameStore()
        self._last_trace: dict[str, object] = {}

    @property
    def store(self) -> InMemoryIdiomGameStore:
        return self._store

    def last_trace(self) -> dict[str, object]:
        return dict(self._last_trace)

    def start(self, device_id: str, text: str | None = None) -> str:
        opening = self._rng.choice(self._opening_pool)
        requested_difficulty = detect_idiom_difficulty(text or "")
        robot_difficulty = requested_difficulty or self._default_robot_difficulty
        self._last_trace = {
            "idiom_event": "start",
            "idiom_expected_py": opening.last_py,
            "idiom_robot_difficulty": robot_difficulty,
            "idiom_target_user_turns": self._target_user_turns_for(robot_difficulty),
            "idiom_llm_judge_used": False,
        }
        self._store.save(
            device_id,
            IdiomGameState(
                expected_py=opening.last_py,
                used_words={opening.word},
                robot_difficulty=robot_difficulty,
                last_robot_word=opening.word,
            ),
        )
        self._last_trace["idiom_robot_reply_word"] = opening.word
        return f"好呀，我们玩成语接龙。小机仔先来：{opening.word}。"

    def exit(self, device_id: str) -> str:
        self._store.clear(device_id)
        self._last_trace = {"idiom_event": "exit", "idiom_llm_judge_used": False}
        return "这局先到这里，小机仔把小本本合上啦。"

    def repeat(self, device_id: str, *, llm_judge_used: bool = False) -> str:
        state = self._store.get(device_id)
        if state is None:
            return self.start(device_id)
        previous_trace = dict(self._last_trace)
        repeat_trace = {
            "idiom_event": "repeat",
            "idiom_result": "repeat",
            "idiom_expected_py": state.expected_py,
            "idiom_robot_reply_word": state.last_robot_word,
            "idiom_robot_difficulty": state.robot_difficulty,
            "idiom_llm_judge_used": llm_judge_used,
        }
        if llm_judge_used:
            for key in (
                "idiom_llm_intent",
                "idiom_llm_judge_confidence",
                "idiom_llm_matches_expected_pinyin",
            ):
                if key in previous_trace:
                    repeat_trace[key] = previous_trace[key]
        self._last_trace = repeat_trace
        return state.last_robot_word

    def handle(self, device_id: str, text: str) -> str:
        state = self._store.get(device_id)
        if state is None:
            return self.start(device_id, text)
        self._last_trace = {
            "idiom_event": "turn",
            "idiom_expected_py": state.expected_py,
            "idiom_robot_difficulty": state.robot_difficulty,
            "idiom_target_user_turns": self._target_user_turns_for(state.robot_difficulty),
            "idiom_llm_judge_used": False,
        }

        requested_difficulty = detect_idiom_difficulty(text)
        if requested_difficulty is not None:
            self._last_trace.update(
                {
                    "idiom_event": "difficulty_switch",
                    "idiom_robot_difficulty": requested_difficulty,
                    "idiom_target_user_turns": self._target_user_turns_for(requested_difficulty),
                    "idiom_valid_user_turns": 0,
                }
            )
            self._store.save(
                device_id,
                IdiomGameState(
                    expected_py=state.expected_py,
                    used_words=set(state.used_words),
                    valid_user_turns=0,
                    robot_difficulty=requested_difficulty,
                    last_robot_word=state.last_robot_word,
                ),
            )
            return (
                f"已切换到{robot_difficulty_label(requested_difficulty)}模式，"
                f"连续接对轮数已重新计算。轮到你啦，要接“{state.expected_py}”。"
            )

        cleaned = clean_idiom_text(text)
        if detect_idiom_repeat(cleaned):
            return self.repeat(device_id)

        user_entry = self._extract_local_entry(cleaned, expected_py=state.expected_py)
        if user_entry is None:
            decision = self._judge_unknown_decision(cleaned, expected_py=state.expected_py)
            if decision is None and self._last_trace.get("idiom_llm_judge_used"):
                self._last_trace.update(
                    {"idiom_event": "judge_retry", "idiom_result": "judge_failed"}
                )
                return "我没听清，请再说一次。"
            if decision is not None:
                intent = str(decision.intent or "unknown").strip().lower()
                if intent == "exit":
                    self._store.clear(device_id)
                    self._last_trace.update({"idiom_event": "exit", "idiom_result": "llm_exit"})
                    return "这局先到这里，小机仔把小本本合上啦。"
                if intent == "repeat":
                    return self.repeat(device_id, llm_judge_used=True)
                if intent in {"easy", "hard"}:
                    return self._switch_difficulty(device_id, state, intent, llm_judge_used=True)
                if intent == "off_topic":
                    self._last_trace.update({"idiom_event": "off_topic", "idiom_result": "off_topic"})
                    return "我们继续成语接龙吧，请说一个能接上的四字成语。"
                if intent == "idiom":
                    user_entry = self._entry_from_judge_decision(decision, expected_py=state.expected_py)
                    if user_entry is None and float(decision.confidence) < self._judge_min_confidence:
                        self._last_trace.update({"idiom_event": "judge_retry", "idiom_result": "low_confidence"})
                        return "我没听清，请再说一次。"
            if user_entry is None:
                self._last_trace["idiom_user_match_source"] = "none"
                self._last_trace["idiom_result"] = "unknown_idiom"
                return "这个我还没在成语词库里找到。你可以换一个四字成语再接。"
        if user_entry.word in state.used_words:
            self._last_trace["idiom_result"] = "repeated_word"
            return f"“{user_entry.word}”刚刚用过啦，成语接龙不能重复哦。"
        if user_entry.first_py != state.expected_py:
            self._last_trace["idiom_result"] = "wrong_prefix"
            return f"要接“{state.expected_py}”开头的成语哦。你可以再来一次。"

        used_words = set(state.used_words)
        used_words.add(user_entry.word)
        valid_user_turns = state.valid_user_turns + 1
        target_user_turns = self._target_user_turns_for(state.robot_difficulty)
        if target_user_turns and valid_user_turns >= target_user_turns:
            self._store.clear(device_id)
            self._last_trace.update(
                {
                    "idiom_result": "user_win_target_turns",
                    "idiom_valid_user_turns": valid_user_turns,
                    "idiom_target_user_turns": target_user_turns,
                }
            )
            return (
                f"你已经连续接上{valid_user_turns}轮啦，"
                f"{robot_difficulty_label(state.robot_difficulty)}模式挑战成功，这局你赢。"
            )

        reply_entry = self._find_reply(user_entry.last_py, used_words, state.robot_difficulty)
        if reply_entry is None:
            self._store.clear(device_id)
            self._last_trace.update(
                {
                    "idiom_result": "user_win_robot_no_reply",
                    "idiom_valid_user_turns": valid_user_turns,
                    "idiom_target_user_turns": target_user_turns,
                }
            )
            return f"你接上了“{user_entry.word}”，小机仔暂时接不上啦，这局你赢。"

        used_words.add(reply_entry.word)
        self._last_trace.update(
            {
                "idiom_result": "robot_replied",
                "idiom_valid_user_turns": valid_user_turns,
                "idiom_target_user_turns": target_user_turns,
                "idiom_robot_reply_word": reply_entry.word,
                "idiom_robot_reply_first_py": reply_entry.first_py,
                "idiom_robot_reply_last_py": reply_entry.last_py,
                "idiom_next_expected_py": reply_entry.last_py,
            }
        )
        self._store.save(
            device_id,
            IdiomGameState(
                expected_py=reply_entry.last_py,
                used_words=used_words,
                valid_user_turns=valid_user_turns,
                robot_difficulty=state.robot_difficulty,
                last_robot_word=reply_entry.word,
            ),
        )
        self._last_trace["idiom_event"] = "robot_reply"
        return reply_entry.word

    def _extract_local_entry(self, cleaned_text: str, *, expected_py: str) -> IdiomEntry | None:
        exact = self._by_word.get(cleaned_text)
        if exact is not None:
            self._record_user_entry_trace(exact, "exact")
            return exact

        expected_entry = self._find_entry_in_text(cleaned_text, self._by_first_py.get(expected_py, []))
        if expected_entry is not None:
            self._record_user_entry_trace(expected_entry, "expected_text")
            return expected_entry

        known_entry = self._find_entry_in_text(cleaned_text, (self._by_word[word] for word in self._known_words))
        if known_entry is not None:
            self._record_user_entry_trace(known_entry, "known_text")
            return known_entry

        return None

    def _record_user_entry_trace(self, entry: IdiomEntry, source: str) -> None:
        self._last_trace.update(
            {
                "idiom_user_match_source": source,
                "idiom_user_word": entry.word,
                "idiom_user_first_py": entry.first_py,
                "idiom_user_last_py": entry.last_py,
            }
        )

    @staticmethod
    def _find_entry_in_text(cleaned_text: str, entries: Iterable[IdiomEntry]) -> IdiomEntry | None:
        best: tuple[int, int, IdiomEntry] | None = None
        for entry in entries:
            index = cleaned_text.find(entry.word)
            if index < 0:
                continue
            candidate = (index, -len(entry.word), entry)
            if best is None or candidate[:2] < best[:2]:
                best = candidate
        return best[2] if best is not None else None

    def _find_reply(self, first_py: str, used_words: set[str], difficulty: str) -> IdiomEntry | None:
        reply_index = self._bot_by_first_py_by_difficulty.get(
            normalize_robot_difficulty(difficulty),
            self._bot_by_first_py_by_difficulty[self._default_robot_difficulty],
        )
        for entry in reply_index.get(first_py, []):
            if entry.word not in used_words:
                return entry
        return None

    def _select_robot_reply_pool(self, difficulty: str, reply_limit: int | None) -> list[IdiomEntry]:
        playable = [entry for entry in self._idioms if entry.word in self._playable_words]
        if reply_limit is None:
            normalized_difficulty = normalize_robot_difficulty(difficulty)
            reply_limit = _ROBOT_REPLY_LIMITS.get(normalized_difficulty, _ROBOT_REPLY_LIMITS["normal"])
        if reply_limit is None:
            return playable
        return playable[: max(0, int(reply_limit))]

    @staticmethod
    def _build_reply_index(entries: Iterable[IdiomEntry]) -> dict[str, list[IdiomEntry]]:
        reply_index: dict[str, list[IdiomEntry]] = defaultdict(list)
        for entry in entries:
            reply_index[entry.first_py].append(entry)
        return reply_index

    def _judge_unknown_decision(
        self, cleaned_text: str, *, expected_py: str
    ) -> IdiomJudgeDecision | None:
        if (
            not cleaned_text
            or _NOISE_ONLY_RE.fullmatch(cleaned_text) is not None
            or self._judge_unknown_idiom is None
        ):
            return None
        self._last_trace["idiom_llm_judge_used"] = True
        decision = self._judge_unknown_idiom(cleaned_text, expected_py)
        if decision is not None:
            self._last_trace["idiom_llm_judge_confidence"] = float(decision.confidence)
            self._last_trace["idiom_llm_intent"] = str(decision.intent or "unknown")
            self._last_trace["idiom_llm_matches_expected_pinyin"] = bool(
                decision.matches_expected_pinyin
            )
        return decision

    def _entry_from_judge_decision(
        self, decision: IdiomJudgeDecision, *, expected_py: str
    ) -> IdiomEntry | None:
        if not decision.is_idiom:
            return None
        if float(decision.confidence) < self._judge_min_confidence:
            return None
        word = clean_idiom_text(decision.word)
        first_py = normalize_pinyin(decision.first_py)
        last_py = normalize_pinyin(decision.last_py)
        if _FOUR_HAN_RE.fullmatch(word) is None or first_py != expected_py or not last_py:
            return None
        entry = IdiomEntry(word=word, first_py=first_py, last_py=last_py)
        self._record_user_entry_trace(entry, "llm_judge")
        return entry

    def _switch_difficulty(
        self,
        device_id: str,
        state: IdiomGameState,
        difficulty: str,
        *,
        llm_judge_used: bool,
    ) -> str:
        self._last_trace.update(
            {
                "idiom_event": "difficulty_switch",
                "idiom_robot_difficulty": difficulty,
                "idiom_target_user_turns": self._target_user_turns_for(difficulty),
                "idiom_valid_user_turns": 0,
                "idiom_llm_judge_used": llm_judge_used,
            }
        )
        self._store.save(
            device_id,
            IdiomGameState(
                expected_py=state.expected_py,
                used_words=set(state.used_words),
                valid_user_turns=0,
                robot_difficulty=difficulty,
                last_robot_word=state.last_robot_word,
            ),
        )
        return (
            f"已切换到{robot_difficulty_label(difficulty)}模式，"
            f"连续接对轮数已重新计算。轮到你啦，要接“{state.expected_py}”。"
        )

    def _target_user_turns_for(self, difficulty: str) -> int:
        if self._target_user_turns_override:
            return self._target_user_turns_override
        return robot_difficulty_target_turns(difficulty)
