"""Anotações de todos os livros (grifos e marcadores) e exportação para Markdown."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .library import HIGHLIGHT_COLORS, Library

COLOR_NAMES = {"amarelo": "Amarelo", "verde": "Verde", "azul": "Azul", "rosa": "Rosa"}


def annotations_markdown(library: Library, book_id: int | None = None) -> str:
    """Grifos e marcadores agrupados por livro, prontos para colar em qualquer editor."""
    books = [library.get(book_id)] if book_id else library.all_books(include_missing=True)
    parts = [f"# Anotações — Leitor Universal\n\n_Exportado em {date.today():%d/%m/%Y}_\n"]
    for book in sorted((b for b in books if b), key=lambda b: b.title.lower()):
        highlights = library.highlights(book.id)
        bookmarks = library.bookmarks(book.id)
        if not highlights and not bookmarks:
            continue
        parts.append(f"## {book.title}" + (f" — {book.author}" if book.author else "") + "\n")
        for h in highlights:
            parts.append(f"> {h.text.strip()}\n>\n> — página {h.page + 1} · {COLOR_NAMES.get(h.color, h.color)}\n")
            if h.note:
                parts.append(f"**Nota:** {h.note}\n")
        if bookmarks:
            parts.append("### Marcadores\n")
            for bm in bookmarks:
                line = f"- Página {bm.page + 1}" + (f" — {bm.label}" if bm.label else "")
                parts.append(line + (f"\n  - {bm.note}" if bm.note else ""))
            parts.append("")
    if len(parts) == 1:
        parts.append("Nenhuma anotação ainda.")
    return "\n".join(parts).strip() + "\n"


def save_markdown(parent: QWidget, library: Library, book_id: int | None = None) -> None:
    name = "anotacoes" if book_id is None else f"anotacoes-{library.get(book_id).title[:40]}"
    safe = "".join(c for c in name if c.isalnum() or c in " -_").strip() or "anotacoes"
    path, _ = QFileDialog.getSaveFileName(parent, "Exportar anotações", str(Path.home() / f"{safe}.md"),
                                          "Markdown (*.md);;Texto (*.txt)")
    if path:
        Path(path).write_text(annotations_markdown(library, book_id), encoding="utf-8")
        QMessageBox.information(parent, "Anotações exportadas", f"Arquivo salvo em:\n{path}")


def color_icon(color: str) -> QIcon:
    pix = QPixmap(14, 14)
    pix.fill(QColor(HIGHLIGHT_COLORS.get(color, color)))
    return QIcon(pix)


class AnnotationsView(QWidget):
    open_at = Signal(int, int, str)  # livro, página, posição estável (pode ser vazia)

    def __init__(self, library: Library, parent=None):
        super().__init__(parent)
        self.library = library
        heading = QLabel("Anotações")
        heading.setObjectName("heading")
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        export_btn = QPushButton("⇩ Exportar tudo (Markdown)")
        export_btn.clicked.connect(lambda: save_markdown(self, self.library))
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(heading)
        titles.addWidget(self.summary)
        header.addLayout(titles)
        header.addStretch(1)
        header.addWidget(export_btn)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar nos grifos e notas…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.book_combo = QComboBox()
        self.book_combo.setMinimumWidth(220)
        self.book_combo.currentIndexChanged.connect(self.refresh)
        self.color_combo = QComboBox()
        self.color_combo.addItem("Todas as cores", None)
        for key, label in COLOR_NAMES.items():
            self.color_combo.addItem(color_icon(key), label, key)
        self.color_combo.currentIndexChanged.connect(self.refresh)
        controls = QHBoxLayout()
        controls.addWidget(self.search, 1)
        controls.addWidget(self.book_combo)
        controls.addWidget(self.color_combo)

        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setSpacing(4)
        self.list.itemActivated.connect(self._open)
        self.list.itemDoubleClicked.connect(self._open)
        hint = QLabel("Dê dois cliques para abrir o livro no trecho. Grife textos selecionando-os durante a leitura.")
        hint.setObjectName("muted")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 12)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addLayout(controls)
        layout.addWidget(self.list, 1)
        layout.addWidget(hint)

    def _reload_books(self, highlights) -> None:
        current = self.book_combo.currentData()
        self.book_combo.blockSignals(True)
        self.book_combo.clear()
        self.book_combo.addItem("Todos os livros", None)
        seen = {}
        for h in highlights:
            seen.setdefault(h.book_id, h.book_title)
        for book_id, title in sorted(seen.items(), key=lambda kv: kv[1].lower()):
            self.book_combo.addItem(title, book_id)
        self.book_combo.setCurrentIndex(max(self.book_combo.findData(current), 0))
        self.book_combo.blockSignals(False)

    def refresh(self) -> None:
        highlights = self.library.all_highlights()
        self._reload_books(highlights)
        book_id = self.book_combo.currentData()
        color = self.color_combo.currentData()
        query = self.search.text().strip().lower()
        shown = [h for h in highlights
                 if (book_id is None or h.book_id == book_id) and (color is None or h.color == color)
                 and (not query or query in f"{h.text} {h.note} {h.book_title}".lower())]
        self.list.clear()
        for h in shown:
            text = f"“{h.text.strip()}”\n{h.book_title} · página {h.page + 1}"
            if h.note:
                text += f"\n📝 {h.note}"
            item = QListWidgetItem(color_icon(h.color), text)
            item.setData(Qt.UserRole, (h.book_id, h.page, h.position or ""))
            self.list.addItem(item)
        if not shown:
            empty = QListWidgetItem("Nenhum grifo encontrado." if highlights else
                                    "Você ainda não grifou nenhum trecho. Selecione um texto durante a leitura "
                                    "e escolha uma cor.")
            empty.setFlags(Qt.NoItemFlags)
            self.list.addItem(empty)
        books = len({h.book_id for h in highlights})
        self.summary.setText(f"{len(highlights)} grifo(s) em {books} livro(s)")

    def _open(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole)
        if data:
            self.open_at.emit(*data)
