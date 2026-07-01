from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.rag.retriever import (
    HashingEmbedder,
    clean_text,
    faiss,
    index_paths,
    split_text,
    to_float32_matrix,
    tokenize_zh,
)
from src.settings import settings

ALLOWED_EXTS = {".md", ".txt"}


def should_ingest_file(fp: Path) -> bool:
    return fp.suffix.lower() in ALLOWED_EXTS


def collect_doc_units(base: Path | None = None) -> list[dict[str, Any]]:
    base = base or settings.kb_dir
    units: list[dict[str, Any]] = []
    for fp in sorted(base.rglob("*")):
        if not fp.is_file() or not should_ingest_file(fp):
            continue
        text = clean_text(fp.read_text(encoding="utf-8", errors="ignore"))
        if text:
            units.append({"source_file": str(fp), "source_title": fp.name, "page_no": None, "text": text})
    return units


def ingest_coffee_docs() -> dict[str, Any]:
    units = collect_doc_units()
    if not units:
        raise RuntimeError(f"no docs found under {settings.kb_dir}")

    chunks: list[dict[str, Any]] = []
    for unit in units:
        for i, part in enumerate(split_text(unit["text"], settings.chunk_size, settings.chunk_overlap)):
            chunks.append(
                {
                    "chunk_id": len(chunks) + 1,
                    "source_file": unit["source_file"],
                    "source_title": unit["source_title"],
                    "page_no": unit["page_no"],
                    "part": i,
                    "text": part,
                }
            )

    corpus = [x["text"] for x in chunks]
    tokenized = [tokenize_zh(x) for x in corpus]
    vecs = to_float32_matrix(HashingEmbedder(dim=settings.embedding_dim).encode(corpus, normalize_embeddings=True))
    index = faiss.IndexFlatIP(vecs.shape[1])
    index.add(vecs)

    settings.indices_dir.mkdir(parents=True, exist_ok=True)
    meta_file, faiss_file = index_paths()
    meta_file.write_text(
        json.dumps(
            {
                "domain": "coffee",
                "chunks": chunks,
                "tokenized_corpus": tokenized,
                "chunk_size": settings.chunk_size,
                "chunk_overlap": settings.chunk_overlap,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    faiss.write_index(index, str(faiss_file))
    return {
        "domain": "coffee",
        "docs": len({x["source_file"] for x in chunks}),
        "chunks": len(chunks),
        "meta_file": str(meta_file),
        "faiss_file": str(faiss_file),
    }


def ingest_buddhism_docs() -> dict[str, Any]:
    return ingest_coffee_docs()
