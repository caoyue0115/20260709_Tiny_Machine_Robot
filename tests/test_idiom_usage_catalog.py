from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_usage_catalog_covers_the_full_idiom_lexicon() -> None:
    idioms = json.loads((ROOT / "src" / "voice_skills" / "idioms.json").read_text(encoding="utf-8"))
    catalog = json.loads(
        (ROOT / "src" / "voice_skills" / "idiom_usage.json").read_text(encoding="utf-8")
    )
    entries = catalog["entries"]

    assert set(entries) == {item["word"] for item in idioms}
    assert {entry["usage_tier"] for entry in entries.values()} == {"A", "B", "C"}
    assert all(0 <= float(entry["common_score"]) <= 100 for entry in entries.values())


def test_usage_report_matches_catalog_and_keeps_robot_pool_conservative() -> None:
    catalog = json.loads(
        (ROOT / "src" / "voice_skills" / "idiom_usage.json").read_text(encoding="utf-8")
    )
    report = json.loads(
        (ROOT / "data" / "idiom_usage" / "report.json").read_text(encoding="utf-8")
    )
    counts = Counter(entry["usage_tier"] for entry in catalog["entries"].values())

    assert dict(sorted(counts.items())) == report["tier_counts"]
    assert report["robot_pool_size"] == counts["A"] + counts["B"]
    assert 4000 <= report["robot_pool_size"] <= 7000
    assert report["user_ending_reply_coverage"] >= 0.98


def test_manual_blacklist_overrides_robot_usage_tier() -> None:
    catalog = json.loads(
        (ROOT / "src" / "voice_skills" / "idiom_usage.json").read_text(encoding="utf-8")
    )["entries"]
    overrides = json.loads(
        (ROOT / "config" / "idiom_usage_overrides.json").read_text(encoding="utf-8")
    )["words"]

    assert len(overrides) >= 20
    assert all(catalog[word]["usage_tier"] == "C" for word in overrides if word in catalog)
    assert catalog["画龙点睛"]["usage_tier"] == "A"
    assert catalog["阿党比周"]["usage_tier"] == "C"


def test_runtime_loader_joins_usage_tiers_and_scores() -> None:
    from src.voice_skills.idiom_game import load_default_idioms

    entries = {entry.word: entry for entry in load_default_idioms()}

    assert entries["画龙点睛"].usage_tier == "A"
    assert entries["画龙点睛"].common_score > entries["阿党比周"].common_score
    assert entries["一槌定音"].usage_tier == "C"
