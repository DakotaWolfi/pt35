"""Compact, reconstructible receipt history using SQLite and compressed JSON.

No per-job images. Fields, templates, timestamp and print outcome are retained.
Database is local to the station, not committed to Git.
"""
import json
from pathlib import Path
import sqlite3
import threading
import time
import zlib

ROOT = Path(__file__).resolve().parent
DB = ROOT / "print_history.sqlite3"
_guard = threading.RLock()

def connection():
    db = sqlite3.connect(DB, timeout=10)
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS receipts(
        id INTEGER PRIMARY KEY,
        created INTEGER NOT NULL,
        finished INTEGER,
        kind TEXT NOT NULL CHECK (kind IN ('fine','custom')),
        payload BLOB NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('queued','printed','failed')),
        error TEXT DEFAULT ''
    )""")
    existing = {row[1] for row in db.execute("PRAGMA table_info(receipts)")}
    if "source_ip" not in existing:
        db.execute("ALTER TABLE receipts ADD COLUMN source_ip TEXT NOT NULL DEFAULT ''")
    if "user_agent" not in existing:
        db.execute("ALTER TABLE receipts ADD COLUMN user_agent TEXT NOT NULL DEFAULT ''")
    return db

def record(kind, payload, source_ip="", user_agent=""):
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()
    with _guard, connection() as db:
        cursor = db.execute("INSERT INTO receipts(created,kind,payload,state,source_ip,user_agent) VALUES(?,?,?,?,?,?)",
                            (int(time.time()), kind, zlib.compress(raw, level=9), "queued", str(source_ip)[:64], str(user_agent)[:180]))
        db.commit()
        return cursor.lastrowid

def complete(job_id, success, error=""):
    with _guard, connection() as db:
        db.execute("UPDATE receipts SET finished=?,state=?,error=? WHERE id=?",
                   (int(time.time()), "printed" if success else "failed", str(error)[:160], job_id))
        db.commit()

def unpack(value):
    return json.loads(zlib.decompress(value).decode())

def list_jobs(limit=50):
    with _guard, connection() as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT id,created,finished,kind,state,error,payload,source_ip,user_agent FROM receipts ORDER BY id DESC LIMIT ?",
                          (max(1,min(int(limit),100)),)).fetchall()
    return [{"id":row["id"],"created":row["created"],"finished":row["finished"],
             "kind":row["kind"],"state":row["state"],"error":row["error"],
             "source_ip":row["source_ip"],"user_agent":row["user_agent"],
             "receipt":unpack(row["payload"])} for row in rows]

def get_job(job_id):
    with _guard, connection() as db:
        db.row_factory=sqlite3.Row
        row=db.execute("SELECT * FROM receipts WHERE id=?",(job_id,)).fetchone()
    if row is None: return None
    return {"id":row["id"],"created":row["created"],"finished":row["finished"],
            "kind":row["kind"],"state":row["state"],"error":row["error"],
            "receipt":unpack(row["payload"])}
