"""Слой доступа к БД. Поддерживает SQLite (по умолчанию) и PostgreSQL (DATABASE_URL)."""

import os
import sqlite3
import threading
import time

DB_URL = os.getenv("DATABASE_URL", "sqlite:///data/data.db")

_lock = threading.Lock()
_conn_holder = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id          BIGINT PRIMARY KEY,
    anon_num       INTEGER UNIQUE,
    display_name   TEXT,
    avatar         TEXT,
    banned         INTEGER DEFAULT 0,
    banned_reason  TEXT,
    last_seen_at   INTEGER,
    created_at     INTEGER
);

CREATE TABLE IF NOT EXISTS queue (
    tg_id     BIGINT PRIMARY KEY,
    joined_at INTEGER
);

CREATE TABLE IF NOT EXISTS chats (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_a     BIGINT,
    user_b     BIGINT,
    status     TEXT DEFAULT 'active',
    created_at INTEGER,
    closed_at  INTEGER
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER,
    sender_id  BIGINT,
    text       TEXT,
    created_at INTEGER,
    reported   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id BIGINT,
    accused_id  BIGINT,
    chat_id     INTEGER,
    reason      TEXT,
    evidence    TEXT,
    status      TEXT DEFAULT 'new',
    created_at  INTEGER
);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id      BIGINT,
    text       TEXT,
    force      INTEGER DEFAULT 1,
    created_at INTEGER,
    sent       INTEGER DEFAULT 0
);
"""

IS_PG = DB_URL.startswith(("postgres://", "postgresql://"))


def _placeholder() -> str:
    return "%s" if IS_PG else "?"


def convert_sql(sql: str) -> str:
    """? -> %s для PostgreSQL."""
    return sql.replace("?", "%s") if IS_PG else sql


def _connect():
    if IS_PG:
        import psycopg2

        conn = psycopg2.connect(DB_URL, sslmode="require")
        conn.autocommit = False
        return conn

    path = DB_URL.replace("sqlite:///", "")
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_conn():
    conn = getattr(_conn_holder, "conn", None)
    if conn is None:
        conn = _connect()
        _conn_holder.conn = conn
    return conn


def _migrate(cur, conn):
    """Лёгкие миграции: добавляем колонки, если таблицы уже существуют."""
    migrations = [
        "ALTER TABLE users ADD COLUMN last_seen_at INTEGER",
        "ALTER TABLE notifications ADD COLUMN force INTEGER DEFAULT 1",
        "ALTER TABLE notifications ADD COLUMN sent INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN banned_reason TEXT",
    ]
    for stmt in migrations:
        try:
            cur.execute(stmt)
        except Exception:
            pass  # колонка уже есть
    conn.commit()


def init_db():
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        for stmt in SCHEMA.split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(convert_sql(stmt))
        conn.commit()
        _migrate(cur, conn)


class DB:
    """Тонкая обёртка: execute + fetch helpers."""

    @staticmethod
    def execute(sql, params=(), commit=True):
        with _lock:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(convert_sql(sql), params)
            if commit:
                conn.commit()
            return cur

    @staticmethod
    def one(sql, params=()):
        cur = DB.execute(sql, params, commit=False)
        row = cur.fetchone()
        if row is None:
            return None
        if isinstance(row, sqlite3.Row):
            return dict(row)
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))

    @staticmethod
    def all(sql, params=()):
        cur = DB.execute(sql, params, commit=False)
        rows = cur.fetchall()
        result = []
        for row in rows:
            if isinstance(row, sqlite3.Row):
                result.append(dict(row))
            else:
                cols = [d[0] for d in cur.description]
                result.append(dict(zip(cols, row)))
        return result


def now() -> int:
    return int(time.time())
