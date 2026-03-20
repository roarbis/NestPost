import sqlite3
import hashlib
import secrets
import os
from typing import Any
from pathlib import Path

# ── Connection mode: Turso (cloud) or local SQLite ───────────────────────────
TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")
DB_PATH = str(Path(__file__).parent.resolve() / "connectnest.db")


def init_db():
    conn = _raw_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            content_type TEXT,
            topic TEXT,
            caption TEXT,
            hashtags TEXT,
            image_suggestion TEXT,
            hook TEXT,
            cta TEXT,
            status TEXT DEFAULT 'draft',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            posted_at TIMESTAMP,
            image_path TEXT,
            image_prompt TEXT
        )
    """)

    # Migration: add image columns to existing tables
    try:
        c.execute("ALTER TABLE content ADD COLUMN image_path TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE content ADD COLUMN image_prompt TEXT")
    except Exception:
        pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            is_encrypted INTEGER DEFAULT 0
        )
    """)

    defaults = [
        ("ollama_url", "http://localhost:11434", 0),
        ("default_model", "ollama", 0),
        ("default_ollama_model", "llama3.2", 0),
    ]
    for key, value, enc in defaults:
        c.execute(
            "INSERT OR IGNORE INTO settings (key, value, is_encrypted) VALUES (?, ?, ?)",
            (key, value, enc),
        )

    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


# ── Auth helpers ─────────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    salt = "nestpost_salt_v1"  # fixed salt — adequate for single-admin app
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def is_setup_done() -> bool:
    """Check if admin password has been set."""
    conn = get_conn()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = 'admin_password_hash'"
    ).fetchone()
    conn.close()
    return bool(row and row["value"])


def set_admin_password(password: str):
    hashed = _hash_password(password)
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value, is_encrypted) VALUES (?, ?, 0)",
        ("admin_password_hash", hashed),
    )
    conn.commit()
    conn.close()


def verify_password(password: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = 'admin_password_hash'"
    ).fetchone()
    conn.close()
    if not row or not row["value"]:
        return False
    return row["value"] == _hash_password(password)


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    conn = get_conn()
    conn.execute("INSERT INTO sessions (token) VALUES (?)", (token,))
    conn.commit()
    conn.close()
    return token


def validate_session(token: str) -> bool:
    if not token:
        return False
    conn = get_conn()
    row = conn.execute("SELECT token FROM sessions WHERE token = ?", (token,)).fetchone()
    conn.close()
    return bool(row)


def delete_session(token: str):
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


class DictCursor:
    """Wraps a libsql cursor to return dict-like rows (keyed by column name)."""
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        self._cursor = self._conn.execute(sql, params)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._cursor.description]
        return _DictRow(zip(cols, row))

    def fetchall(self):
        rows = self._cursor.fetchall()
        if not rows:
            return []
        cols = [d[0] for d in self._cursor.description]
        return [_DictRow(zip(cols, r)) for r in rows]

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


class _DictRow:
    """Mimics sqlite3.Row — supports dict(row), row['key'], row[index]."""
    def __init__(self, pairs):
        self._data = dict(pairs)
        self._keys = list(self._data.keys())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._data[self._keys[key]]
        return self._data[key]

    def keys(self):
        return self._keys

    def __iter__(self):
        return iter(self._data.values())

    def __repr__(self):
        return repr(self._data)


class _TursoConn:
    """Wrapper around libsql connection that returns dict-like rows."""
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        dc = DictCursor(self._conn)
        dc.execute(sql, params)
        return dc

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def cursor(self):
        return self._conn.cursor()


def get_conn():
    if TURSO_URL and TURSO_TOKEN:
        import libsql_experimental as libsql
        conn = libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)
        return _TursoConn(conn)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _raw_conn():
    """Connection without row_factory — for init_db."""
    if TURSO_URL and TURSO_TOKEN:
        import libsql_experimental as libsql
        return libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)
    return sqlite3.connect(DB_PATH)


def get_setting(key: str, default: Any = None) -> Any:
    conn = get_conn()
    row = conn.execute(
        "SELECT value, is_encrypted FROM settings WHERE key = ?", (key,)
    ).fetchone()
    conn.close()
    if not row:
        return default
    if row["is_encrypted"] and row["value"]:
        from encryption_utils import decrypt_value
        return decrypt_value(row["value"])
    return row["value"]


def set_setting(key: str, value: str, is_encrypted: bool = False):
    from encryption_utils import encrypt_value
    stored = encrypt_value(value) if is_encrypted and value else value
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value, is_encrypted) VALUES (?, ?, ?)",
        (key, stored, 1 if is_encrypted else 0),
    )
    conn.commit()
    conn.close()


def get_recent_topics(limit: int = 10) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT topic FROM content ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [r["topic"] for r in rows]
