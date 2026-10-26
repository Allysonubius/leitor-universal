"""Busca capa, autor e sinopse na Open Library e aplica ao livro escolhido."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout,
)

from . import online
from .library import Book, Library


class MetadataDialog(QDialog):
    def __init__(self, library: Library, book: Book, parent=None):
        super().__init__(parent)
        self.library = library
        self.book = book
        self.setWindowTitle("Buscar dados na internet")
        self.resize(640, 520)
        self._tasks: list[online.Task] = []
        self._thumbs: dict[int, bytes] = {}

        self.title_edit = QLineEdit(book.title)
        self.author_edit = QLineEdit(book.author)
        self.author_edit.setPlaceholderText("Autor (opcional)")
        search_btn = QPushButton("Buscar")
        search_btn.setObjectName("primary")
        search_btn.clicked.connect(self.search)
        self.title_edit.returnPressed.connect(self.search)
        row = QHBoxLayout()
        row.addWidget(self.title_edit, 2)
        row.addWidget(self.author_edit, 1)
        row.addWidget(search_btn)

        self.results = QListWidget()
        self.results.setIconSize(QSize(54, 80))
        self.results.setSpacing(2)
        self.status = QLabel("Fonte: Open Library (openlibrary.org).")
        self.status.setObjectName("muted")
        self.use_cover = QCheckBox("Usar a capa encontrada")
        self.use_cover.setChecked(True)
        self.use_text = QCheckBox("Usar título, autor e sinopse")
        self.use_text.setChecked(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Aplicar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.apply)
        buttons.rejected.connect(self.reject)
        self.apply_btn = buttons.button(QDialogButtonBox.Ok)
        self.apply_btn.setEnabled(False)
        self.results.currentItemChanged.connect(lambda *_: self.apply_btn.setEnabled(self._current() is not None))
        self.results.itemDoubleClicked.connect(lambda _: self.apply())

        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.results, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.use_cover)
        layout.addWidget(self.use_text)
        layout.addWidget(buttons)
        self.search()

    def _run(self, fn, *args, callback):
        task = online.Task(fn, *args, parent=self)
        task.done.connect(callback)
        self._tasks.append(task)
        task.start()

    def search(self) -> None:
        self.results.clear()
        self.status.setText("Buscando…")
        self._run(online.search_books, self.title_edit.text().strip(), self.author_edit.text().strip(),
                  callback=self._show_results)

    def _show_results(self, matches, error: str) -> None:
        if error:
            self.status.setText(error)
            return
        if not matches:
            self.status.setText("Nada encontrado. Tente só o título, sem subtítulo.")
            return
        self.status.setText(f"{len(matches)} resultado(s). Escolha o livro certo e clique em Aplicar.")
        for i, m in enumerate(matches):
            item = QListWidgetItem(f"{m.title}\n{m.author or 'Autor desconhecido'}"
                                   + (f" · {m.year}" if m.year else ""))
            item.setData(Qt.UserRole, m)
            self.results.addItem(item)
            if m.thumb_url:
                self._run(online.download, m.thumb_url,
                          callback=lambda data, err, row=i: self._set_thumb(row, data))
        self.results.setCurrentRow(0)

    def _set_thumb(self, row: int, data: bytes | None) -> None:
        item = self.results.item(row)
        if item and data:
            pix = QPixmap()
            pix.loadFromData(data)
            item.setIcon(QIcon(pix))

    def _current(self):
        item = self.results.currentItem()
        return item.data(Qt.UserRole) if item else None

    def apply(self) -> None:
        match = self._current()
        if not match:
            return
        self.apply_btn.setEnabled(False)
        self.status.setText("Baixando capa e sinopse…")
        want_cover = self.use_cover.isChecked() and match.cover_url

        def fetch():
            cover = online.download(match.cover_url) if want_cover else None
            description = online.book_description(match.work_key) if self.use_text.isChecked() else None
            return cover, description

        self._run(fetch, callback=lambda result, err: self._applied(match, result, err))

    def _applied(self, match, result, error: str) -> None:
        if error:
            self.status.setText(error)
            self.apply_btn.setEnabled(True)
            return
        cover, description = result
        if self.use_text.isChecked():
            self.library.update_metadata(self.book.id, match.title or self.book.title,
                                         match.author or self.book.author, description or "", cover)
        else:
            self.library.update_metadata(self.book.id, self.book.title, self.book.author, None, cover)
        self.accept()
