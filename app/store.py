"""Tiny SQLite key/value store used for caching historical responses and day baselines."""
import json
import os
import sqlite3
import threading
import time

from .config import DB_PATH

_lock = threading.Lock()
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT, ts REAL)")
_conn.commit()


def get(key):
    with _lock:
        row = _conn.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def put(key, value):
    with _lock:
        _conn.execute("REPLACE INTO kv (k, v, ts) VALUES (?,?,?)", (key, json.dumps(value), time.time()))
        _conn.commit()
