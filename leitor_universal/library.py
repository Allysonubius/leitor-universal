"""Biblioteca persistente (SQLite): livros, progresso de leitura, marcadores e preferências."""
from __future__ import annotations

import os
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
    cover           BLOB,
    size            INTEGER DEFAULT 0,
    mtime           REAL DEFAULT 0,
    missing         INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS folders (
    id       INTEGER PRIMARY KEY,
    path     TEXT UNIQUE NOT NULL,
    added_at TEXT
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
# Colunas adicionadas depois da 1.0.0 (bancos antigos são migrados ao abrir).
MIGRATIONS = {
    "size": "ALTER TABLE books ADD COLUMN size INTEGER DEFAULT 0",
    "mtime": "ALTER TABLE books ADD COLUMN mtime REAL DEFAULT 0",
    "missing": "ALTER TABLE books ADD COLUMN missing INTEGER DEFAULT 0",
}


def is_inside(path: str, folder: str) -> bool:
    """Compara caminhos sem tocar no disco (funciona com unidades desconectadas)."""
    p, f = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    return p == f or p.startswith(f.rstrip("\\/") + os.sep)


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
    size: int = 0
    mtime: float = 0
    missing: bool = False

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Book":
        data = dict(row)
        data["two_pages"] = bool(data["two_pages"])
        data["favorite"] = bool(data["favorite"])
        data["finished"] = bool(data["finished"])
        data["missing"] = bool(data["missing"])
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
        self.conn = sqlite3.connect(data_dir / "biblioteca.db", timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(books)")}
        for column, ddl in MIGRATIONS.items():
            if column not in columns:
                self.conn.execute(ddl)
        self.conn.commit()

    # ------------------------------------------------------------- livros
    def import_file(self, path: str | Path) -> Book:
        """Adiciona o arquivo à biblioteca (ou reencontra-o, mesmo se movido)."""
        p = Path(path).resolve()
        stat = p.stat()
        fp = fingerprint(p)
        existing = self.conn.execute("SELECT * FROM books WHERE fingerprint = ?", (fp,)).fetchone()
        if existing:
            self.conn.execute(
                "UPDATE books SET path = ?, size = ?, mtime = ?, missing = 0 WHERE id = ?",
                (str(p), stat.st_size, stat.st_mtime, existing["id"]))
            self.conn.commit()
            return self.get(existing["id"])

        loaded = open_document(p, self.cache_dir)
        try:
            cover = render_cover(loaded.doc)
        except Exception:
            cover = None
        same_path = self.conn.execute("SELECT id FROM books WHERE path = ?", (str(p),)).fetchone()
        if same_path:
            # O arquivo foi editado no lugar: mantém progresso e marcadores.
            self.conn.execute(
                "UPDATE books SET fingerprint = ?, title = ?, author = ?, kind = ?, pages = ?, cover = ?,"
                " size = ?, mtime = ?, missing = 0 WHERE id = ?",
                (fp, loaded.title, loaded.author, loaded.kind, loaded.doc.page_count, cover,
                 stat.st_size, stat.st_mtime, same_path["id"]))
            book_id = same_path["id"]
        else:
            cur = self.conn.execute(
                "INSERT INTO books (fingerprint, path, title, author, kind, pages, added_at, cover, size, mtime)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fp, str(p), loaded.title, loaded.author, loaded.kind, loaded.doc.page_count, _now(),
                 cover, stat.st_size, stat.st_mtime),
            )
            book_id = cur.lastrowid
        self.conn.commit()
        loaded.doc.close()
        return self.get(book_id)

    def get(self, book_id: int) -> Book | None:
        row = self.conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return Book.from_row(row) if row else None

    def all_books(self, include_missing: bool = False) -> list[Book]:
        sql = "SELECT * FROM books" if include_missing else "SELECT * FROM books WHERE missing = 0"
        return [Book.from_row(r) for r in self.conn.execute(sql).fetchall()]

    def set_missing(self, book_id: int, missing: bool) -> None:
        self.conn.execute("UPDATE books SET missing = ? WHERE id = ?", (int(missing), book_id))
        self.conn.commit()

    def last_read(self) -> Book | None:
        row = self.conn.execute(
            "SELECT * FROM books WHERE last_opened IS NOT NULL AND missing = 0"
            " ORDER BY last_opened DESC LIMIT 1"
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
            " COALESCE(SUM(reading_seconds), 0) AS seconds FROM books WHERE missing = 0"
        ).fetchone()
        return dict(row)

    # -------------------------------------------------------------- pastas
    def folders(self) -> list[str]:
        return [r["path"] for r in self.conn.execute("SELECT path FROM folders ORDER BY path")]

    def add_folder(self, path: str | Path) -> str:
        folder = str(Path(path).resolve())
        self.conn.execute("INSERT OR IGNORE INTO folders (path, added_at) VALUES (?, ?)", (folder, _now()))
        self.conn.commit()
        return folder

    def remove_folder(self, path: str, remove_books: bool = True) -> int:
        """Remove a pasta; livros que não pertencem a outra pasta saem da biblioteca."""
        self.conn.execute("DELETE FROM folders WHERE path = ?", (path,))
        removed = 0
        if remove_books:
            others = self.folders()
            for book in self.all_books(include_missing=True):
                if is_inside(book.path, path) and not any(is_inside(book.path, o) for o in others):
                    self.conn.execute("DELETE FROM books WHERE id = ?", (book.id,))
                    removed += 1
        self.conn.commit()
        return removed

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
