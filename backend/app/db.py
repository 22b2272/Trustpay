import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS intents(id TEXT PRIMARY KEY, raw_text TEXT, parsed_json TEXT,
  confirmed_at TEXT, expires_at TEXT, used_by TEXT);
CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY, intent_id TEXT, proposal_json TEXT,
  decision TEXT, reason_codes TEXT, token_hash TEXT, status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS executions(proposal_id TEXT UNIQUE, paypal_order_id TEXT, paypal_status TEXT,
  detail_json TEXT);
CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY AUTOINCREMENT, proposal_id TEXT,
  event_type TEXT, detail_json TEXT, timestamp TEXT);
"""


@contextmanager
def conn():
    c = sqlite3.connect(db_path())
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    try:
        yield c
        c.commit()
    finally:
        c.close()


def one(sql, args=()):
    with conn() as c:
        r = c.execute(sql, args).fetchone()
        return dict(r) if r else None


def many(sql, args=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def run(sql, args=()) -> int:
    with conn() as c:
        return c.execute(sql, args).rowcount


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def audit(proposal_id: str | None, event: str, detail: dict) -> None:
    run("INSERT INTO audit_events(proposal_id,event_type,detail_json,timestamp) VALUES(?,?,?,?)",
        (proposal_id, event, json.dumps(detail, default=str), now_iso()))
