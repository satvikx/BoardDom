"""Chunk extracted sources, embed them, and retrieve by cosine similarity.

Chunk text and [C n] labels live in SQLite; vectors live in ChromaDB (see vector_index.py).
A document is re-indexed only when its content_revision changes (extraction or correction).
"""

import math
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.entities import ChunkCounter, SourceChunk, SourceDocument, SourceUnit

CHUNK_CHARS = 900


def split_text(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Paragraph-aware chunks of at most `limit` characters (long paragraphs are cut).

    Markdown headings begin a new chunk and stay attached to the text that follows.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        while len(paragraph) > limit:
            cut = paragraph.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            if current:
                chunks.append(current)
                current = ""
            chunks.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        # A markdown heading starts a new chunk, so each topic is retrieved on its own.
        heading = paragraph.startswith("#")
        if current and (heading or len(current) + len(paragraph) + 2 > limit):
            chunks.append(current)
            current = ""
        current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def vector_index(db: Session):
    index = db.info.get("vector_index")
    if index is None:
        raise RuntimeError("Session has no vector index (use app.db.session.session_factory).")
    return index


def ensure_index(db: Session, provider, workspace_id) -> int:
    """Bring the course's chunks (SQLite) and vectors (ChromaDB) in line with its sources.

    Returns the number of searchable chunks. Chunks that look like prompt injection are kept
    (and shown to the teacher) but never embedded, searched, or sent to the model.
    """
    from app.services.guardrails import moderation_flags, screen_injection

    index = vector_index(db)
    model = embedding_id(provider)
    documents = db.scalars(
        select(SourceDocument).where(SourceDocument.workspace_id == workspace_id)
    ).all()
    current = {
        doc_id: revision
        for doc_id, revision in db.execute(
            select(SourceChunk.document_id, func.max(SourceChunk.content_revision))
            .where(SourceChunk.workspace_id == workspace_id)
            .group_by(SourceChunk.document_id)
        ).all()
    }
    counter = db.get(ChunkCounter, workspace_id)
    if counter is None:
        counter = ChunkCounter(workspace_id=workspace_id, next_ordinal=1)
        db.add(counter)
    next_ordinal = counter.next_ordinal
    for doc in documents:
        extracted = doc.extraction_status == "extracted"
        if extracted and current.get(doc.id) == doc.content_revision:
            continue
        old = db.scalars(select(SourceChunk.id).where(SourceChunk.document_id == doc.id)).all()
        index.delete(str(i) for i in old)
        db.execute(delete(SourceChunk).where(SourceChunk.document_id == doc.id))
        if not extracted:
            continue
        flagged_pages = filtered_pages = 0
        for unit in db.scalars(
            select(SourceUnit).where(SourceUnit.document_id == doc.id).order_by(SourceUnit.position)
        ):
            for text in split_text(unit.effective_text):
                injected = screen_injection(text).flagged
                harmful = not injected and bool(moderation_flags(provider, None, text))
                flagged = injected or harmful
                flagged_pages += injected
                filtered_pages += harmful
                db.add(
                    SourceChunk(
                        workspace_id=workspace_id,
                        document_id=doc.id,
                        content_revision=doc.content_revision,
                        ordinal=next_ordinal,
                        page_number=unit.page_number,
                        text=text,
                        embedding=[],
                        embedding_model="",  # set when the vector is stored
                        flagged=flagged,
                    )
                )
                next_ordinal += 1
        warnings = [
            w
            for w in doc.extraction_warnings
            if "prompt injection" not in w and "content filter" not in w
        ]
        if flagged_pages:
            warnings.append(
                f"{flagged_pages} passage(s) look like instructions to an AI (possible prompt "
                "injection). They are excluded from AI generation; review the source."
            )
        if filtered_pages:
            warnings.append(
                f"{filtered_pages} passage(s) were flagged by the content filter and are "
                "excluded from AI generation."
            )
        if warnings != doc.extraction_warnings:
            doc.extraction_warnings = warnings
    counter.next_ordinal = next_ordinal
    db.flush()

    # Embed every searchable chunk whose vector is missing or from another model.
    chunks = db.scalars(
        select(SourceChunk).where(
            SourceChunk.workspace_id == workspace_id, SourceChunk.flagged.is_(False)
        )
    ).all()
    stored = index.ids(str(workspace_id), model)
    todo = [c for c in chunks if str(c.id) not in stored or c.embedding_model != model]
    if todo:
        vectors = provider.embed([c.text for c in todo], purpose="index")
        index.upsert(
            [
                {
                    "id": str(c.id),
                    "embedding": vector,
                    "workspace_id": str(workspace_id),
                    "document_id": str(c.document_id),
                    "ordinal": c.ordinal,
                    "embedding_model": model,
                }
                for c, vector in zip(todo, vectors, strict=True)
            ]
        )
        for c in todo:
            c.embedding_model = model
    index.delete(index.all_ids(str(workspace_id)) - {str(c.id) for c in chunks})
    db.commit()
    return len(chunks)


def embedding_id(provider) -> str:
    return getattr(provider, "embedding_id", None) or getattr(provider, "name", "unknown")


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


@dataclass
class Hit:
    ordinal: int
    document: str
    page: int | None
    text: str
    score: float

    @property
    def label(self) -> str:
        return f"C{self.ordinal}"

    def snapshot(self) -> dict:
        return {"document": self.document, "page": self.page, "excerpt": self.text[:300]}


def course_chunks(db: Session, workspace_id) -> list[tuple[SourceChunk, str]]:
    """Every chunk of the course with its file name (flagged ones included, for display)."""
    return db.execute(
        select(SourceChunk, SourceDocument.original_filename)
        .join(SourceDocument, SourceDocument.id == SourceChunk.document_id)
        .where(SourceChunk.workspace_id == workspace_id)
        .order_by(SourceChunk.ordinal)
    ).all()


def search(db: Session, provider, workspace_id, query: str, k: int = 6) -> list[Hit]:
    """Top-k passages of this course only (ChromaDB, filtered by course and model)."""
    index = vector_index(db)
    model = embedding_id(provider)
    if not index.ids(str(workspace_id), model):
        return []
    [vector] = provider.embed([query], purpose="search")
    found = index.query(str(workspace_id), model, vector, k)
    if not found:
        return []
    rows = {
        str(chunk.id): (chunk, name)
        for chunk, name in db.execute(
            select(SourceChunk, SourceDocument.original_filename)
            .join(SourceDocument, SourceDocument.id == SourceChunk.document_id)
            .where(
                SourceChunk.workspace_id == workspace_id,
                SourceChunk.flagged.is_(False),
                SourceChunk.id.in_([UUID(chunk_id) for chunk_id, _ in found]),
            )
        ).all()
    }
    hits = [
        Hit(rows[i][0].ordinal, rows[i][1], rows[i][0].page_number, rows[i][0].text, score)
        for i, score in found
        if i in rows
    ]
    return sorted(hits, key=lambda hit: (-hit.score, hit.ordinal))
