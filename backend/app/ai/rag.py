"""Knowledge-base retrieval (RAG) over original awareness notes in app/ai/knowledge/*.md.

Embeddings: a deterministic local *hashing* embedder (word unigrams + bigrams hashed into
512 dims, L2-normalised). It needs no download or API key, so RAG works offline. It is a
lexical embedder, not a neural one — swap `embed()` for a sentence-transformer or provider
embedding in production. Vector store: ChromaDB (persistent) when available, else an
in-memory cosine store with the same interface.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)
KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
DIM = 512
MIN_SIMILARITY = 0.18  # below this, the answer is "not in knowledge base"
STOPWORDS = set("a an the and or of to in on for is are be it this that with as by at from your you i we "
                "what how why when do does can should my our if not".split())


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS and len(w) > 1]


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    toks = [_stem(t) for t in tokens(text)]
    feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
    for f in feats:
        h = int(hashlib.md5(f.encode()).hexdigest(), 16)
        vec[h % DIM] += 1.0 if "_" not in f else 0.5
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@dataclass
class Chunk:
    id: str
    doc_slug: str
    title: str
    text: str


def load_documents() -> list[dict]:
    docs = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        title = content.splitlines()[0].lstrip("# ").strip()
        docs.append({"slug": path.stem, "title": title, "content_md": content})
    return docs


def chunk_document(slug: str, title: str, content: str, max_chars: int = 700) -> list[Chunk]:
    """Split on headings/paragraphs, then pack paragraphs up to max_chars."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    chunks, buf = [], ""
    for p in paras:
        if buf and len(buf) + len(p) > max_chars:
            chunks.append(buf)
            buf = ""
        buf = f"{buf}\n\n{p}".strip()
    if buf:
        chunks.append(buf)
    return [Chunk(f"{slug}-{i}", slug, title, c) for i, c in enumerate(chunks)]


class MemoryStore:
    backend = "memory"

    def __init__(self) -> None:
        self.items: list[tuple[Chunk, list[float]]] = []

    def reset(self, chunks: list[Chunk]) -> None:
        self.items = [(c, embed(c.title + " " + c.text)) for c in chunks]

    def search(self, query: str, k: int) -> list[tuple[Chunk, float]]:
        q = embed(query)
        scored = [(c, sum(a * b for a, b in zip(q, v))) for c, v in self.items]
        return sorted(scored, key=lambda x: -x[1])[:k]


class ChromaStore:
    backend = "chroma"

    def __init__(self, path: str) -> None:
        import chromadb  # imported lazily so the app still runs if chromadb is unavailable

        self.client = chromadb.PersistentClient(path=path)
        self.col = None

    def reset(self, chunks: list[Chunk]) -> None:
        try:
            self.client.delete_collection("phishguard-kb")
        except Exception:  # noqa: BLE001 - collection may not exist yet
            pass
        self.col = self.client.create_collection("phishguard-kb", embedding_function=None,
                                                 metadata={"hnsw:space": "cosine"})
        self.col.add(ids=[c.id for c in chunks], embeddings=[embed(c.title + " " + c.text) for c in chunks],
                     documents=[c.text for c in chunks],
                     metadatas=[{"slug": c.doc_slug, "title": c.title} for c in chunks])

    def search(self, query: str, k: int) -> list[tuple[Chunk, float]]:
        res = self.col.query(query_embeddings=[embed(query)], n_results=k)
        out = []
        for cid, doc, meta, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0],
                                        res["distances"][0]):
            out.append((Chunk(cid, meta["slug"], meta["title"], doc), 1.0 - dist))  # cosine distance -> sim
        return out


_store = None


def get_store():
    """Build the index once per process (from the markdown files)."""
    global _store
    if _store is None:
        s = get_settings()
        chunks = [c for d in load_documents() for c in chunk_document(d["slug"], d["title"], d["content_md"])]
        store = None
        if s.vector_store in ("auto", "chroma"):
            try:
                store = ChromaStore(s.chroma_path)
                store.reset(chunks)
            except Exception as exc:  # noqa: BLE001
                log.warning("chroma_unavailable_falling_back", extra={"error": repr(exc)})
                store = None
        if store is None:
            store = MemoryStore()
            store.reset(chunks)
        _store = store
        log.info("rag_index_built", extra={"backend": store.backend, "chunks": len(chunks)})
    return _store


def retrieve(query: str, k: int = 3) -> list[dict]:
    hits = get_store().search(query, k)
    return [{"id": c.id, "slug": c.doc_slug, "title": c.title, "text": c.text, "similarity": round(sim, 3)}
            for c, sim in hits]
