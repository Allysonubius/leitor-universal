"""Backup/restauração da biblioteca e sincronização entre PCs por uma pasta na nuvem.

Sincronização: cada PC grava `<pasta>/LeitorUniversal-sync/<dispositivo>.json` com o progresso,
marcadores, grifos e coleções, identificando livros pela impressão digital do arquivo (o
mesmo livro em PCs diferentes, mesmo em caminhos diferentes). Ao sincronizar, os arquivos
dos outros PCs são mesclados: vence o progresso mais recente; anotações são unidas e as
exclusões propagadas.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import __version__
from .library import Library

SYNC_DIR_NAME = "LeitorUniversal-sync"
BACKUP_DB_NAME = "biblioteca.db"


# ------------------------------------------------------------------ backup
def create_backup(library: Library, destination: Path) -> Path:
    """Cópia consistente do banco (API de backup do SQLite) compactada em .zip."""
    destination = Path(destination)
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / BACKUP_DB_NAME
        target = sqlite3.connect(copy)
        library.conn.backup(target)
        target.close()
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(copy, BACKUP_DB_NAME)
            zf.writestr("backup.json", json.dumps({
                "app": "Leitor Universal", "versao": __version__,
                "criado_em": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False))
    return destination


def validate_backup(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as zf:
            if BACKUP_DB_NAME not in zf.namelist():
                raise ValueError
            info = json.loads(zf.read("backup.json")) if "backup.json" in zf.namelist() else {}
            with tempfile.TemporaryDirectory() as tmp:
                db = Path(zf.extract(BACKUP_DB_NAME, tmp))
                conn = sqlite3.connect(db)
                books = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
                conn.close()
    except (zipfile.BadZipFile, ValueError, sqlite3.DatabaseError, KeyError) as exc:
        raise ValueError("Este arquivo não é um backup válido do Leitor Universal.") from exc
    info["livros"] = books
    return info


def restore_backup(path: Path, data_dir: Path) -> None:
    """Substitui o banco atual (chame com a biblioteca fechada). Guarda uma cópia do anterior."""
    validate_backup(path)
    db = data_dir / BACKUP_DB_NAME
    if db.exists():
        shutil.copy2(db, data_dir / f"biblioteca-antes-da-restauracao-{datetime.now():%Y%m%d-%H%M%S}.db")
    for suffix in ("-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    with zipfile.ZipFile(path) as zf, zf.open(BACKUP_DB_NAME) as src, open(db, "wb") as out:
        shutil.copyfileobj(src, out)


# ---------------------------------------------------------- sincronização
@dataclass
class SyncResult:
    devices: int = 0
    progress: int = 0
    annotations: int = 0
    removed: int = 0


def device_id(library: Library) -> str:
    value = library.setting("dispositivo_id")
    if not value:
        value = f"{os.environ.get('COMPUTERNAME', 'pc')}-{uuid.uuid4().hex[:8]}"
        library.set_setting("dispositivo_id", value)
    return value


def export_state(library: Library) -> dict:
    conn = library.conn
    books = {}
    for row in conn.execute(
            "SELECT fingerprint, title, page, position, progress, progress_updated_at, finished, finished_at,"
            " favorite FROM books"):
        books[row["fingerprint"]] = dict(row)
    fp_of = {r["id"]: r["fingerprint"] for r in conn.execute("SELECT id, fingerprint FROM books")}
    bookmarks = [dict(r, fingerprint=fp_of[r["book_id"]]) for r in conn.execute(
        "SELECT uuid, book_id, page, position, label, note, created_at FROM bookmarks")]
    highlights = [dict(r, fingerprint=fp_of[r["book_id"]]) for r in conn.execute(
        "SELECT uuid, book_id, page, position, color, text, note, rects, created_at, updated_at FROM highlights")]
    collections: dict[str, list[str]] = {}
    for r in conn.execute("SELECT c.name, cb.book_id FROM collections c"
                          " LEFT JOIN collection_books cb ON cb.collection_id = c.id"):
        collections.setdefault(r["name"], [])
        if r["book_id"] in fp_of:
            collections[r["name"]].append(fp_of[r["book_id"]])
    for item in bookmarks + highlights:
        item.pop("book_id")
    return {
        "formato": 1, "dispositivo": device_id(library), "versao": __version__,
        "exportado_em": datetime.now().isoformat(timespec="seconds"),
        "livros": books, "marcadores": bookmarks, "grifos": highlights,
        "colecoes": collections, "exclusoes": sorted(library.deleted_uuids()),
    }


def merge_state(library: Library, data: dict) -> SyncResult:
    conn = library.conn
    result = SyncResult(devices=1)
    local = {r["fingerprint"]: r for r in conn.execute(
        "SELECT id, fingerprint, progress_updated_at FROM books")}

    for fp, remote in data.get("livros", {}).items():
        mine = local.get(fp)
        if not mine or not remote.get("progress_updated_at"):
            continue
        if (mine["progress_updated_at"] or "") < remote["progress_updated_at"]:
            conn.execute(
                "UPDATE books SET page = ?, position = ?, progress = ?, finished = ?, finished_at = ?,"
                " progress_updated_at = ?, favorite = MAX(favorite, ?) WHERE id = ?",
                (remote["page"], remote["position"], remote["progress"], remote["finished"],
                 remote["finished_at"], remote["progress_updated_at"], remote.get("favorite", 0), mine["id"]))
            result.progress += 1

    deleted_here = library.deleted_uuids()
    for uid in data.get("exclusoes", []):
        if uid in deleted_here:
            continue
        cur1 = conn.execute("DELETE FROM bookmarks WHERE uuid = ?", (uid,))
        cur2 = conn.execute("DELETE FROM highlights WHERE uuid = ?", (uid,))
        result.removed += cur1.rowcount + cur2.rowcount
        conn.execute("INSERT OR REPLACE INTO deletions (uuid, deleted_at) VALUES (?, ?)",
                     (uid, datetime.now().isoformat(timespec="seconds")))
    deleted_here = library.deleted_uuids()

    existing_bm = {r["uuid"] for r in conn.execute("SELECT uuid FROM bookmarks")}
    for bm in data.get("marcadores", []):
        mine = local.get(bm["fingerprint"])
        if mine and bm["uuid"] not in existing_bm and bm["uuid"] not in deleted_here:
            conn.execute("INSERT INTO bookmarks (book_id, page, position, label, note, created_at, uuid)"
                         " VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (mine["id"], bm["page"], bm["position"], bm["label"], bm["note"], bm["created_at"], bm["uuid"]))
            result.annotations += 1

    existing_hl = {r["uuid"]: r["updated_at"] for r in conn.execute("SELECT uuid, updated_at FROM highlights")}
    for hl in data.get("grifos", []):
        mine = local.get(hl["fingerprint"])
        if not mine or hl["uuid"] in deleted_here:
            continue
        if hl["uuid"] not in existing_hl:
            conn.execute(
                "INSERT INTO highlights (uuid, book_id, page, position, color, text, note, rects, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (hl["uuid"], mine["id"], hl["page"], hl["position"], hl["color"], hl["text"], hl["note"],
                 hl["rects"], hl["created_at"], hl["updated_at"]))
            result.annotations += 1
        elif (existing_hl[hl["uuid"]] or "") < (hl["updated_at"] or ""):
            conn.execute("UPDATE highlights SET color = ?, note = ?, updated_at = ? WHERE uuid = ?",
                         (hl["color"], hl["note"], hl["updated_at"], hl["uuid"]))
            result.annotations += 1

    for name, fingerprints in data.get("colecoes", {}).items():
        col_id = library.create_collection(name)
        for fp in fingerprints:
            if fp in local:
                conn.execute("INSERT OR IGNORE INTO collection_books VALUES (?, ?)", (col_id, local[fp]["id"]))
    conn.commit()
    return result


def sync_folder(library: Library, folder: str | Path) -> SyncResult:
    """Mescla os arquivos dos outros PCs e grava o deste. Seguro de chamar com frequência."""
    target = Path(folder) / SYNC_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)
    me = device_id(library)
    total = SyncResult()
    for path in sorted(target.glob("*.json")):
        if path.stem == me:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # arquivo sendo baixado pela nuvem; tenta na próxima
        if data.get("formato") != 1:
            continue
        part = merge_state(library, data)
        total.devices += part.devices
        total.progress += part.progress
        total.annotations += part.annotations
        total.removed += part.removed
    own = target / f"{me}.json"
    tmp = own.with_suffix(".tmp")
    tmp.write_text(json.dumps(export_state(library), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, own)
    return total
