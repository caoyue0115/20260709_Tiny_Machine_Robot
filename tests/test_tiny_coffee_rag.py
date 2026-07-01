from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from tests._stubs import install_dependency_stubs

install_dependency_stubs()

from src.rag import ingest
from src.rag import retriever


def test_coffee_question_detection_uses_coffee_words() -> None:
    assert retriever.is_coffee_question("手冲咖啡为什么会偏酸")
    assert retriever.is_coffee_question("拿铁和卡布奇诺有什么区别")
    assert not retriever.is_coffee_question("今天天气怎么样")


def test_old_domain_rag_entrypoints_are_not_exposed() -> None:
    legacy_question_checker = "is_" + "buddhist_question"
    legacy_ingester = "ingest_" + "buddhism_docs"
    assert not hasattr(retriever, legacy_question_checker)
    assert not hasattr(ingest, legacy_ingester)


def test_index_paths_are_coffee_specific(tmp_path: Path) -> None:
    with mock.patch.object(retriever.settings, "indices_dir", tmp_path):
        meta_file, faiss_file = retriever.index_paths()

    assert meta_file == tmp_path / "coffee.meta.json"
    assert faiss_file == tmp_path / "coffee.faiss"


def test_should_ingest_general_coffee_markdown_files() -> None:
    assert ingest.should_ingest_file(Path("CF01_coffee_basics.md"))
    assert ingest.should_ingest_file(Path("beans.txt"))
    assert not ingest.should_ingest_file(Path("raw.pdf"))


def test_collect_doc_units_reads_coffee_docs(tmp_path: Path) -> None:
    (tmp_path / "CF01_coffee_basics.md").write_text("# 咖啡豆\n阿拉比卡通常香气更细腻。", encoding="utf-8")
    (tmp_path / "notes.pdf").write_bytes(b"%PDF-1.4")

    units = ingest.collect_doc_units(tmp_path)

    assert [unit["source_title"] for unit in units] == ["CF01_coffee_basics.md"]
    assert "阿拉比卡" in units[0]["text"]


def test_ingest_summary_is_coffee_specific(tmp_path: Path) -> None:
    (tmp_path / "CF01_coffee_basics.md").write_text("# 咖啡豆\n阿拉比卡通常香气更细腻。", encoding="utf-8")
    index_dir = tmp_path / "indices"

    with mock.patch.object(ingest.settings, "kb_dir", tmp_path), mock.patch.object(
        ingest.settings, "indices_dir", index_dir
    ), mock.patch.object(ingest.settings, "chunk_size", 80), mock.patch.object(
        ingest.settings, "chunk_overlap", 10
    ):
        summary = ingest.ingest_coffee_docs()

    assert summary["domain"] == "coffee"
    assert summary["docs"] == 1
    assert Path(summary["meta_file"]).name == "coffee.meta.json"
    meta = json.loads((index_dir / "coffee.meta.json").read_text(encoding="utf-8"))
    assert meta["domain"] == "coffee"
