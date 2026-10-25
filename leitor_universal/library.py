"""Biblioteca persistente (SQLite): livros, progresso de leitura, marcadores e preferências."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .documents import fingerprint, open_document, render_cover

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id              INTEGER PRIMARY KEY,
    fingerprint     TEXT UNIQUE NOT NULL,
    path            TEXT NOT NULL,
    title           TEXT NOT NULL,
    author          TEXT DEFAULT '',
    kind            TEXT DEFAULT '',
    pages           INTEGER DEFAULT 0,
    page            INTEGER DEFAULT 0,
    position        TEXT,
    progress        REAL DEFAULT 0,
    font_size       REAL DEFAULT 12,
    zoom_mode       TEXT DEFAULT '',
    zoom            REAL DEFAULT 1,
    two_pages       INTEGER DEFAULT 0,
    favorite        INTEGER DEFAULT 0,
    finished        INTEGER DEFAULT 0,
    reading_seconds INTEGER DEFAULT 0,
    added_at        TEXT,
    last_opened     TEXT,
    cover           BLOB
);
CREATE TABLE IF NOT EXISTS bookmarks (
    id         INTEGER PRIMARY KEY,
    book_id    INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    page       INTEGER NOT NULL,
    position   TEXT,
    label      TEXT DEFAULT '',
    note       TEXT DEFAULT '',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Book:
    id: int
    fingerprint: str
    path: str
    title: str
    author: str
    kind: str
    pages: int
    page: int
    position: str | None
    progress: float
    font_size: float
    zoom_mode: str
    zoom: float
    two_pages: bool
    favorite: bool
    finished: bool
    reading_seconds: int
    added_at: str | None
    last_opened: str | None
    cover: bytes | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Book":
        data = dict(row)
        data["two_pages"] = bool(data["two_pages"])
        data["favorite"] = bool(data["favorite"])
        data["finished"] = bool(data["finished"])
        return cls(**data)

    @property
    def status(self) -> str:
        if self.finished:
            return "concluido"
        return "lendo" if self.last_opened and self.progress > 0 else "novo"


@dataclass
class Bookmark:
    id: int
    book_id: int
    page: int
    position: str | None
    label: str
    note: str
    created_at: str


class Library:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.cache_dir = data_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(data_dir / "biblioteca.db")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------- livros
    def import_file(self, path: str | Path) -> Book:
        """Adiciona o arquivo à biblioteca (ou reencontra-o, mesmo se movido)."""
        p = Path(path).resolve()
        fp = fingerprint(p)
        existing = self.conn.execute("SELECT * FROM books WHERE fingerprint = ?", (fp,)).fetchone()
        if existing:
            if existing["path"] != str(p):
                self.conn.execute("UPDATE books SET path = ? WHERE id = ?", (str(p), existing["id"]))
                self.conn.commit()
            return self.get(existing["id"])

        loaded = open_document(p, self.cache_dir)
        try:
            cover = render_cover(loaded.doc)
        except Exception:
            cover = None
        cur = self.conn.execute(
            "INSERT INTO books (fingerprint, path, title, author, kind, pages, added_at, cover)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (fp, str(p), loaded.title, loaded.author, loaded.kind, loaded.doc.page_count, _now(), cover),
        )
        self.conn.commit()
        loaded.doc.close()
        return self.get(cur.lastrowid)

    def get(self, book_id: int) -> Book | None:
        row = self.conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return Book.from_row(row) if row else None

    def all_books(self) -> list[Book]:
        rows = self.conn.execute("SELECT * FROM books").fetchall()
        return [Book.from_row(r) for r in rows]

    def last_read(self) -> Book | None:
        row = self.conn.execute(
            "SELECT * FROM books WHERE last_opened IS NOT NULL ORDER BY last_opened DESC LIMIT 1"
        ).fetchone()
        return Book.from_row(row) if row else None

    def mark_opened(self, book_id: int) -> None:
        self.conn.execute("UPDATE books SET last_opened = ? WHERE id = ?", (_now(), book_id))
        self.conn.commit()

    def save_reading_state(self, book_id: int, *, page: int, position: str | None, pages: int,
                           progress: float, font_size: float, zoom_mode: str, zoom: float,
                           two_pages: bool, extra_seconds: int = 0) -> None:
        self.conn.execute(
            "UPDATE books SET page = ?, position = ?, pages = ?, progress = ?, font_size = ?,"
            " zoom_mode = ?, zoom = ?, two_pages = ?, reading_seconds = reading_seconds + ?,"
            " finished = CASE WHEN ? >= 0.999 THEN 1 ELSE finished END WHERE id = ?",
            (page, position, pages, progress, font_size, zoom_mode, zoom, int(two_pages),
             extra_seconds, progress, book_id),
        )
        self.conn.commit()

    def update_metadata(self, book_id: int, title: str, author: str) -> None:
        self.conn.execute("UPDATE books SET title = ?, author = ? WHERE id = ?", (title, author, book_id))
        self.conn.commit()

    def set_path(self, book_id: int, path: str) -> None:
        self.conn.execute("UPDATE books SET path = ?, fingerprint = ? WHERE id = ?",
                          (path, fingerprint(path), book_id))
        self.conn.commit()

    def set_flag(self, book_id: int, flag: str, value: bool) -> None:
        if flag not in {"favorite", "finished"}:
            raise ValueError(flag)
        self.conn.execute(f"UPDATE books SET {flag} = ? WHERE id = ?", (int(value), book_id))
        self.conn.commit()

    def reset_progress(self, book_id: int) -> None:
        self.conn.execute(
            "UPDATE books SET page = 0, position = NULL, progress = 0, finished = 0 WHERE id = ?",
            (book_id,),
        )
        self.conn.commit()

    def remove(self, book_id: int) -> None:
        self.conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        self.conn.commit()

    def stats(self) -> dict:
        row = self.conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(finished), 0) AS finished,"
            " COALESCE(SUM(reading_seconds), 0) AS seconds FROM books"
        ).fetchone()
        return dict(row)

    # ---------------------------------------------------------- marcadores
    def bookmarks(self, book_id: int) -> list[Bookmark]:
        rows = self.conn.execute(
            "SELECT * FROM bookmarks WHERE book_id = ? ORDER BY page, id", (book_id,)
        ).fetchall()
        return [Bookmark(**dict(r)) for r in rows]

    def add_bookmark(self, book_id: int, page: int, position: str | None, label: str, note: str) -> None:
        self.conn.execute(
            "INSERT INTO bookmarks (book_id, page, position, label, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (book_id, page, position, label, note, _now()),
        )
        self.conn.commit()

    def update_bookmark_note(self, bookmark_id: int, note: str) -> None:
        self.conn.execute("UPDATE bookmarks SET note = ? WHERE id = ?", (note, bookmark_id))
        self.conn.commit()

    def remove_bookmark(self, bookmark_id: int) -> None:
        self.conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
        self.conn.commit()

    # -------------------------------------------------------- preferências
    def setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
