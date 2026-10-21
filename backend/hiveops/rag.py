"""Retrieval-augmented generation: parsing, chunking, embeddings and hybrid search.

Embeddings use feature hashing (unigrams + bigrams, signed, log-scaled, L2
normalised). That keeps the platform fully offline and deterministic; swap
``embed`` for a hosted embedding model if you prefer. Search runs on pgvector
(HNSW, cosine) in PostgreSQL, with an in-Python cosine fallback for SQLite,
then reranks by keyword overlap (hybrid retrieval).
"""

from __future__ import annotations

import hashlib
import io
import math
import re
from dataclasses import dataclass

from sqlalchemy import delete, select, text

from .config import EMBED_DIM
from .db import Database
from .models import Chunk, Document

STOPWORDS = set(
    """a an and are as at be by for from has have in is it its of on or that the this to was were will with what which
    who how when where why our we you your they their them i me my do does did can could should would about into than
    then there these those not no yes also any all per""".split()
)
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9$%.\-]*[a-z0-9%]|[a-z0-9]")
CHUNK_CHARS = 700


def tokens(text_: str) -> list[str]:
    out = []
    for t in TOKEN_RE.findall(text_.lower()):
        if t in STOPWORDS:
            continue
        if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]  # light stemming: policies → policie, contracts → contract
        out.append(t)
    return out


def _bucket(feature: str) -> tuple[int, float]:
    h = hashlib.blake2b(feature.encode(), digest_size=8).digest()
    n = int.from_bytes(h, "little")
    return n % EMBED_DIM, 1.0 if (n >> 63) & 1 else -1.0


def embed(text_: str) -> list[float]:
    toks = tokens(text_)
    counts: dict[str, int] = {}
    for t in toks:
        counts[t] = counts.get(t, 0) + 1
    for a, b in zip(toks, toks[1:], strict=False):
        key = f"{a}_{b}"
        counts[key] = counts.get(key, 0) + 1
    vec = [0.0] * EMBED_DIM
    for feat, c in counts.items():
        idx, sign = _bucket(feat)
        vec[idx] += sign * (1.0 + math.log(c)) * (0.6 if "_" in feat else 1.0)
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


def keyword_overlap(query: str, passage: str) -> float:
    q = set(tokens(query))
    if not q:
        return 0.0
    return len(q & set(tokens(passage))) / len(q)


# ----------------------------------------------------------------- parsing


def extract_text(filename: str, data: bytes) -> tuple[str, str]:
    """Return (kind, text) for an uploaded file."""
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "pdf", "\n\n".join((page.extract_text() or "") for page in reader.pages)
    if name.endswith((".md", ".markdown")):
        return "md", data.decode("utf-8", errors="replace")
    if name.endswith((".txt", ".text", ".log")):
        return "txt", data.decode("utf-8", errors="replace")
    raise ValueError("Supported document types: .pdf, .md, .txt")


def chunk_text(text_: str, size: int = CHUNK_CHARS) -> list[str]:
    """Paragraph-aware chunks of about ``size`` characters. Markdown headings are
    carried into each chunk so a chunk keeps its section context."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text_) if p.strip()]
    chunks: list[str] = []
    current = ""
    heading = ""

    def flush() -> None:
        nonlocal current
        body = current.strip()
        if body and body != heading:  # skip chunks that are only a heading
            chunks.append(body)
        current = f"{heading}\n" if heading else ""

    for block in paragraphs:
        if block.startswith("#"):  # a new section always starts a new chunk
            first, _, rest = block.partition("\n")
            flush()
            heading = first.lstrip("#").strip()
            current = f"{heading}\n"
            p = rest.strip()
            if not p:
                continue
        else:
            p = block
        parts = [p] if len(p) <= size else re.split(r"(?<=[.!?])\s+", p)
        for part in parts:
            if len(current) + len(part) + 1 > size and current.strip() != heading:
                flush()
            current += part + ("\n\n" if len(parts) == 1 else " ")
    flush()
    return chunks


# ------------------------------------------------------------------ store


@dataclass
class Hit:
    document: str
    document_id: str
    chunk_id: int
    text: str
    score: float

    def as_dict(self) -> dict:
        return {
            "document": self.document,
            "documentId": self.document_id,
            "chunkId": self.chunk_id,
            "text": self.text,
            "score": round(self.score, 4),
        }


async def ingest(db: Database, filename: str, data: bytes) -> Document:
    kind, body = extract_text(filename, data)
    pieces = chunk_text(body)
    if not pieces:
        raise ValueError("The document contains no extractable text.")
    async with db.session() as s, s.begin():
        doc = Document(name=filename, kind=kind, size=len(data), chunk_count=len(pieces), preview=body[:1500])
        s.add(doc)
        await s.flush()
        for i, piece in enumerate(pieces):
            s.add(Chunk(document_id=doc.id, idx=i, text=piece, embedding=embed(piece)))
    return doc


async def delete_document(db: Database, doc_id: str) -> bool:
    async with db.session() as s, s.begin():
        await s.execute(delete(Chunk).where(Chunk.document_id == doc_id))
        result = await s.execute(delete(Document).where(Document.id == doc_id))
        return result.rowcount > 0


async def search(db: Database, query: str, k: int = 4, candidates: int = 20) -> list[Hit]:
    """Hybrid search: vector similarity for recall, then keyword overlap to rerank."""
    qvec = embed(query)
    async with db.session() as s:
        if db.is_postgres:
            literal = "[" + ",".join(f"{v:.6f}" for v in qvec) + "]"
            rows = await s.execute(
                text(
                    "SELECT c.id, c.text, c.document_id, d.name, 1 - (c.embedding <=> CAST(:q AS vector)) AS sim "
                    "FROM chunks c JOIN documents d ON d.id = c.document_id "
                    "ORDER BY c.embedding <=> CAST(:q AS vector) LIMIT :n"
                ),
                {"q": literal, "n": candidates},
            )
            scored = [(r.sim, r.id, r.text, r.document_id, r.name) for r in rows]
        else:
            rows = await s.execute(select(Chunk, Document.name).join(Document, Document.id == Chunk.document_id))
            scored = [(cosine(qvec, c.embedding), c.id, c.text, c.document_id, name) for c, name in rows]
            scored.sort(key=lambda r: r[0], reverse=True)
            scored = scored[:candidates]

    hits = [
        Hit(document=name, document_id=did, chunk_id=cid, text=body, score=0.65 * sim + 0.35 * keyword_overlap(query, body))
        for sim, cid, body, did, name in scored
    ]
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]
