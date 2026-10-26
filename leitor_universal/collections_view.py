"""Coleções criadas pelo usuário e séries detectadas automaticamente."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

from .library import Library
from .library_view import BookGrid, CoverCache
from .themes import Theme


class CollectionsView(QWidget):
    open_requested = Signal(int)
    book_action = Signal(str, int)

    def __init__(self, library: Library, covers: CoverCache, theme: Theme, parent=None):
        super().__init__(parent)
        self.library = library

        self.groups = QListWidget()
        self.groups.setMinimumWidth(220)
        self.groups.currentItemChanged.connect(lambda *_: self._show_selected())
        new_btn = QPushButton("＋ Nova coleção")
        new_btn.clicked.connect(self._new)
        self.rename_btn = QPushButton("Renomear")
        self.rename_btn.clicked.connect(self._rename)
        self.delete_btn = QPushButton("Excluir")
        self.delete_btn.clicked.connect(self._delete)
        buttons = QHBoxLayout()
        buttons.addWidget(self.rename_btn)
        buttons.addWidget(self.delete_btn)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(new_btn)
        left_layout.addWidget(self.groups, 1)
        left_layout.addLayout(buttons)

        self.title = QLabel()
        self.title.setObjectName("heading")
        self.hint = QLabel()
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        self.grid = BookGrid(library, covers, theme)
        self.grid.open_requested.connect(self.open_requested.emit)
        self.grid.action_requested.connect(self.book_action.emit)
        self.grid.changed.connect(self.refresh)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 0, 0, 0)
        right_layout.addWidget(self.title)
        right_layout.addWidget(self.hint)
        right_layout.addWidget(self.grid, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 900])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 12)
        heading = QLabel("Coleções e séries")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        layout.addWidget(splitter, 1)

    def set_theme(self, theme: Theme) -> None:
        self.grid.theme = theme
        self.grid.viewport().update()

    def _series(self) -> dict[str, list]:
        series: dict[str, list] = {}
        for book in self.library.all_books():
            if book.series:
                series.setdefault(book.series, []).append(book)
        return {name: books for name, books in series.items() if len(books) >= 2}

    def refresh(self) -> None:
        current = self.groups.currentItem().data(Qt.UserRole) if self.groups.currentItem() else None
        self.groups.blockSignals(True)
        self.groups.clear()
        self._add_header("Minhas coleções")
        collections = self.library.collections()
        for col in collections:
            self._add_item(f"📚  {col.name}  ({col.count})", ("col", col.id, col.name))
        if not collections:
            self._add_header("   Nenhuma coleção ainda", muted=True)
        self._add_header("Séries detectadas")
        series = self._series()
        for name in sorted(series, key=str.lower):
            self._add_item(f"🔢  {name}  ({len(series[name])})", ("serie", name, name))
        if not series:
            self._add_header("   Nenhuma série encontrada", muted=True)
        self.groups.blockSignals(False)
        target = 0
        for i in range(self.groups.count()):
            data = self.groups.item(i).data(Qt.UserRole)
            if data and (current is None or data[:2] == current[:2]):
                target = i
                break
        self.groups.setCurrentRow(target)
        self._show_selected()

    def _add_header(self, text: str, muted: bool = False) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.NoItemFlags)
        font = item.font()
        font.setBold(not muted)
        item.setFont(font)
        self.groups.addItem(item)

    def _add_item(self, text: str, data: tuple) -> None:
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, data)
        self.groups.addItem(item)

    def _selected(self):
        item = self.groups.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _show_selected(self) -> None:
        data = self._selected()
        is_collection = bool(data and data[0] == "col")
        self.rename_btn.setEnabled(is_collection)
        self.delete_btn.setEnabled(is_collection)
        if not data:
            self.title.setText("Crie uma coleção")
            self.hint.setText("Clique com o botão direito em um livro e use “Coleções” para organizá-lo.")
            self.grid.set_books([])
            return
        if is_collection:
            ids = self.library.collection_book_ids(data[1])
            books = [b for b in self.library.all_books() if b.id in ids]
            books.sort(key=lambda b: b.title.lower())
            self.hint.setText("Adicione livros pelo menu do botão direito → Coleções.")
        else:
            books = sorted(self._series().get(data[1], []), key=lambda b: (b.series_index or 0, b.title))
            self.hint.setText("Série detectada pelo título ou nome do arquivo, em ordem de volume.")
        self.title.setText(data[2])
        self.grid.set_books(books)

    def _new(self) -> None:
        name, ok = QInputDialog.getText(self, "Nova coleção", "Nome da coleção:")
        if ok and name.strip():
            self.library.create_collection(name)
            self.refresh()

    def _rename(self) -> None:
        data = self._selected()
        if data and data[0] == "col":
            name, ok = QInputDialog.getText(self, "Renomear coleção", "Novo nome:", text=data[2])
            if ok and name.strip():
                self.library.rename_collection(data[1], name)
                self.refresh()

    def _delete(self) -> None:
        data = self._selected()
        if data and data[0] == "col":
            answer = QMessageBox.question(
                self, "Excluir coleção", f"Excluir a coleção “{data[2]}”?\n\nOs livros continuam na biblioteca.")
            if answer == QMessageBox.Yes:
                self.library.delete_collection(data[1])
                self.refresh()
