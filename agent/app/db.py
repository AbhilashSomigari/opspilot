from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import settings

SCHEMA = r"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS incidents (
  id text PRIMARY KEY,
  title text NOT NULL,
  alert text NOT NULL,
  service text NOT NULL,
  severity text NOT NULL,
  status text NOT NULL,
  result jsonb,
  proposed_action jsonb,
  approved_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_events (
  id bigserial PRIMARY KEY,
  incident_id text NOT NULL,
  ts timestamptz NOT NULL DEFAULT now(),
  event_type text NOT NULL,
  actor text NOT NULL,
  name text NOT NULL,
  input jsonb,
  output jsonb,
  ok boolean NOT NULL DEFAULT true,
  error text
);

CREATE TABLE IF NOT EXISTS documents (
  id bigserial PRIMARY KEY,
  source text NOT NULL UNIQUE,
  kind text NOT NULL,
  title text NOT NULL,
  content text NOT NULL,
  embedding vector(256) NOT NULL,
  textsearch tsvector GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || content)) STORED,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS documents_embedding_hnsw ON documents USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS documents_textsearch_gin ON documents USING gin (textsearch);
"""


@contextmanager
def conn():
    with psycopg.connect(settings.database_url, row_factory=dict_row, autocommit=True) as connection:
        yield connection


def init_db() -> None:
    with conn() as c:
        c.execute(SCHEMA)


def create_incident(incident_id: str, req: dict[str, Any]) -> None:
    with conn() as c:
        c.execute(
            """INSERT INTO incidents(id,title,alert,service,severity,status)
               VALUES (%s,%s,%s,%s,%s,'investigating')
               ON CONFLICT(id) DO UPDATE SET status='investigating', updated_at=now()""",
            (incident_id, req["title"], req["alert"], req["service"], req["severity"]),
        )


def save_result(incident_id: str, result: dict[str, Any], action: dict[str, Any]) -> None:
    with conn() as c:
        c.execute(
            "UPDATE incidents SET status='awaiting_approval', result=%s, proposed_action=%s, updated_at=now() WHERE id=%s",
            (Jsonb(result), Jsonb(action), incident_id),
        )


def get_incident(incident_id: str) -> dict[str, Any] | None:
    with conn() as c:
        return c.execute("SELECT * FROM incidents WHERE id=%s", (incident_id,)).fetchone()


def mark_approved(incident_id: str, actor: str, status: str = "approved") -> None:
    with conn() as c:
        c.execute(
            "UPDATE incidents SET approved_by=%s, status=%s, updated_at=now() WHERE id=%s",
            (actor, status, incident_id),
        )


def audit(incident_id: str, event_type: str, actor: str, name: str,
          input_data: Any = None, output_data: Any = None, ok: bool = True, error: str | None = None) -> None:
    with conn() as c:
        c.execute(
            """INSERT INTO audit_events(incident_id,event_type,actor,name,input,output,ok,error)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                incident_id, event_type, actor, name,
                Jsonb(input_data) if input_data is not None else None,
                Jsonb(output_data) if output_data is not None else None,
                ok, error,
            ),
        )


def audit_trail(incident_id: str) -> list[dict[str, Any]]:
    with conn() as c:
        return list(c.execute(
            "SELECT id,ts,event_type,actor,name,input,output,ok,error FROM audit_events WHERE incident_id=%s ORDER BY id",
            (incident_id,),
        ).fetchall())
