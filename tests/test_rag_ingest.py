from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._stubs import install_dependency_stubs

install_dependency_stubs()

from src.rag import ingest


class RagIngestTests(unittest.TestCase):
    def test_should_ingest_markdown_and_text_files(self) -> None:
        self.assertTrue(ingest.should_ingest_file(Path("CF01_coffee_basics.md")))
        self.assertTrue(ingest.should_ingest_file(Path("beans.txt")))
        self.assertFalse(ingest.should_ingest_file(Path("raw.pdf")))

    def test_collect_doc_units_reads_text_coffee_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_dir = Path(tmpdir)
            (kb_dir / "CF01_coffee_basics.md").write_text("# 咖啡豆\n阿拉比卡通常香气更细腻。", encoding="utf-8")
            (kb_dir / "beans.txt").write_text("水洗处理通常让酸质和干净度更突出。", encoding="utf-8")
            (kb_dir / "raw.pdf").write_bytes(b"%PDF-1.4\n")

            units = ingest.collect_doc_units(kb_dir)

        titles = sorted(unit["source_title"] for unit in units)
        self.assertEqual(titles, ["CF01_coffee_basics.md", "beans.txt"])


if __name__ == "__main__":
    unittest.main()
