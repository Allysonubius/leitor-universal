"""Biblioteca persistente (SQLite): livros, progresso, marcadores, grifos, coleções,
registro de leitura e preferências."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .documents import detect_series, fingerprint, open_document, render_cover

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id                  INTEGER PRIMARY KEY,
    fingerprint         TEXT UNIQUE NOT NULL,
    path                TEXT NOT NULL,
    title               TEXT NOT NULL,
    author              TEXT DEFAULT '',
    kind                TEXT DEFAULT '',
    pages               INTEGER DEFAULT 0,
    page                INTEGER DEFAULT 0,
    position            TEXT,
    progress            REAL DEFAULT 0,
    font_size           REAL DEFAULT 12,
    zoom_mode           TEXT DEFAULT '',
    zoom                REAL DEFAULT 1,
    two_pages           INTEGER DEFAULT 0,
    favorite            INTEGER DEFAULT 0,
    finished            INTEGER DEFAULT 0,
    reading_seconds     INTEGER DEFAULT 0,
    added_at            TEXT,
    last_opened         TEXT,
    cover               BLOB,
    size                INTEGER DEFAULT 0,
    mtime               REAL DEFAULT 0,
    missing             INTEGER DEFAULT 0,
    finished_at         TEXT,
    progress_updated_at TEXT,
    series              TEXT,
    series_index        REAL,
    description         TEXT DEFAULT '',
    continuous          INTEGER DEFAULT 0
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
    created_at TEXT,
    uuid       TEXT
);
CREATE TABLE IF NOT EXISTS highlights (
    id         INTEGER PRIMARY KEY,
    uuid       TEXT UNIQUE NOT NULL,
    book_id    INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    page       INTEGER NOT NULL,
    position   TEXT,
    color      TEXT NOT NULL,
    text       TEXT NOT NULL,
    note       TEXT DEFAULT '',
    rects      TEXT DEFAULT '[]',
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS collections (
    id         INTEGER PRIMARY KEY,
    name       TEXT UNIQUE NOT NULL,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS collection_books (
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    book_id       INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    PRIMARY KEY (collection_id, book_id)
);
CREATE TABLE IF NOT EXISTS reading_log (
    day     TEXT NOT NULL,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    seconds INTEGER DEFAULT 0,
    pages   INTEGER DEFAULT 0,
    PRIMARY KEY (day, book_id)
);
CREATE TABLE IF NOT EXISTS deletions (
    uuid       TEXT PRIMARY KEY,
    deleted_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""
# Colunas adicionadas depois da 1.0.0 (bancos antigos são migrados ao abrir).
MIGRATIONS = {
    "books": {
        "size": "INTEGER DEFAULT 0", "mtime": "REAL DEFAULT 0", "missing": "INTEGER DEFAULT 0",
        "finished_at": "TEXT", "progress_updated_at": "TEXT", "series": "TEXT",
        "series_index": "REAL", "description": "TEXT DEFAULT ''", "continuous": "INTEGER DEFAULT 0",
    },
    "bookmarks": {"uuid": "TEXT"},
}
HIGHLIGHT_COLORS = {"amarelo": "#ffd54a", "verde": "#7ed957", "azul": "#5ab0ff", "rosa": "#ff7eb6"}


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
    size: int = 0
    mtime: float = 0
    missing: bool = False
    finished_at: str | None = None
    progress_updated_at: str | None = None
    series: str | None = None
    series_index: float | None = None
    description: str = ""
    continuous: bool = False

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Book":
        data = {k: row[k] for k in row.keys() if k != "cover"}
        for flag in ("two_pages", "favorite", "finished", "missing", "continuous"):
            data[flag] = bool(data[flag])
        data["description"] = data.get("description") or ""
        return cls(**data)

    @property
    def status(self) -> str:
        if self.finished:
            return "concluido"
        return "lendo" if self.last_opened and self.progress > 0 else "novo"


BOOK_COLUMNS = ", ".join(f.name for f in Book.__dataclass_fields__.values())


@dataclass
class Bookmark:
    id: int
    book_id: int
    page: int
    position: str | None
    label: str
    note: str
    created_at: str
    uuid: str | None = None


@dataclass
class Highlight:
    id: int
    uuid: str
    book_id: int
    page: int
    position: str | None
    color: str
    text: str
    note: str
    rects: list = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    book_title: str = ""

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Highlight":
        data = dict(row)
        data["rects"] = json.loads(data.get("rects") or "[]")
        return cls(**data)


@dataclass
class Collection:
    id: int
    name: str
    count: int


class Library:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.cache_dir = data_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(data_dir / "biblioteca.db", timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        # Tabelas novas primeiro; colunas faltantes de bancos antigos depois.
        tables = {r["name"] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, columns in MIGRATIONS.items():
            if table not in tables:
                continue
            existing = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            for column, ddl in columns.items():
                if column not in existing:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        self.conn.executescript(SCHEMA)
        for row in self.conn.execute("SELECT id FROM bookmarks WHERE uuid IS NULL").fetchall():
            self.conn.execute("UPDATE bookmarks SET uuid = ? WHERE id = ?", (uuid.uuid4().hex, row["id"]))
        for row in self.conn.execute("SELECT id, title, path FROM books WHERE series IS NULL").fetchall():
            self._store_series(row["id"], row["title"], row["path"])
        self.conn.commit()

    def _store_series(self, book_id: int, title: str, path: str) -> None:
        name, index = detect_series(title, Path(path).stem)
        self.conn.execute("UPDATE books SET series = ?, series_index = ? WHERE id = ?",
                          (name or "", index, book_id))

    # ------------------------------------------------------------- livros
    def import_file(self, path: str | Path) -> Book:
        """Adiciona o arquivo à biblioteca (ou reencontra-o, mesmo se movido)."""
        p = Path(path).resolve()
        stat = p.stat()
        fp = fingerprint(p)
        existing = self.conn.execute("SELECT id FROM books WHERE fingerprint = ?", (fp,)).fetchone()
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
        self._store_series(book_id, loaded.title, str(p))
        self.conn.commit()
        loaded.doc.close()
        return self.get(book_id)

    def get(self, book_id: int) -> Book | None:
        row = self.conn.execute(f"SELECT {BOOK_COLUMNS} FROM books WHERE id = ?", (book_id,)).fetchone()
        return Book.from_row(row) if row else None

    def by_fingerprint(self, fp: str) -> Book | None:
        row = self.conn.execute(f"SELECT {BOOK_COLUMNS} FROM books WHERE fingerprint = ?", (fp,)).fetchone()
        return Book.from_row(row) if row else None

    def all_books(self, include_missing: bool = False) -> list[Book]:
        """Não carrega as capas: elas vêm sob demanda por cover() (bibliotecas grandes)."""
        where = "" if include_missing else " WHERE missing = 0"
        return [Book.from_row(r) for r in self.conn.execute(f"SELECT {BOOK_COLUMNS} FROM books{where}")]

    def cover(self, book_id: int) -> bytes | None:
        row = self.conn.execute("SELECT cover FROM books WHERE id = ?", (book_id,)).fetchone()
        return row["cover"] if row else None

    def set_missing(self, book_id: int, missing: bool) -> None:
        self.conn.execute("UPDATE books SET missing = ? WHERE id = ?", (int(missing), book_id))
        self.conn.commit()

    def last_read(self) -> Book | None:
        row = self.conn.execute(
            f"SELECT {BOOK_COLUMNS} FROM books WHERE last_opened IS NOT NULL AND missing = 0"
            " ORDER BY last_opened DESC LIMIT 1"
        ).fetchone()
        return Book.from_row(row) if row else None

    def mark_opened(self, book_id: int) -> None:
        self.conn.execute("UPDATE books SET last_opened = ? WHERE id = ?", (_now(), book_id))
        self.conn.commit()

    def save_reading_state(self, book_id: int, *, page: int, position: str | None, pages: int,
                           progress: float, font_size: float, zoom_mode: str, zoom: float,
                           two_pages: bool, extra_seconds: int = 0, pages_read: int = 0,
                           continuous: bool = False) -> None:
        now = _now()
        self.conn.execute(
            "UPDATE books SET page = ?, position = ?, pages = ?, progress = ?, font_size = ?,"
            " zoom_mode = ?, zoom = ?, two_pages = ?, continuous = ?, reading_seconds = reading_seconds + ?,"
            " progress_updated_at = ?,"
            " finished_at = CASE WHEN ? >= 0.999 AND finished = 0 THEN ? ELSE finished_at END,"
            " finished = CASE WHEN ? >= 0.999 THEN 1 ELSE finished END WHERE id = ?",
            (page, position, pages, progress, font_size, zoom_mode, zoom, int(two_pages), int(continuous),
             extra_seconds, now, progress, now, progress, book_id),
        )
        if extra_seconds or pages_read:
            self.log_reading(book_id, extra_seconds, pages_read, commit=False)
        self.conn.commit()

    def log_reading(self, book_id: int, seconds: int, pages: int, day: str | None = None,
                    commit: bool = True) -> None:
        self.conn.execute(
            "INSERT INTO reading_log (day, book_id, seconds, pages) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(day, book_id) DO UPDATE SET seconds = seconds + excluded.seconds,"
            " pages = pages + excluded.pages",
            (day or date.today().isoformat(), book_id, seconds, pages))
        if commit:
            self.conn.commit()

    def update_metadata(self, book_id: int, title: str, author: str, description: str | None = None,
                        cover: bytes | None = None) -> None:
        self.conn.execute("UPDATE books SET title = ?, author = ? WHERE id = ?", (title, author, book_id))
        if description is not None:
            self.conn.execute("UPDATE books SET description = ? WHERE id = ?", (description, book_id))
        if cover:
            self.conn.execute("UPDATE books SET cover = ? WHERE id = ?", (cover, book_id))
        book = self.get(book_id)
        self._store_series(book_id, title, book.path)
        self.conn.commit()

    def set_path(self, book_id: int, path: str) -> None:
        self.conn.execute("UPDATE books SET path = ?, fingerprint = ? WHERE id = ?",
                          (path, fingerprint(path), book_id))
        self.conn.commit()

    def set_flag(self, book_id: int, flag: str, value: bool) -> None:
        if flag not in {"favorite", "finished"}:
            raise ValueError(flag)
        self.conn.execute(f"UPDATE books SET {flag} = ? WHERE id = ?", (int(value), book_id))
        if flag == "finished":
            self.conn.execute("UPDATE books SET finished_at = ? WHERE id = ?",
                              (_now() if value else None, book_id))
        self.conn.commit()

    def reset_progress(self, book_id: int) -> None:
        self.conn.execute(
            "UPDATE books SET page = 0, position = NULL, progress = 0, finished = 0, finished_at = NULL,"
            " progress_updated_at = ? WHERE id = ?", (_now(), book_id))
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

    def add_bookmark(self, book_id: int, page: int, position: str | None, label: str, note: str,
                     uid: str | None = None, created_at: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO bookmarks (book_id, page, position, label, note, created_at, uuid)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (book_id, page, position, label, note, created_at or _now(), uid or uuid.uuid4().hex),
        )
        self.conn.commit()

    def update_bookmark_note(self, bookmark_id: int, note: str) -> None:
        self.conn.execute("UPDATE bookmarks SET note = ? WHERE id = ?", (note, bookmark_id))
        self.conn.commit()

    def remove_bookmark(self, bookmark_id: int) -> None:
        row = self.conn.execute("SELECT uuid FROM bookmarks WHERE id = ?", (bookmark_id,)).fetchone()
        self.conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
        if row and row["uuid"]:
            self._tombstone(row["uuid"])
        self.conn.commit()

    # --------------------------------------------------------------- grifos
    def highlights(self, book_id: int) -> list[Highlight]:
        rows = self.conn.execute(
            "SELECT h.*, b.title AS book_title FROM highlights h JOIN books b ON b.id = h.book_id"
            " WHERE h.book_id = ? ORDER BY h.page, h.id", (book_id,)).fetchall()
        return [Highlight.from_row(r) for r in rows]

    def all_highlights(self) -> list[Highlight]:
        rows = self.conn.execute(
            "SELECT h.*, b.title AS book_title FROM highlights h JOIN books b ON b.id = h.book_id"
            " ORDER BY h.created_at DESC").fetchall()
        return [Highlight.from_row(r) for r in rows]

    def add_highlight(self, book_id: int, page: int, position: str | None, color: str, text: str,
                      note: str = "", rects: list | None = None, uid: str | None = None,
                      created_at: str | None = None) -> str:
        uid = uid or uuid.uuid4().hex
        now = _now()
        self.conn.execute(
            "INSERT INTO highlights (uuid, book_id, page, position, color, text, note, rects, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, book_id, page, position, color, text, note, json.dumps(rects or []), created_at or now, now))
        self.conn.commit()
        return uid

    def update_highlight(self, highlight_id: int, *, color: str | None = None, note: str | None = None) -> None:
        if color is not None:
            self.conn.execute("UPDATE highlights SET color = ?, updated_at = ? WHERE id = ?",
                              (color, _now(), highlight_id))
        if note is not None:
            self.conn.execute("UPDATE highlights SET note = ?, updated_at = ? WHERE id = ?",
                              (note, _now(), highlight_id))
        self.conn.commit()

    def remove_highlight(self, highlight_id: int) -> None:
        row = self.conn.execute("SELECT uuid FROM highlights WHERE id = ?", (highlight_id,)).fetchone()
        self.conn.execute("DELETE FROM highlights WHERE id = ?", (highlight_id,))
        if row:
            self._tombstone(row["uuid"])
        self.conn.commit()

    def _tombstone(self, uid: str) -> None:
        """Registra exclusões para que a sincronização não as ressuscite em outro PC."""
        self.conn.execute("INSERT OR REPLACE INTO deletions (uuid, deleted_at) VALUES (?, ?)", (uid, _now()))

    def deleted_uuids(self) -> set[str]:
        return {r["uuid"] for r in self.conn.execute("SELECT uuid FROM deletions")}

    # -------------------------------------------------------------- coleções
    def collections(self) -> list[Collection]:
        rows = self.conn.execute(
            "SELECT c.id, c.name, COUNT(b.id) AS count FROM collections c"
            " LEFT JOIN collection_books cb ON cb.collection_id = c.id"
            " LEFT JOIN books b ON b.id = cb.book_id AND b.missing = 0"
            " GROUP BY c.id ORDER BY c.name COLLATE NOCASE").fetchall()
        return [Collection(r["id"], r["name"], r["count"]) for r in rows]

    def create_collection(self, name: str) -> int:
        self.conn.execute("INSERT OR IGNORE INTO collections (name, created_at) VALUES (?, ?)", (name.strip(), _now()))
        self.conn.commit()
        return self.conn.execute("SELECT id FROM collections WHERE name = ?", (name.strip(),)).fetchone()["id"]

    def rename_collection(self, collection_id: int, name: str) -> None:
        self.conn.execute("UPDATE collections SET name = ? WHERE id = ?", (name.strip(), collection_id))
        self.conn.commit()

    def delete_collection(self, collection_id: int) -> None:
        self.conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        self.conn.commit()

    def set_in_collection(self, collection_id: int, book_id: int, member: bool) -> None:
        if member:
            self.conn.execute("INSERT OR IGNORE INTO collection_books VALUES (?, ?)", (collection_id, book_id))
        else:
            self.conn.execute("DELETE FROM collection_books WHERE collection_id = ? AND book_id = ?",
                              (collection_id, book_id))
        self.conn.commit()

    def collection_book_ids(self, collection_id: int) -> set[int]:
        return {r["book_id"] for r in self.conn.execute(
            "SELECT book_id FROM collection_books WHERE collection_id = ?", (collection_id,))}

    def collections_of(self, book_id: int) -> set[int]:
        return {r["collection_id"] for r in self.conn.execute(
            "SELECT collection_id FROM collection_books WHERE book_id = ?", (book_id,))}

    # ---------------------------------------------------------- estatísticas
    def daily_reading(self) -> dict[str, dict]:
        rows = self.conn.execute(
            "SELECT day, SUM(seconds) AS seconds, SUM(pages) AS pages FROM reading_log GROUP BY day")
        return {r["day"]: {"seconds": r["seconds"], "pages": r["pages"]} for r in rows}

    def finished_dates(self) -> list[str]:
        return [r["finished_at"] for r in self.conn.execute(
            "SELECT finished_at FROM books WHERE finished = 1 AND finished_at IS NOT NULL")]

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
