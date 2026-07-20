from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    script_path = ROOT / "scripts" / "build_idiom_usage_catalog.py"
    spec = importlib.util.spec_from_file_location("tests.build_idiom_usage_catalog", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_parse_education_response_keeps_levels_and_missing_words() -> None:
    module = _load_script()
    html = """
    <div class='card'><div class='card-body'>
      <h5 class='card-title'>画龙点睛</h5>
      <p>收录于<font color='blue'>第二学段（小学3—4年级）</font></p>
    </div></div>
    <div class='card'><div class='card-body'>
      <h5 class='card-title'>精卫填海</h5>
      <p>收录于<font color='blue'>第四学段（初中1—3年级）</font></p>
    </div></div>
    <div class='card'><div class='card-body'>
      <h5 class='card-title'>阿党比周</h5>
      <p>不《在义务教育常用词表（草案）》中</p>
    </div></div>
    """

    levels = module.parse_education_response(html, ["画龙点睛", "精卫填海", "阿党比周"])

    assert levels == {"画龙点睛": 2, "精卫填海": 4, "阿党比周": None}


def test_source_parsers_read_school_common_rank_bcc_and_gb18030_subtlex() -> None:
    module = _load_script()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        modern = root / "modern.txt"
        modern.write_text("画龙点睛\thua4\t1200\n阿党比周\ta1\t55000\n", encoding="utf-8")
        school = root / "school.txt"
        school.write_text("//小学生常用成语\n画龙点睛\n临危不俱\n", encoding="utf-8")
        bcc = root / "bcc.csv"
        bcc.write_text("token,count\n画龙点睛,273\n精卫填海,12\n", encoding="utf-8")
        subtlex = root / "subtlex.txt"
        subtlex.write_text(
            '"Total word count: 33,546,516"\t\n'
            '"Context number: 6,243"\t\n'
            "Word\tWCount\tW/million\tlogW\tW-CD\tW-CD%\tlogW-CD\n"
            "画龙点睛\t9\t0.27\t1\t8\t0.13\t0.95\n",
            encoding="gb18030",
        )

        assert module.load_modern_common_ranks(modern) == {"画龙点睛": 1200, "阿党比周": 55000}
        assert module.load_school_common_words(school) == {"画龙点睛", "临危不俱"}
        assert module.load_bcc_counts(bcc, {"画龙点睛", "不存在"}) == {
            "画龙点睛": 273
        }
        assert module.load_subtlex_counts(subtlex, {"画龙点睛", "不存在"}) == {
            "画龙点睛": {"count": 9, "per_million": 0.27, "context_pct": 0.13}
        }


def test_classification_uses_education_multi_source_evidence_and_manual_overrides() -> None:
    module = _load_script()

    primary = module.classify_usage(
        education_level=2,
        modern_common_rank=30000,
        bcc_counts={"multi": 1, "news": 0, "literature": 0, "dialogue": 0},
        subtlex_count=0,
    )
    assert primary["usage_tier"] == "A"

    widely_observed = module.classify_usage(
        education_level=None,
        modern_common_rank=12000,
        bcc_counts={"multi": 80, "news": 200, "literature": 20, "dialogue": 10},
        subtlex_count=8,
    )
    assert widely_observed["usage_tier"] == "A"

    school_and_corpus_supported = module.classify_usage(
        education_level=None,
        modern_common_rank=None,
        bcc_counts={"multi": 20, "news": 20, "literature": 0, "dialogue": 0},
        subtlex_count=0,
        school_common=True,
    )
    assert school_and_corpus_supported["usage_tier"] == "A"

    very_low_rank_without_corpus_support = module.classify_usage(
        education_level=None,
        modern_common_rank=50000,
        bcc_counts={"multi": 0, "news": 2, "literature": 0, "dialogue": 0},
        subtlex_count=0,
    )
    assert very_low_rank_without_corpus_support["usage_tier"] == "C"

    common_rank_without_corpus_support = module.classify_usage(
        education_level=None,
        modern_common_rank=25000,
        bcc_counts={"multi": 0, "news": 0, "literature": 0, "dialogue": 0},
        subtlex_count=0,
    )
    assert common_rank_without_corpus_support["usage_tier"] == "B"

    obscure = module.classify_usage(
        education_level=None,
        modern_common_rank=None,
        bcc_counts={"multi": 0, "news": 0, "literature": 0, "dialogue": 0},
        subtlex_count=0,
    )
    assert obscure["usage_tier"] == "C"

    blacklisted = module.classify_usage(
        education_level=1,
        modern_common_rank=100,
        bcc_counts={"multi": 1000, "news": 1000, "literature": 1000, "dialogue": 1000},
        subtlex_count=1000,
        forced_tier="C",
    )
    assert blacklisted["usage_tier"] == "C"
    assert blacklisted["manual_override"] is True
