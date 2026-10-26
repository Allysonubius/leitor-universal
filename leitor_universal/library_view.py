"""Estante de livros (componente reutilizável) e tela da Biblioteca."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListView, QListWidget,
    QListWidgetItem, QMenu, QPushButton, QStackedLayout, QStyle, QStyledItemDelegate, QToolButton,
    QVBoxLayout, QWidget,
)

from .library import Book, Library, is_inside
from .themes import Theme

CARD_W, CARD_H, COVER_H = 176, 318, 236
FILTERS = {"todos": "Todos", "lendo": "Lendo", "novo": "Não iniciados",
           "concluido": "Concluídos", "favoritos": "Favoritos"}
SORTS = {
    "recentes": ("Lidos recentemente", lambda b: b.last_opened or b.added_at or "", True),
    "adicionados": ("Adicionados recentemente", lambda b: b.added_at or "", True),
    "titulo": ("Título", lambda b: b.title.lower(), False),
    "autor": ("Autor", lambda b: (b.author or "~").lower(), False),
    "serie": ("Série", lambda b: ((b.series or "~").lower(), b.series_index or 0, b.title.lower()), False),
    "progresso": ("Progresso", lambda b: b.progress, True),
}
# Ações que dependem da janela principal (diálogos, Explorer, internet).
BOOK_ACTIONS = ("edit", "online", "reveal", "locate", "remove")


class CoverCache:
    """Capas decodificadas sob demanda e compartilhadas entre as telas."""

    def __init__(self, library: Library):
        self.library = library
        self._items: dict[int, QPixmap] = {}

    def get(self, book_id: int) -> QPixmap:
        if book_id not in self._items:
            pix = QPixmap()
            data = self.library.cover(book_id)
            if data:
                pix.loadFromData(data)
            self._items[book_id] = pix
        return self._items[book_id]

    def invalidate(self, book_id: int) -> None:
        self._items.pop(book_id, None)


class BookCardDelegate(QStyledItemDelegate):
    def __init__(self, grid: "BookGrid"):
        super().__init__(grid)
        self.grid = grid

    def sizeHint(self, option, index) -> QSize:
        return QSize(CARD_W, CARD_H)

    def paint(self, painter: QPainter, option, index) -> None:
        book: Book = index.data(Qt.UserRole)
        theme: Theme = self.grid.theme
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = option.rect.adjusted(6, 6, -6, -6)

        if option.state & (QStyle.State_Selected | QStyle.State_MouseOver):
            painter.setPen(Qt.NoPen)
            bg = QColor(theme.accent)
            bg.setAlpha(45 if option.state & QStyle.State_Selected else 22)
            painter.setBrush(bg)
            painter.drawRoundedRect(rect, 10, 10)

        cover_rect = QRect(rect.x() + 8, rect.y() + 8, rect.width() - 16, COVER_H - 16)
        pix = self.grid.covers.get(book.id)
        if not pix.isNull():
            scaled = pix.scaled(cover_rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            target = QRect(0, 0, scaled.width(), scaled.height())
            target.moveCenter(cover_rect.center())
            target.moveBottom(cover_rect.bottom())
            path = QPainterPath()
            path.addRoundedRect(target, 4, 4)
            painter.setClipPath(path)
            painter.drawPixmap(target, scaled)
            painter.setClipping(False)
            painter.setPen(QColor(0, 0, 0, 40))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(target, 4, 4)
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.reader_bg))
            painter.drawRoundedRect(cover_rect, 4, 4)
            painter.setPen(QColor(theme.muted))
            painter.drawText(cover_rect.adjusted(8, 8, -8, -8), Qt.AlignCenter | Qt.TextWordWrap, book.title)

        painter.setFont(_font(8, bold=True))
        badge = book.kind.upper()
        bw = painter.fontMetrics().horizontalAdvance(badge) + 10
        badge_rect = QRect(cover_rect.right() - bw - 4, cover_rect.y() + 4, bw, 16)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.drawRoundedRect(badge_rect, 4, 4)
        painter.setPen(QColor("white"))
        painter.drawText(badge_rect, Qt.AlignCenter, badge)
        if book.favorite:
            painter.setFont(_font(14))
            painter.setPen(QColor("#f5b301"))
            painter.drawText(QRect(cover_rect.x() + 6, cover_rect.y() + 2, 24, 24), Qt.AlignCenter, "★")

        y = rect.y() + COVER_H
        text_rect = QRect(rect.x() + 8, y, rect.width() - 16, 36)
        painter.setFont(_font(9, bold=True))
        painter.setPen(QColor(theme.text))
        title = _elide_lines(painter, book.title, text_rect.width(), 2)
        painter.drawText(text_rect, Qt.AlignTop | Qt.AlignLeft, title)
        title_h = painter.fontMetrics().lineSpacing() * (title.count("\n") + 1)
        painter.setFont(_font(8))
        painter.setPen(QColor(theme.muted))
        subtitle = book.author or "Autor desconhecido"
        if book.series:
            subtitle = f"{book.series} · nº {book.series_index:g}" if book.series_index else book.series
        author_rect = QRect(rect.x() + 8, y + title_h + 2, rect.width() - 16, 16)
        painter.drawText(author_rect, Qt.AlignLeft,
                         painter.fontMetrics().elidedText(subtitle, Qt.ElideRight, author_rect.width()))

        bar = QRect(rect.x() + 8, rect.bottom() - 14, rect.width() - 56, 4)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.reader_bg))
        painter.drawRoundedRect(bar, 2, 2)
        if book.progress > 0:
            done = QRect(bar)
            done.setWidth(max(4, int(bar.width() * min(book.progress, 1))))
            painter.setBrush(QColor("#2e9d55") if book.finished else QColor(theme.accent))
            painter.drawRoundedRect(done, 2, 2)
        painter.setPen(QColor(theme.muted))
        label = "✓ lido" if book.finished else (f"{book.progress:.0%}" if book.progress else "novo")
        painter.drawText(QRect(bar.right() + 6, bar.y() - 7, 44, 18), Qt.AlignRight | Qt.AlignVCenter, label)
        painter.restore()


def _font(size: int, bold: bool = False) -> QFont:
    f = QFont()
    f.setPointSize(size)
    f.setBold(bold)
    return f


def _elide_lines(painter: QPainter, text: str, width: int, lines: int) -> str:
    """Quebra o texto em até `lines` linhas, com reticências na última."""
    fm = painter.fontMetrics()
    words, out, i = text.split(), [], 0
    while i < len(words) and len(out) < lines - 1:
        current = words[i]
        i += 1
        while i < len(words) and fm.horizontalAdvance(f"{current} {words[i]}") <= width:
            current += f" {words[i]}"
            i += 1
        out.append(fm.elidedText(current, Qt.ElideRight, width))
    if i < len(words):
        out.append(fm.elidedText(" ".join(words[i:]), Qt.ElideRight, width))
    return "\n".join(out)


class BookGrid(QListWidget):
    """Grade de capas com menu de contexto; usada pela Biblioteca e pelas Coleções."""

    open_requested = Signal(int)
    action_requested = Signal(str, int)
    changed = Signal()

    def __init__(self, library: Library, covers: CoverCache, theme: Theme, parent=None):
        super().__init__(parent)
        self.library = library
        self.covers = covers
        self.theme = theme
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setGridSize(QSize(CARD_W + 8, CARD_H + 8))
        self.setSpacing(4)
        self.setMouseTracking(True)
        self.setItemDelegate(BookCardDelegate(self))
        self.itemActivated.connect(lambda it: self.open_requested.emit(it.data(Qt.UserRole).id))
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

    def set_books(self, books: list[Book]) -> None:
        self.setUpdatesEnabled(False)
        self.clear()
        for book in books:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, book)
            tip = f"{book.title}\n{book.author}\n{book.path}"
            if book.description:
                tip += "\n\n" + book.description[:400]
            item.setToolTip(tip)
            self.addItem(item)
        self.setUpdatesEnabled(True)

    def _context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if not item:
            return
        book: Book = item.data(Qt.UserRole)
        menu = QMenu(self)
        handlers = {
            menu.addAction("Abrir"): lambda: self.open_requested.emit(book.id),
            menu.addAction("Remover dos favoritos" if book.favorite else "★ Favoritar"):
                lambda: self.library.set_flag(book.id, "favorite", not book.favorite),
            menu.addAction("Marcar como não lido" if book.finished else "Marcar como lido"):
                lambda: self.library.set_flag(book.id, "finished", not book.finished),
            menu.addAction("Recomeçar do início"): lambda: self.library.reset_progress(book.id),
        }
        collections_menu = menu.addMenu("Coleções")
        member_of = self.library.collections_of(book.id)
        for col in self.library.collections():
            act = collections_menu.addAction(col.name)
            act.setCheckable(True)
            act.setChecked(col.id in member_of)
            handlers[act] = (lambda c=col.id, m=col.id in member_of:
                             self.library.set_in_collection(c, book.id, not m))
        collections_menu.addSeparator()
        handlers[collections_menu.addAction("Nova coleção…")] = lambda: self._new_collection(book.id)
        menu.addSeparator()
        labels = {"edit": "Editar título/autor…", "online": "Buscar capa e dados na internet…",
                  "reveal": "Mostrar no Explorer", "locate": "Localizar arquivo…",
                  "remove": "Remover da biblioteca"}
        for name in BOOK_ACTIONS:
            if name == "reveal":
                menu.addSeparator()
            handlers[menu.addAction(labels[name])] = lambda n=name: self.action_requested.emit(n, book.id)
        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen in handlers:
            handlers[chosen]()
            self.changed.emit()

    def _new_collection(self, book_id: int) -> None:
        name, ok = QInputDialog.getText(self, "Nova coleção", "Nome da coleção:")
        if ok and name.strip():
            self.library.set_in_collection(self.library.create_collection(name), book_id, True)


class LibraryView(QWidget):
    open_requested = Signal(int)
    add_files_requested = Signal()
    add_folder_requested = Signal()
    check_updates_requested = Signal()
    about_requested = Signal()
    sync_requested = Signal()
    book_action = Signal(str, int)

    def __init__(self, library: Library, covers: CoverCache, theme: Theme, parent=None):
        super().__init__(parent)
        self.library = library
        self.covers = covers
        self.theme = theme

        title = QLabel("Minha biblioteca")
        title.setObjectName("heading")
        self.stats_label = QLabel()
        self.stats_label.setObjectName("muted")
        self.continue_btn = QPushButton("▶  Continuar leitura")
        self.continue_btn.setObjectName("primary")
        self.continue_btn.clicked.connect(self._continue)
        self.sync_btn = QPushButton("⟳ Sincronizar")
        self.sync_btn.setToolTip("Procurar livros novos nas pastas da biblioteca")
        self.sync_btn.clicked.connect(self.sync_requested.emit)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(title)
        titles.addWidget(self.stats_label)
        header.addLayout(titles)
        header.addStretch(1)
        header.addWidget(self.sync_btn)
        header.addWidget(self.continue_btn)
        self.menu_btn = QToolButton()
        self.menu_btn.setText("⋮")
        self.menu_btn.setToolTip("Mais opções")
        self.menu_btn.setPopupMode(QToolButton.InstantPopup)
        options = QMenu(self.menu_btn)
        options.addAction("Abrir um arquivo avulso…", self.add_files_requested.emit)
        options.addAction("Adicionar pasta de livros…", self.add_folder_requested.emit)
        options.addAction("Verificar atualizações", self.check_updates_requested.emit)
        options.addAction("Sobre o Leitor Universal", self.about_requested.emit)
        self.menu_btn.setMenu(options)
        header.addWidget(self.menu_btn)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por título, autor, série ou formato…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.folder_combo = QComboBox()
        self.folder_combo.setMinimumWidth(160)
        self.folder_combo.currentIndexChanged.connect(self.refresh)
        self.filter_combo = QComboBox()
        for key, label in FILTERS.items():
            self.filter_combo.addItem(label, key)
        self.filter_combo.currentIndexChanged.connect(self.refresh)
        self.sort_combo = QComboBox()
        for key, (label, _, _) in SORTS.items():
            self.sort_combo.addItem(label, key)
        self.sort_combo.currentIndexChanged.connect(self.refresh)
        controls = QHBoxLayout()
        controls.addWidget(self.search, 1)
        controls.addWidget(self.folder_combo)
        controls.addWidget(self.filter_combo)
        controls.addWidget(self.sort_combo)

        self.grid = BookGrid(library, covers, theme)
        self.grid.open_requested.connect(self.open_requested.emit)
        self.grid.action_requested.connect(self.book_action.emit)
        self.grid.changed.connect(self.refresh)

        self.empty = QWidget()
        self.empty_text = QLabel()
        self.empty_text.setAlignment(Qt.AlignCenter)
        self.empty_text.setObjectName("muted")
        self.empty_btn = QPushButton("📁  Escolher pasta de livros")
        self.empty_btn.setObjectName("primary")
        self.empty_btn.clicked.connect(self.add_folder_requested.emit)
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_text)
        empty_layout.addWidget(self.empty_btn, 0, Qt.AlignCenter)
        empty_layout.addStretch(2)
        self.sync_label = QLabel()
        self.sync_label.setObjectName("muted")
        self.sync_label.hide()
        self.stack = QStackedLayout()
        self.stack.addWidget(self.grid)
        self.stack.addWidget(self.empty)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 12)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addLayout(controls)
        layout.addWidget(self.sync_label)
        layout.addLayout(self.stack, 1)
        self.refresh()

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.grid.theme = theme
        self.grid.viewport().update()

    def set_sync_status(self, text: str) -> None:
        self.sync_label.setText(text)
        self.sync_label.setVisible(bool(text))
        self.sync_btn.setEnabled(not text.startswith("Sincronizando"))

    def _reload_folders(self) -> None:
        current = self.folder_combo.currentData()
        self.folder_combo.blockSignals(True)
        self.folder_combo.clear()
        self.folder_combo.addItem("Todas as pastas", None)
        for folder in self.library.folders():
            self.folder_combo.addItem("📁 " + (Path(folder).name or folder), folder)
        self.folder_combo.addItem("Arquivos avulsos", "")
        index = self.folder_combo.findData(current)
        self.folder_combo.setCurrentIndex(max(index, 0))
        self.folder_combo.blockSignals(False)

    def refresh(self) -> None:
        self._reload_folders()
        books = self.library.all_books()
        folder = self.folder_combo.currentData()
        if folder:
            books = [b for b in books if is_inside(b.path, folder)]
        elif folder == "":
            folders = self.library.folders()
            books = [b for b in books if not any(is_inside(b.path, f) for f in folders)]
        query = self.search.text().strip().lower()
        if query:
            books = [b for b in books if query in f"{b.title} {b.author} {b.kind} {b.series or ''}".lower()]
        flt = self.filter_combo.currentData()
        if flt == "favoritos":
            books = [b for b in books if b.favorite]
        elif flt != "todos":
            books = [b for b in books if b.status == flt]
        _, key, reverse = SORTS[self.sort_combo.currentData()]
        books.sort(key=key, reverse=reverse)
        self.grid.set_books(books)

        stats = self.library.stats()
        self.stats_label.setText(
            f"{stats['total']} livro(s)  ·  {stats['finished']} concluído(s)  ·  "
            f"{stats['seconds'] / 3600:.1f} h de leitura registradas")
        has_folders = bool(self.library.folders())
        if stats["total"] == 0:
            self.empty_text.setText(
                "<div style='font-size:42px'>📚</div>"
                + ("<p style='font-size:16px'><b>Nenhum livro encontrado nas suas pastas</b></p>"
                   "<p>Verifique os formatos em Configurações ou escolha outra pasta.</p>"
                   if has_folders else
                   "<p style='font-size:16px'><b>Bem-vindo ao Leitor Universal</b></p>"
                   "<p>Escolha a pasta onde ficam seus livros. Tudo o que estiver nela<br/>"
                   "(PDF, EPUB, MOBI, quadrinhos, Word, TXT…) vira sua biblioteca.</p>"))
        self.stack.setCurrentWidget(self.empty if stats["total"] == 0 else self.grid)
        last = self.library.last_read()
        self.continue_btn.setVisible(last is not None)
        if last:
            self.continue_btn.setToolTip(f"{last.title} — {last.progress:.0%}")

    def invalidate_cover(self, book_id: int) -> None:
        self.covers.invalidate(book_id)

    def _continue(self) -> None:
        last = self.library.last_read()
        if last:
            self.open_requested.emit(last.id)
