"""Tela da biblioteca: estante com capas, progresso, busca, filtros e ordenação."""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
    QMenu, QPushButton, QStackedLayout, QStyle, QStyledItemDelegate, QToolButton, QVBoxLayout,
    QWidget,
)

from .library import Book, Library
from .themes import Theme

CARD_W, CARD_H, COVER_H = 176, 318, 236
FILTERS = {"todos": "Todos", "lendo": "Lendo", "novo": "Não iniciados",
           "concluido": "Concluídos", "favoritos": "Favoritos"}
SORTS = {
    "recentes": ("Lidos recentemente", lambda b: b.last_opened or b.added_at or "", True),
    "adicionados": ("Adicionados recentemente", lambda b: b.added_at or "", True),
    "titulo": ("Título", lambda b: b.title.lower(), False),
    "autor": ("Autor", lambda b: (b.author or "~").lower(), False),
    "progresso": ("Progresso", lambda b: b.progress, True),
}


class BookCardDelegate(QStyledItemDelegate):
    def __init__(self, view: "LibraryView"):
        super().__init__(view)
        self.view = view

    def sizeHint(self, option, index) -> QSize:
        return QSize(CARD_W, CARD_H)

    def paint(self, painter: QPainter, option, index) -> None:
        book: Book = index.data(Qt.UserRole)
        theme: Theme = self.view.theme
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

        # Capa
        cover_rect = QRect(rect.x() + 8, rect.y() + 8, rect.width() - 16, COVER_H - 16)
        pix = self.view.cover_for(book)
        path = QPainterPath()
        if pix and not pix.isNull():
            scaled = pix.scaled(cover_rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            target = QRect(0, 0, scaled.width(), scaled.height())
            target.moveCenter(cover_rect.center())
            target.moveBottom(cover_rect.bottom())
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
            painter.drawText(cover_rect, Qt.AlignCenter | Qt.TextWordWrap, book.title)

        # Selo de formato
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

        # Textos
        y = rect.y() + COVER_H
        text_rect = QRect(rect.x() + 8, y, rect.width() - 16, 36)
        painter.setFont(_font(9, bold=True))
        painter.setPen(QColor(theme.text))
        title = _elide_lines(painter, book.title, text_rect.width(), 2)
        painter.drawText(text_rect, Qt.AlignTop | Qt.AlignLeft, title)
        title_h = painter.fontMetrics().lineSpacing() * (title.count("\n") + 1)
        painter.setFont(_font(8))
        painter.setPen(QColor(theme.muted))
        author_rect = QRect(rect.x() + 8, y + title_h + 2, rect.width() - 16, 16)
        painter.drawText(author_rect, Qt.AlignLeft,
                         painter.fontMetrics().elidedText(book.author or "Autor desconhecido",
                                                          Qt.ElideRight, author_rect.width()))

        # Progresso
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


class LibraryView(QWidget):
    open_requested = Signal(int)
    add_files_requested = Signal()
    add_folder_requested = Signal()
    remove_requested = Signal(int)
    locate_requested = Signal(int)
    reveal_requested = Signal(int)
    edit_requested = Signal(int)
    check_updates_requested = Signal()
    about_requested = Signal()

    def __init__(self, library: Library, theme: Theme, parent=None):
        super().__init__(parent)
        self.library = library
        self.theme = theme
        self._covers: dict[int, QPixmap] = {}

        title = QLabel("Minha biblioteca")
        title.setObjectName("heading")
        self.stats_label = QLabel()
        self.stats_label.setObjectName("muted")
        self.continue_btn = QPushButton("▶  Continuar leitura")
        self.continue_btn.setObjectName("primary")
        self.continue_btn.clicked.connect(self._continue)
        add_files = QPushButton("＋ Adicionar livros")
        add_files.clicked.connect(self.add_files_requested.emit)
        add_folder = QPushButton("📁 Adicionar pasta")
        add_folder.clicked.connect(self.add_folder_requested.emit)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(title)
        titles.addWidget(self.stats_label)
        header.addLayout(titles)
        header.addStretch(1)
        header.addWidget(add_folder)
        header.addWidget(add_files)
        header.addWidget(self.continue_btn)
        self.menu_btn = QToolButton()
        self.menu_btn.setText("⋮")
        self.menu_btn.setToolTip("Mais opções")
        self.menu_btn.setPopupMode(QToolButton.InstantPopup)
        options = QMenu(self.menu_btn)
        options.addAction("Verificar atualizações", self.check_updates_requested.emit)
        options.addAction("Sobre o Leitor Universal", self.about_requested.emit)
        self.menu_btn.setMenu(options)
        header.addWidget(self.menu_btn)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por título, autor ou formato…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
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
        controls.addWidget(self.filter_combo)
        controls.addWidget(self.sort_combo)

        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setGridSize(QSize(CARD_W + 8, CARD_H + 8))
        self.grid.setSpacing(4)
        self.grid.setMouseTracking(True)
        self.grid.setItemDelegate(BookCardDelegate(self))
        self.grid.itemActivated.connect(lambda it: self.open_requested.emit(it.data(Qt.UserRole).id))
        self.grid.itemDoubleClicked.connect(lambda it: self.open_requested.emit(it.data(Qt.UserRole).id))
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._context_menu)

        self.empty = QLabel(
            "<div style='font-size:42px'>📚</div>"
            "<p style='font-size:16px'><b>Sua biblioteca está vazia</b></p>"
            "<p>Arraste arquivos ou pastas para esta janela,<br/>ou use “Adicionar livros”.</p>"
            "<p style='font-size:11px'>PDF · EPUB · MOBI/AZW · FB2 · XPS · CBZ/CBR · DOCX · TXT · MD · RTF · "
            "HTML · imagens · DOC/ODT/PPTX (com LibreOffice)</p>"
        )
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setObjectName("muted")
        self.stack = QStackedLayout()
        self.stack.addWidget(self.grid)
        self.stack.addWidget(self.empty)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 12)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addLayout(controls)
        layout.addLayout(self.stack, 1)
        self.refresh()

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.grid.viewport().update()

    def cover_for(self, book: Book) -> QPixmap | None:
        if book.id not in self._covers:
            pix = QPixmap()
            if book.cover:
                pix.loadFromData(book.cover)
            self._covers[book.id] = pix
        return self._covers[book.id]

    def refresh(self) -> None:
        books = self.library.all_books()
        query = self.search.text().strip().lower()
        if query:
            books = [b for b in books if query in f"{b.title} {b.author} {b.kind}".lower()]
        flt = self.filter_combo.currentData()
        if flt == "favoritos":
            books = [b for b in books if b.favorite]
        elif flt != "todos":
            books = [b for b in books if b.status == flt]
        _, key, reverse = SORTS[self.sort_combo.currentData()]
        books.sort(key=key, reverse=reverse)

        self.grid.clear()
        for book in books:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, book)
            item.setToolTip(f"{book.title}\n{book.author}\n{book.path}")
            self.grid.addItem(item)

        stats = self.library.stats()
        hours = stats["seconds"] / 3600
        self.stats_label.setText(
            f"{stats['total']} livro(s)  ·  {stats['finished']} concluído(s)  ·  "
            f"{hours:.1f} h de leitura registradas"
        )
        self.stack.setCurrentWidget(self.empty if stats["total"] == 0 else self.grid)
        last = self.library.last_read()
        self.continue_btn.setVisible(last is not None)
        if last:
            self.continue_btn.setToolTip(f"{last.title} — {last.progress:.0%}")

    def invalidate_cover(self, book_id: int) -> None:
        self._covers.pop(book_id, None)

    def _continue(self) -> None:
        last = self.library.last_read()
        if last:
            self.open_requested.emit(last.id)

    def _context_menu(self, pos) -> None:
        item = self.grid.itemAt(pos)
        if not item:
            return
        book: Book = item.data(Qt.UserRole)
        menu = QMenu(self)
        actions = {
            menu.addAction("Abrir"): lambda: self.open_requested.emit(book.id),
            menu.addAction("Remover dos favoritos" if book.favorite else "★ Favoritar"):
                lambda: self.library.set_flag(book.id, "favorite", not book.favorite),
            menu.addAction("Marcar como não lido" if book.finished else "Marcar como lido"):
                lambda: self.library.set_flag(book.id, "finished", not book.finished),
            menu.addAction("Recomeçar do início"): lambda: self.library.reset_progress(book.id),
            menu.addAction("Editar título/autor…"): lambda: self.edit_requested.emit(book.id),
        }
        menu.addSeparator()
        actions[menu.addAction("Mostrar no Explorer")] = lambda: self.reveal_requested.emit(book.id)
        actions[menu.addAction("Localizar arquivo…")] = lambda: self.locate_requested.emit(book.id)
        actions[menu.addAction("Remover da biblioteca")] = lambda: self.remove_requested.emit(book.id)
        chosen = menu.exec(self.grid.viewport().mapToGlobal(pos))
        if chosen in actions:
            actions[chosen]()
            self.refresh()
