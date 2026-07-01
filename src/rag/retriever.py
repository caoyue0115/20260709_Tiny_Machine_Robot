from __future__ import annotations

import hashlib
import json
import pickle
import re
from pathlib import Path
from typing import Any

import numpy as np

try:
    import faiss
except ModuleNotFoundError:

    class _FallbackIndexFlatIP:
        def __init__(self, dim: int) -> None:
            self.dim = dim
            self.vectors = np.empty((0, dim), dtype=np.float32)

        def add(self, vectors: np.ndarray) -> None:
            arr = np.asarray(vectors, dtype=np.float32)
            if arr.ndim != 2 or arr.shape[1] != self.dim:
                raise ValueError("index vectors must match embedding dimension")
            self.vectors = np.vstack([self.vectors, arr])

        def search(self, queries: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
            q = np.asarray(queries, dtype=np.float32)
            if q.ndim != 2 or q.shape[1] != self.dim:
                raise ValueError("query vectors must match embedding dimension")
            if self.vectors.size == 0:
                scores = np.full((q.shape[0], k), -np.inf, dtype=np.float32)
                ids = np.full((q.shape[0], k), -1, dtype=np.int64)
                return scores, ids

            raw_scores = q @ self.vectors.T
            take = min(k, self.vectors.shape[0])
            ids = np.argsort(-raw_scores, axis=1)[:, :take]
            scores = np.take_along_axis(raw_scores, ids, axis=1)
            if take < k:
                pad_scores = np.full((q.shape[0], k - take), -np.inf, dtype=np.float32)
                pad_ids = np.full((q.shape[0], k - take), -1, dtype=np.int64)
                scores = np.concatenate([scores, pad_scores], axis=1)
                ids = np.concatenate([ids, pad_ids], axis=1)
            return scores.astype(np.float32), ids.astype(np.int64)

    class _FallbackFaiss:
        IndexFlatIP = _FallbackIndexFlatIP

        @staticmethod
        def write_index(index: _FallbackIndexFlatIP, path: str) -> None:
            with open(path, "wb") as fh:
                pickle.dump({"dim": index.dim, "vectors": index.vectors}, fh)

        @staticmethod
        def read_index(path: str) -> _FallbackIndexFlatIP:
            with open(path, "rb") as fh:
                payload = pickle.load(fh)
            index = _FallbackIndexFlatIP(int(payload["dim"]))
            index.vectors = np.asarray(payload["vectors"], dtype=np.float32)
            return index

    faiss = _FallbackFaiss()

try:
    import jieba
except ModuleNotFoundError:

    class _JiebaFallback:
        @staticmethod
        def cut(text: str) -> list[str]:
            return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]|[^\s]", text)

    jieba = _JiebaFallback()

try:
    from rank_bm25 import BM25Okapi
except ModuleNotFoundError:

    class BM25Okapi:
        def __init__(self, tokenized_corpus: list[list[str]]) -> None:
            self.tokenized_corpus = [list(doc) for doc in tokenized_corpus]

        def get_scores(self, tokens: list[str]) -> np.ndarray:
            query_terms = set(tokens)
            scores = [sum(doc.count(term) for term in query_terms) for doc in self.tokenized_corpus]
            return np.asarray(scores, dtype=np.float32)

from src.settings import settings

COFFEE_KEYWORDS = [
    "coffee",
    "coffee bean",
    "coffee beans",
    "hand brew",
    "hand-brew",
    "pour over",
    "espresso",
    "latte",
    "cappuccino",
    "americano",
    "milk coffee",
    "grind",
    "grinding",
    "extraction",
    "roast",
    "roasting",
    "light roast",
    "medium roast",
    "dark roast",
    "flavor",
    "flavour",
    "coffee acidity",
    "acidic coffee",
    "bitter coffee",
    "bitter flavor",
    "coffee sweetness",
    "processing method",
    "water temp",
    "water temperature",
    "brew ratio",
    "咖啡",
    "咖啡豆",
    "豆子",
    "手冲",
    "手冲咖啡",
    "意式",
    "浓缩",
    "意式浓缩",
    "拿铁",
    "卡布奇诺",
    "美式",
    "奶咖",
    "牛奶咖啡",
    "研磨",
    "磨豆",
    "萃取",
    "烘焙",
    "浅烘",
    "浅烘焙",
    "中烘",
    "中度烘焙",
    "深烘",
    "深度烘焙",
    "风味",
    "偏酸",
    "酸味",
    "酸质",
    "偏苦",
    "苦味",
    "甜感",
    "处理法",
    "日晒",
    "水洗",
    "蜜处理",
    "水温",
    "粉水比",
    "冲煮比例",
]


def tokenize_zh(text: str) -> list[str]:
    return [t.strip() for t in jieba.cut(text) if t.strip()]


def clean_text(text: str) -> str:
    lines = [x.strip() for x in text.splitlines()]
    cleaned: list[str] = []
    for line in lines:
        if not line:
            continue
        if re.fullmatch(r"第?\s*\d+\s*页?", line):
            continue
        if re.fullmatch(r"\d{1,4}", line):
            continue
        cleaned.append(line)
    merged = "\n".join(cleaned)
    merged = re.sub(r"\n{3,}", "\n\n", merged)
    merged = re.sub(r"[ \t]{2,}", " ", merged)
    return merged.strip()


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if overlap >= chunk_size:
        overlap = max(0, chunk_size // 5)
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        part = text[start:end].strip()
        if part:
            chunks.append(part)
        if end == len(text):
            break
        start = max(0, end - overlap)
    return chunks


def normalize_inline(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def build_snippet(question: str, text: str, max_chars: int = 60) -> str:
    line = normalize_inline(text)
    if len(line) <= max_chars:
        return line
    q_tokens = [t for t in tokenize_zh(question) if len(t) >= 2]
    hit = None
    for token in q_tokens:
        idx = line.find(token)
        if idx >= 0:
            hit = idx
            break
    if hit is None:
        return line[:max_chars]
    half = max_chars // 2
    start = max(0, hit - half)
    end = min(len(line), start + max_chars)
    start = max(0, end - max_chars)
    return line[start:end]


class HashingEmbedder:
    def __init__(self, dim: int = 768) -> None:
        self.dim = dim

    def encode(self, texts: list[str], normalize_embeddings: bool = True, show_progress_bar: bool = False) -> np.ndarray:
        del show_progress_bar
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            tokens = tokenize_zh(text)
            for token in tokens:
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                idx = int.from_bytes(digest, "big") % self.dim
                out[i, idx] += 1.0
            if normalize_embeddings:
                norm = np.linalg.norm(out[i])
                if norm > 0:
                    out[i] = out[i] / norm
        return out


def to_float32_matrix(vectors: np.ndarray) -> np.ndarray:
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError("embedding output must be 2D matrix")
    return arr


def index_paths() -> tuple[Path, Path]:
    return settings.indices_dir / "coffee.meta.json", settings.indices_dir / "coffee.faiss"


def is_coffee_question(question: str) -> bool:
    normalized = question.casefold()
    return any(keyword.casefold() in normalized for keyword in COFFEE_KEYWORDS)


def retrieve_references(question_text: str, top_k: int | None = None) -> tuple[list[dict[str, Any]], float]:
    if not is_coffee_question(question_text):
        return [], 0.0

    meta_file, faiss_file = index_paths()
    if not meta_file.exists() or not faiss_file.exists():
        raise FileNotFoundError("coffee index not found; run coffee ingest first")
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    index = faiss.read_index(str(faiss_file))
    chunks = meta["chunks"]
    tokenized_corpus = meta["tokenized_corpus"]
    bm25 = BM25Okapi(tokenized_corpus)
    embedder = HashingEmbedder(dim=settings.embedding_dim)

    q_tokens = tokenize_zh(question_text)
    bm_scores = bm25.get_scores(q_tokens)
    bm_top_n = min(max((top_k or settings.top_k) * 3, 8), len(chunks))
    bm_ranked = sorted(enumerate(bm_scores), key=lambda x: x[1], reverse=True)[:bm_top_n]

    q_arr = to_float32_matrix(embedder.encode([question_text], normalize_embeddings=True, show_progress_bar=False))
    vec_top_n = min(max((top_k or settings.top_k) * 3, 8), len(chunks))
    vec_scores, vec_ids = index.search(q_arr, vec_top_n)

    bm_min = float(np.min(bm_scores)) if len(bm_scores) else 0.0
    bm_max = float(np.max(bm_scores)) if len(bm_scores) else 0.0
    bm_norm: dict[int, float] = {}
    for idx, score in bm_ranked:
        bm_norm[idx] = float((score - bm_min) / (bm_max - bm_min)) if bm_max > bm_min else 0.0

    vec_norm: dict[int, float] = {}
    for raw_idx, raw_score in zip(vec_ids[0], vec_scores[0]):
        if raw_idx < 0:
            continue
        vec_norm[int(raw_idx)] = float(max(0.0, min(1.0, (raw_score + 1.0) / 2.0)))

    alpha = settings.bm25_weight
    fused: list[tuple[int, float, float, float]] = []
    for idx in set(bm_norm.keys()) | set(vec_norm.keys()):
        b = bm_norm.get(idx, 0.0)
        v = vec_norm.get(idx, 0.0)
        fused.append((idx, alpha * b + (1.0 - alpha) * v, b, v))
    fused.sort(key=lambda x: (-x[1], x[0]))

    refs: list[dict[str, Any]] = []
    for rank, (idx, score, bm_s, vec_s) in enumerate(fused[: top_k or settings.top_k], start=1):
        ch = chunks[idx]
        refs.append(
            {
                "rank": rank,
                "score": float(score),
                "bm25_score": float(bm_s),
                "vec_score": float(vec_s),
                "source_file": ch["source_file"],
                "source_title": ch["source_title"],
                "page_no": ch["page_no"],
                "chunk_id": ch["chunk_id"],
                "snippet": build_snippet(question_text, ch["text"]),
                "text": ch["text"],
            }
        )
    top_score = float(refs[0]["score"]) if refs else 0.0
    return refs, top_score
