from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Iterable

from openai import OpenAI
from psycopg.types.json import Jsonb

from ..config import settings
from ..db import conn

DIM = 256


def _fallback_embedding(text: str) -> list[float]:
    vec = [0.0] * DIM
    for token in re.findall(r"[a-z0-9_./-]+", text.lower()):
        digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
        n = int.from_bytes(digest, "big")
        idx = n % DIM
        vec[idx] += 1.0 if ((n >> 9) & 1) else -1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def embed(text: str) -> list[float]:
    if not settings.openai_api_key:
        return _fallback_embedding(text)
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.embeddings.create(
        model=settings.embedding_model,
        input=text,
        dimensions=DIM,
    )
    return response.data[0].embedding


def _literal(v: Iterable[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in v) + "]"


def upsert_document(source: str, kind: str, title: str, content: str, metadata: dict | None = None) -> None:
    vector = _literal(embed(title + "\n" + content))
    with conn() as c:
        c.execute(
            """INSERT INTO documents(source,kind,title,content,embedding,metadata)
               VALUES (%s,%s,%s,%s,%s::vector,%s)
               ON CONFLICT(source) DO UPDATE SET
                 kind=excluded.kind,title=excluded.title,content=excluded.content,
                 embedding=excluded.embedding,metadata=excluded.metadata""",
            (source, kind, title, content, vector, Jsonb(metadata or {})),
        )


def ingest_paths(paths: list[Path]) -> int:
    count = 0
    for directory in paths:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("**/*")):
            if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
                continue
            text = path.read_text(errors="replace")
            title = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), path.stem)
            kind = "runbook" if "runbook" in str(directory).lower() else "incident"
            upsert_document(str(path), kind, title, text, {"filename": path.name})
            count += 1
    return count


def hybrid_search(query: str, limit: int = 6) -> list[dict]:
    qvec = _literal(embed(query))
    with conn() as c:
        vector_rows = list(c.execute(
            """SELECT id,source,kind,title,content,1-(embedding <=> %s::vector) AS score
               FROM documents ORDER BY embedding <=> %s::vector LIMIT %s""",
            (qvec, qvec, max(limit * 2, 8)),
        ).fetchall())
        lexical_rows = list(c.execute(
            """SELECT id,source,kind,title,content,
                      ts_rank_cd(textsearch, plainto_tsquery('english', %s)) AS score
               FROM documents
               WHERE textsearch @@ plainto_tsquery('english', %s)
               ORDER BY score DESC LIMIT %s""",
            (query, query, max(limit * 2, 8)),
        ).fetchall())

    # Reciprocal-rank fusion avoids pretending vector and FTS scores share a scale.
    fused: dict[int, dict] = {}
    for rows in (vector_rows, lexical_rows):
        for rank, row in enumerate(rows, start=1):
            item = fused.setdefault(row["id"], {**row, "rrf": 0.0})
            item["rrf"] += 1.0 / (60 + rank)
    ranked = sorted(fused.values(), key=lambda x: x["rrf"], reverse=True)[:limit]
    return [
        {
            "source": r["source"],
            "kind": r["kind"],
            "title": r["title"],
            "excerpt": r["content"][:1800],
            "score": round(r["rrf"], 6),
        }
        for r in ranked
    ]
