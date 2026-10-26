"""Sincronização das pastas da biblioteca: encontra livros novos, alterados e removidos."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .library import Library, is_inside

log = logging.getLogger("leitor.scanner")


@dataclass
class ScanResult:
    added: int = 0
    updated: int = 0
    missing: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def find_files(folder: Path, extensions: set[str], recursive: bool):
    """Lista arquivos de livro, ignorando pastas sem permissão, ocultas e temporários do Office."""
    for root, dirs, files in os.walk(folder, onerror=lambda _: None):
        dirs[:] = [d for d in dirs if not d.startswith(".")] if recursive else []
        for name in files:
            if name.startswith(("~$", ".")):
                continue
            if os.path.splitext(name)[1].lower() in extensions:
                yield Path(root) / name


def scan(library: Library, extensions: set[str], recursive: bool,
         progress=None, cancelled=lambda: False) -> ScanResult:
    result = ScanResult()
    known = {os.path.normcase(b.path): b for b in library.all_books(include_missing=True)}
    known_ids = {b.id for b in known.values()}
    online = [f for f in library.folders() if Path(f).is_dir()]

    candidates = [f for folder in online for f in find_files(Path(folder), extensions, recursive)]
    seen: set[str] = set()
    for i, path in enumerate(candidates):
        if cancelled():
            return result
        if progress:
            progress(i, len(candidates), path.name)
        key = os.path.normcase(str(path.resolve()))
        seen.add(key)
        try:
            stat = path.stat()
            book = known.get(key)
            if book and not book.missing and book.size == stat.st_size and abs(book.mtime - stat.st_mtime) < 1:
                continue  # inalterado: nada a fazer
            if library.import_file(path).id not in known_ids:
                result.added += 1
            else:
                result.updated += 1
        except Exception as exc:
            log.warning("Não foi possível importar %s: %s", path, exc)
            result.errors.append((path.name, str(exc) or exc.__class__.__name__))

    # Livros de pastas acessíveis cujo arquivo sumiu ficam ocultos (progresso preservado).
    for key, book in known.items():
        if book.missing or key in seen:
            continue
        if any(is_inside(book.path, f) for f in online) and not Path(book.path).exists():
            library.set_missing(book.id, True)
            result.missing += 1
    if progress:
        progress(len(candidates), len(candidates), "")
    return result


class ScanThread(QThread):
    progress = Signal(int, int, str)
    finished_scan = Signal(object)  # ScanResult

    def __init__(self, data_dir: Path, extensions: set[str], recursive: bool, parent=None):
        super().__init__(parent)
        self.data_dir = data_dir
        self.extensions = extensions
        self.recursive = recursive

    def run(self) -> None:
        library = Library(self.data_dir)  # conexão própria: SQLite não é compartilhado entre threads
        try:
            result = scan(library, self.extensions, self.recursive,
                          progress=lambda d, t, n: self.progress.emit(d, t, n),
                          cancelled=self.isInterruptionRequested)
        except Exception as exc:
            log.exception("Falha na sincronização")
            result = ScanResult(errors=[("sincronização", str(exc))])
        finally:
            library.close()
        self.finished_scan.emit(result)
