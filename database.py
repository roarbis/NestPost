import sqlite3
import hashlib
import secrets
import os
import base64
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
    try:
        c.execute("ALTER TABLE content ADD COLUMN image_data TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE content ADD COLUMN image_mime TEXT DEFAULT 'image/png'")
    except Exception:
        pass

    # Performance indexes
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_content_platform ON content(platform)")
    except Exception:
        pass
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_content_status ON content(status)")
    except Exception:
        pass
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_content_created ON content(created_at DESC)")
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

    # Seed brand logo if not already set
    _seed_brand_logo(c)

    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migration: add username column to existing sessions table
    try:
        c.execute("ALTER TABLE sessions ADD COLUMN username TEXT")
    except Exception:
        pass

    # ── Users table ──────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            display_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Seed default users if table is empty
    _seed_default_users(c)

    conn.commit()
    conn.close()


def _seed_brand_logo(cursor):
    """Seed the brand logo from the bundled file if not already in settings."""
    row = cursor.execute(
        "SELECT value FROM settings WHERE key = 'brand_logo_b64'"
    ).fetchone()
    if row:
        val = row[0] if isinstance(row, (list, tuple)) else row.get("value", "")
        if val:
            return  # already seeded

    logo_path = Path(__file__).parent / "Logo - No BG.png"
    if not logo_path.exists():
        return

    with open(logo_path, "rb") as f:
        logo_b64 = base64.b64encode(f.read()).decode("utf-8")

    cursor.execute(
        "INSERT OR REPLACE INTO settings (key, value, is_encrypted) VALUES (?, ?, 0)",
        ("brand_logo_b64", logo_b64),
    )
    cursor.execute(
        "INSERT OR REPLACE INTO settings (key, value, is_encrypted) VALUES (?, ?, 0)",
        ("brand_logo_mime", "image/png"),
    )


def _seed_default_users(cursor):
    """Create masteradmin and claudeadmin if no users exist yet."""
    row = cursor.execute("SELECT COUNT(*) as cnt FROM users").fetchone()
    count = row[0] if row else 0
    if count > 0:
        return

    # Migrate existing password from settings if available
    existing_hash = None
    try:
        row = cursor.execute(
            "SELECT value FROM settings WHERE key = 'admin_password_hash'"
        ).fetchone()
        if row:
            existing_hash = row[0] if isinstance(row, (list, tuple)) else row["value"]
    except Exception:
        pass

    # masteradmin gets the existing password hash, or default "Nestpost1"
    master_hash = existing_hash if existing_hash else _hash_password("Nestpost1")
    claude_hash = _hash_password("Cl@ud3@admin@1")

    cursor.execute(
        "INSERT OR IGNORE INTO users (username, password_hash, role, display_name) VALUES (?, ?, ?, ?)",
        ("masteradmin", master_hash, "masteradmin", "Master Admin"),
    )
    cursor.execute(
        "INSERT OR IGNORE INTO users (username, password_hash, role, display_name) VALUES (?, ?, ?, ?)",
        ("claudeadmin", claude_hash, "admin", "Claude Admin"),
    )


def cleanup_old_sessions(max_age_days: int = 30):
    """Remove sessions older than max_age_days."""
    conn = get_conn()
    conn.execute(
        "DELETE FROM sessions WHERE created_at < datetime('now', ?)",
        (f"-{max_age_days} days",),
    )
    conn.commit()
    conn.close()


# ── Auth helpers ─────────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    salt = "nestpost_salt_v1"  # fixed salt — adequate for single-admin app
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def is_setup_done() -> bool:
    """Check if at least one user exists."""
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()
    conn.close()
    return bool(row and row["cnt"] > 0)


def set_admin_password(password: str):
    """Legacy — kept for compatibility. Updates masteradmin password."""
    hashed = _hash_password(password)
    conn = get_conn()
    conn.execute("UPDATE users SET password_hash = ? WHERE username = 'masteradmin'", (hashed,))
    conn.commit()
    conn.close()


def verify_password(password: str) -> bool:
    """Legacy single-password check — no longer used."""
    return False


def authenticate_user(username: str, password: str) -> dict | None:
    """Verify username+password. Returns user dict or None."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, username, password_hash, role, display_name FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    if row["password_hash"] != _hash_password(password):
        return None
    return {"id": row["id"], "username": row["username"], "role": row["role"], "display_name": row["display_name"]}


def create_user(username: str, password: str, role: str = "admin", display_name: str = "") -> bool:
    """Create a new user. Returns True on success."""
    hashed = _hash_password(password)
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, display_name) VALUES (?, ?, ?, ?)",
            (username, hashed, role, display_name or username),
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def change_user_password(username: str, old_password: str, new_password: str) -> bool:
    """Change password for a user. Validates old password first."""
    conn = get_conn()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE username = ?", (username,)
    ).fetchone()
    if not row or row["password_hash"] != _hash_password(old_password):
        conn.close()
        return False
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE username = ?",
        (_hash_password(new_password), username),
    )
    conn.commit()
    conn.close()
    return True


def get_user_by_username(username: str) -> dict | None:
    """Get user info by username."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, username, role, display_name, created_at FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row["id"], "username": row["username"], "role": row["role"], "display_name": row["display_name"]}


def create_session(username: str = "") -> str:
    token = secrets.token_urlsafe(32)
    conn = get_conn()
    conn.execute("INSERT INTO sessions (token, username) VALUES (?, ?)", (token, username))
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


def get_session_user(token: str) -> dict | None:
    """Get the user associated with a session token."""
    if not token:
        return None
    conn = get_conn()
    row = conn.execute("SELECT username FROM sessions WHERE token = ?", (token,)).fetchone()
    if not row or not row["username"]:
        conn.close()
        return None
    username = row["username"]
    user = conn.execute(
        "SELECT id, username, role, display_name FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    conn.close()
    if not user:
        return None
    return {"id": user["id"], "username": user["username"], "role": user["role"], "display_name": user["display_name"]}


def list_users() -> list:
    """Return all users (without password hashes)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, username, role, display_name, created_at FROM users ORDER BY id"
    ).fetchall()
    conn.close()
    return [{"id": r["id"], "username": r["username"], "role": r["role"],
             "display_name": r["display_name"], "created_at": r["created_at"]} for r in rows]


def delete_user(user_id: int) -> bool:
    """Delete a user by ID. Cannot delete masteradmin."""
    conn = get_conn()
    row = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or row["role"] == "masteradmin":
        conn.close()
        return False
    conn.execute("DELETE FROM sessions WHERE username = (SELECT username FROM users WHERE id = ?)", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True


def admin_reset_password(user_id: int, new_password: str) -> bool:
    """Reset a user's password (admin action, no old password needed)."""
    conn = get_conn()
    row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (_hash_password(new_password), user_id))
    conn.commit()
    conn.close()
    return True


def update_user(user_id: int, display_name: str = None, role: str = None) -> bool:
    """Update user display name and/or role. Cannot change masteradmin's role."""
    conn = get_conn()
    row = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        conn.close()
        return False
    fields, values = [], []
    if display_name is not None:
        fields.append("display_name = ?")
        values.append(display_name)
    if role is not None and row["role"] != "masteradmin":
        fields.append("role = ?")
        values.append(role)
    if not fields:
        conn.close()
        return True
    values.append(user_id)
    conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", tuple(values))
    conn.commit()
    conn.close()
    return True


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
        self._cursor = self._conn.execute(sql, tuple(params) if not isinstance(params, tuple) else params)
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
