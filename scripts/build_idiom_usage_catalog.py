from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import math
import re
import time
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
EDUCATION_ENDPOINT = "https://nclds.xmu.edu.cn/gedataywjy"
EDUCATION_SOURCE_URL = "https://nclds.xmu.edu.cn/ywjy"
SCHOOL_COMMON_SOURCE_URL = (
    "https://www.plecoforums.com/threads/"
    "%E5%B0%8F%E5%AD%A6%E7%94%9F%E5%B8%B8%E7%94%A8%E6%88%90%E8%AF%AD%E5%A4%A7%E5%85%A8-a-huge-list-of-cheng-yu-flashcards.5366/"
)
SCHOOL_COMMON_DOWNLOAD_URL = (
    "https://www.plecoforums.com/download/xiaoxuechengyudaquan-txt.2172/"
)
MODERN_COMMON_SOURCE_URL = (
    "https://www.moe.gov.cn/ewebeditor/uploadfile/2015/01/13/20150113085920115.pdf"
)
MODERN_COMMON_TRANSCRIPTION_URL = (
    "https://gist.githubusercontent.com/zenwalk/02df86ef16f555f8f6800564d98208ca/raw/"
)
SUBTLEX_SOURCE_URL = (
    "https://www.ugent.be/plone_portal/pp/experimentele-psychologie/en/research/"
    "documents/subtlexch/subtlexchwf.zip"
)
BCC_SOURCE_URLS = {
    "multi": "https://bcc.blcu.edu.cn/api/datasets/multi_domain_total_word_freq.txt/download",
    "news": "https://bcc.blcu.edu.cn/api/datasets/news_total_word_freq.txt/download",
    "literature": "https://bcc.blcu.edu.cn/api/datasets/literature_word_freq.txt/download",
    "dialogue": "https://bcc.blcu.edu.cn/api/datasets/dialogue_word_freq.txt/download",
}
BCC_FILENAMES = {
    "multi": "multi_domain_total_word_freq.txt",
    "news": "news_total_word_freq.txt",
    "literature": "literature_word_freq.txt",
    "dialogue": "dialogue_word_freq.txt",
}
EDUCATION_LEVEL_MARKERS = {
    "第一学段": 1,
    "第二学段": 2,
    "第三学段": 3,
    "第四学段": 4,
}
CARD_RE = re.compile(
    r"<h5\s+class=['\"]card-title['\"]>(?P<word>.*?)</h5>\s*<p>(?P<body>.*?)</p>",
    re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "TinyMachineRobot-IdiomCatalog/1.0"},
    )
    with urllib.request.urlopen(request, timeout=120.0) as response:
        return response.read()


def _download_file(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_download(url))


def _download_zip_member(url: str, member_name: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(_download(url))) as archive:
        path.write_bytes(archive.read(member_name))


def fetch_corpus_sources(args: argparse.Namespace) -> None:
    if not args.modern_common.exists():
        _download_file(MODERN_COMMON_TRANSCRIPTION_URL, args.modern_common)
    if not args.school_common.exists():
        _download_file(SCHOOL_COMMON_DOWNLOAD_URL, args.school_common)
    for channel, filename in BCC_FILENAMES.items():
        path = args.bcc_dir / filename
        if not path.exists():
            _download_zip_member(BCC_SOURCE_URLS[channel], filename, path)
    if not args.subtlex.exists():
        _download_zip_member(SUBTLEX_SOURCE_URL, "SUBTLEX-CH-WF", args.subtlex)


def parse_education_response(response_html: str, requested_words: Iterable[str]) -> dict[str, int | None]:
    requested = list(requested_words)
    levels: dict[str, int | None] = {word: None for word in requested}
    seen: set[str] = set()
    for match in CARD_RE.finditer(response_html):
        word = html.unescape(TAG_RE.sub("", match.group("word"))).strip()
        if word not in levels:
            continue
        body = html.unescape(TAG_RE.sub("", match.group("body")))
        level = next((value for marker, value in EDUCATION_LEVEL_MARKERS.items() if marker in body), None)
        levels[word] = level
        seen.add(word)
    missing = set(requested) - seen
    if missing:
        raise ValueError(f"education_response_missing_words:{','.join(sorted(missing))}")
    return levels


def _post_education_batch(words: list[str], *, timeout_seconds: float = 30.0) -> dict[str, int | None]:
    payload = urllib.parse.urlencode({"word": ",".join(words)}).encode("utf-8")
    request = urllib.request.Request(
        EDUCATION_ENDPOINT,
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "TinyMachineRobot-IdiomCatalog/1.0 (research cache builder)",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        response_html = response.read().decode("utf-8")
    return parse_education_response(response_html, words)


def fetch_education_levels(
    words: Iterable[str],
    cache_path: Path,
    *,
    batch_size: int = 30,
    delay_seconds: float = 0.25,
    retries: int = 3,
    max_new_words: int | None = None,
) -> dict[str, int | None]:
    ordered_words = list(dict.fromkeys(words))
    if cache_path.exists():
        cached_payload = json.loads(cache_path.read_text(encoding="utf-8"))
        levels = dict(cached_payload.get("levels") or {})
    else:
        levels = {}
    missing = [word for word in ordered_words if word not in levels]
    if max_new_words is not None:
        missing = missing[: max(0, int(max_new_words))]
    total_batches = math.ceil(len(missing) / batch_size) if missing else 0
    for batch_index in range(total_batches):
        batch = missing[batch_index * batch_size : (batch_index + 1) * batch_size]
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                levels.update(_post_education_batch(batch))
                last_error = None
                break
            except Exception as exc:  # pragma: no cover - exercised only by live endpoint failures
                last_error = exc
                time.sleep(delay_seconds * (attempt + 1))
        if last_error is not None:
            raise RuntimeError(f"education_query_failed_batch:{batch_index + 1}") from last_error
        _write_json(
            cache_path,
            {
                "source": EDUCATION_SOURCE_URL,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "levels": levels,
            },
        )
        if (batch_index + 1) % 20 == 0 or batch_index + 1 == total_batches:
            print(f"education batches {batch_index + 1}/{total_batches} cached={len(levels)}", flush=True)
        if batch_index + 1 < total_batches:
            time.sleep(delay_seconds)
    return {word: levels.get(word) for word in ordered_words}


def load_education_levels(path: Path, words: Iterable[str]) -> dict[str, int | None]:
    if not path.exists():
        return {word: None for word in words}
    payload = json.loads(path.read_text(encoding="utf-8"))
    cached = dict(payload.get("levels") or {})
    return {word: cached.get(word) for word in words}


def load_school_common_words(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if re.fullmatch(r"[\u3400-\u9fff]{4}", line.strip())
    }


def load_modern_common_ranks(path: Path) -> dict[str, int]:
    ranks: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        parts = line.rstrip().split("\t")
        if len(parts) < 3 or not parts[-1].isdigit():
            continue
        word = parts[0].strip()
        rank = int(parts[-1])
        if word:
            ranks[word] = min(rank, ranks.get(word, rank))
    return ranks


def load_bcc_counts(path: Path, target_words: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    with path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            word = str(row.get("token") or "")
            if word in target_words:
                counts[word] = int(row.get("count") or 0)
    return counts


def load_subtlex_counts(path: Path, target_words: set[str]) -> dict[str, dict[str, float | int]]:
    counts: dict[str, dict[str, float | int]] = {}
    with path.open(encoding="gb18030") as source:
        for line_number, line in enumerate(source):
            if line_number < 3:
                continue
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) < 7 or parts[0] not in target_words:
                continue
            counts[parts[0]] = {
                "count": int(parts[1]),
                "per_million": float(parts[2]),
                "context_pct": float(parts[5]),
            }
    return counts


def classify_usage(
    *,
    education_level: int | None,
    modern_common_rank: int | None,
    bcc_counts: dict[str, int],
    subtlex_count: int,
    school_common: bool = False,
    forced_tier: str | None = None,
) -> dict[str, object]:
    normalized_forced_tier = str(forced_tier or "").strip().upper()
    bcc_hits = sum(int(count) >= 2 for count in bcc_counts.values())
    subtlex_hit = int(subtlex_count) >= 2
    source_hits = bcc_hits + int(subtlex_hit)
    daily_hit = int(bcc_counts.get("dialogue", 0)) >= 10 or int(subtlex_count) >= 10

    score = 0.0
    if education_level is not None:
        score = max(score, {1: 98.0, 2: 94.0, 3: 86.0, 4: 72.0}[int(education_level)])
    if modern_common_rank is not None:
        rank_ratio = min(1.0, max(0.0, (int(modern_common_rank) - 1) / 56007.0))
        score += 25.0 + (25.0 * (1.0 - rank_ratio))
    if school_common:
        score += 20.0
    score += 7.0 * bcc_hits
    score += 10.0 if subtlex_hit else 0.0
    if daily_hit:
        score += 5.0

    if normalized_forced_tier in {"A", "B", "C"}:
        usage_tier = normalized_forced_tier
        manual_override = True
    else:
        manual_override = False
        if education_level in {1, 2, 3}:
            usage_tier = "A"
        elif school_common and source_hits >= 2:
            usage_tier = "A"
        elif (
            modern_common_rank is not None
            and int(modern_common_rank) <= 40000
            and source_hits >= 3
        ):
            usage_tier = "A"
        elif source_hits >= 4 and daily_hit:
            usage_tier = "A"
        elif education_level == 4:
            usage_tier = "B"
        elif school_common:
            usage_tier = "B"
        elif modern_common_rank is not None and int(modern_common_rank) <= 30000:
            usage_tier = "B"
        elif (
            modern_common_rank is not None
            and int(modern_common_rank) <= 45000
            and source_hits >= 1
        ):
            usage_tier = "B"
        elif source_hits >= 3 and sum(int(value) for value in bcc_counts.values()) >= 50:
            usage_tier = "B"
        elif source_hits >= 2 and (
            daily_hit or sum(int(value) for value in bcc_counts.values()) >= 100
        ):
            usage_tier = "B"
        elif int(bcc_counts.get("dialogue", 0)) >= 10 or int(subtlex_count) >= 5:
            usage_tier = "B"
        else:
            usage_tier = "C"

    if usage_tier == "A":
        score = max(70.0, score)
    elif usage_tier == "B":
        score = min(69.0, max(40.0, score))
    else:
        score = min(39.0, score)
    return {
        "usage_tier": usage_tier,
        "common_score": round(min(100.0, score), 1),
        "source_hits": source_hits,
        "manual_override": manual_override,
    }


def _load_overrides(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload.get("words") or {})


def build_catalog(args: argparse.Namespace) -> tuple[dict[str, object], dict[str, object]]:
    idioms = json.loads(args.idioms.read_text(encoding="utf-8"))
    words = [str(item["word"]) for item in idioms]
    target_words = set(words)
    if args.fetch_education:
        education_levels = fetch_education_levels(
            words,
            args.education_cache,
            delay_seconds=args.education_delay,
            max_new_words=args.education_query_limit,
        )
    else:
        education_levels = load_education_levels(args.education_cache, words)
    school_common_words = load_school_common_words(args.school_common)
    modern_ranks = load_modern_common_ranks(args.modern_common)
    bcc_by_channel = {
        channel: load_bcc_counts(args.bcc_dir / filename, target_words)
        for channel, filename in BCC_FILENAMES.items()
    }
    subtlex = load_subtlex_counts(args.subtlex, target_words)
    overrides = _load_overrides(args.overrides)

    entries: dict[str, dict[str, object]] = {}
    tier_counts: Counter[str] = Counter()
    for word in words:
        bcc_counts = {
            channel: int(channel_counts.get(word, 0))
            for channel, channel_counts in bcc_by_channel.items()
        }
        override = overrides.get(word) or {}
        classification = classify_usage(
            education_level=education_levels.get(word),
            modern_common_rank=modern_ranks.get(word),
            bcc_counts=bcc_counts,
            subtlex_count=int((subtlex.get(word) or {}).get("count") or 0),
            school_common=word in school_common_words,
            forced_tier=override.get("tier"),
        )
        tier_counts[str(classification["usage_tier"])] += 1
        entry = {
            "usage_tier": classification["usage_tier"],
            "common_score": classification["common_score"],
        }
        entries[word] = entry

    robot_first_pinyin = {
        str(item["first_py"])
        for item in idioms
        if entries[str(item["word"])]["usage_tier"] in {"A", "B"}
    }
    supported_user_endings = sum(
        str(item["last_py"]) in robot_first_pinyin
        for item in idioms
    )
    report = {
        "generated_on": date.today().isoformat(),
        "total_idioms": len(words),
        "tier_counts": dict(sorted(tier_counts.items())),
        "robot_pool_size": tier_counts["A"] + tier_counts["B"],
        "robot_start_pinyin_count": len(robot_first_pinyin),
        "user_endings_with_robot_reply": supported_user_endings,
        "user_ending_reply_coverage": round(supported_user_endings / len(words), 4),
        "education_matches": sum(level is not None for level in education_levels.values()),
        "school_common_matches": sum(word in school_common_words for word in words),
        "modern_common_matches": sum(word in modern_ranks for word in words),
        "bcc_matches": {
            channel: len(counts) for channel, counts in bcc_by_channel.items()
        },
        "subtlex_matches": len(subtlex),
        "manual_overrides": sum(bool((overrides.get(word) or {}).get("tier")) for word in words),
    }
    catalog = {
        "version": 1,
        "generated_on": report["generated_on"],
        "method": "education-school-modern-common-bcc-subtlex-v1",
        "entries": entries,
    }
    return catalog, report


def build_source_manifest(args: argparse.Namespace) -> dict[str, object]:
    files = {
        "modern_common_transcription": args.modern_common,
        "school_common": args.school_common,
        "bcc_multi": args.bcc_dir / BCC_FILENAMES["multi"],
        "bcc_news": args.bcc_dir / BCC_FILENAMES["news"],
        "bcc_literature": args.bcc_dir / BCC_FILENAMES["literature"],
        "bcc_dialogue": args.bcc_dir / BCC_FILENAMES["dialogue"],
        "subtlex": args.subtlex,
    }
    if args.education_cache.exists():
        files["education_cache"] = args.education_cache
    return {
        "generated_on": date.today().isoformat(),
        "sources": {
            "education": EDUCATION_SOURCE_URL,
            "school_common": SCHOOL_COMMON_SOURCE_URL,
            "standardized_variants": (
                "https://www.moe.gov.cn/jyb_sjzl/ziliao/A19/201001/"
                "t20100115_75687.html"
            ),
            "modern_common_official": MODERN_COMMON_SOURCE_URL,
            "modern_common_transcription": MODERN_COMMON_TRANSCRIPTION_URL,
            "bcc": BCC_SOURCE_URLS,
            "subtlex": SUBTLEX_SOURCE_URL,
        },
        "files": {
            name: {"sha256": _sha256(path), "size_bytes": path.stat().st_size}
            for name, path in files.items()
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build evidence-backed idiom usage tiers.")
    parser.add_argument("--idioms", type=Path, default=ROOT / "src" / "voice_skills" / "idioms.json")
    parser.add_argument(
        "--education-cache",
        type=Path,
        default=ROOT / "tmp" / "idiom_sources" / "education_levels.json",
    )
    parser.add_argument("--education-delay", type=float, default=0.25)
    parser.add_argument(
        "--education-query-limit",
        type=int,
        default=300,
        help="Maximum new words to query per run; the public endpoint enforces a daily cap.",
    )
    parser.add_argument(
        "--fetch-education",
        action="store_true",
        help="Incrementally query the rate-limited education-list endpoint.",
    )
    parser.add_argument(
        "--download-sources",
        action="store_true",
        help="Download missing public corpus files before building.",
    )
    parser.add_argument(
        "--school-common",
        type=Path,
        default=ROOT / "tmp" / "idiom_sources" / "school_common_idioms.txt",
    )
    parser.add_argument(
        "--modern-common",
        type=Path,
        default=ROOT / "tmp" / "idiom_sources" / "modern_chinese_common_words.txt",
    )
    parser.add_argument(
        "--bcc-dir",
        type=Path,
        default=ROOT / "tmp" / "idiom_sources" / "bcc" / "raw",
    )
    parser.add_argument(
        "--subtlex",
        type=Path,
        default=ROOT / "tmp" / "idiom_sources" / "subtlex" / "raw" / "SUBTLEX-CH-WF",
    )
    parser.add_argument(
        "--overrides",
        type=Path,
        default=ROOT / "config" / "idiom_usage_overrides.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "src" / "voice_skills" / "idiom_usage.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "data" / "idiom_usage" / "report.json",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data" / "idiom_usage" / "sources.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.download_sources:
        fetch_corpus_sources(args)
    catalog, report = build_catalog(args)
    _write_json(args.output, catalog)
    _write_json(args.report, report)
    _write_json(args.manifest, build_source_manifest(args))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
