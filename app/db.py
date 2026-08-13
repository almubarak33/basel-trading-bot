import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB = Path(__file__).resolve().parent.parent / "trades.db"

def init_db():
    with sqlite3.connect(DB) as con:
        con.execute('''
        CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            kind TEXT NOT NULL,
            symbol TEXT,
            payload TEXT NOT NULL
        )''')

def log_event(kind: str, symbol: str | None, payload: str):
    with sqlite3.connect(DB) as con:
        con.execute(
            "INSERT INTO events(ts,kind,symbol,payload) VALUES(?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), kind, symbol, payload),
        )

def recent_events(limit: int = 100):
    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
