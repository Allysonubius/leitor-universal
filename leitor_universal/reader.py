"""Tela de leitura: renderização de páginas, navegação, sumário, marcadores e busca."""
from __future__ import annotations

import time
from collections import OrderedDict

import pymupdf
from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QPushButton, QScrollArea, QSizePolicy, QSlider, QSplitter, QTabWidget,
    QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .documents import LoadedDocument
from .library import Book, Library
from .themes import THEMES, Theme

PAGE_GAP = 16          # espaço entre páginas no modo duplo (px lógicos)
VIEW_MARGIN = 24       # margem em volta da página
IDLE_LIMIT = 180       # segundos sem interação que interrompem a contagem de tempo
TICK_SECONDS = 15
ZOOM_MODES = {"largura": "Ajustar à largura", "pagina": "Página inteira", "livre": "Zoom livre"}


class ReaderWidget(QWidget):
    back_requested = Signal()
    fullscreen_requested = Signal()
    theme_changed = Signal(str)

    def __init__(self, library: Library, parent: QWidget | None = None):
        super().__init__(parent)
        self.library = library
        self.book: Book | None = None
        self.ldoc: LoadedDocument | None = None
        self.doc: pymupdf.Document | None = None
        self.page_index = 0
        self.zoom_mode = "pagina"
        self.zoom = 1.0
        self.two_pages = False
        self.font_size = 12.0
        self.theme: Theme = THEMES["claro"]
        self._layout_key = None
        self._layout_version = 0
        self._cache: OrderedDict = OrderedDict()
        self._toc_items: list[tuple[int, QTreeWidgetItem]] = []
        self._search_hits: dict[int, list[pymupdf.Rect]] = {}
        self._search_results: list[tuple[int, pymupdf.Rect]] = []
        self._search_state = None
        self._search_version = 0
        self._current_hit = -1
        self._wheel_accum = 0
        self._drag_origin: QPoint | None = None
        self._drag_scroll = (0, 0)
        self._last_interaction = time.monotonic()
        self._pending_seconds = 0

        self._build_ui()
        self._build_shortcuts()

        self._save_timer = QTimer(self, singleShot=True, interval=800, timeout=self.save_state)
        self._resize_timer = QTimer(self, singleShot=True, interval=150, timeout=self._on_resized)
        self._search_timer = QTimer(self, interval=0, timeout=self._search_step)
        self._clock = QTimer(self, interval=TICK_SECONDS * 1000, timeout=self._tick)
        self._clock.start()

    # ================================================================ UI
    def _build_ui(self) -> None:
        tb = QToolBar(self)
        tb.setMovable(False)
        self.toolbar = tb
        self.act_back = tb.addAction("← Biblioteca", self.back_requested.emit)
        self.act_panel = tb.addAction("☰ Painel", self._toggle_panel)
        self.act_panel.setCheckable(True)
        self.act_panel.setChecked(True)
        tb.addSeparator()
        self.title_label = QLabel()
        self.title_label.setObjectName("muted")
        self.title_label.setMinimumWidth(80)
        tb.addWidget(self.title_label)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        self.act_font_down = tb.addAction("A−", lambda: self._change_font(-1))
        self.act_font_up = tb.addAction("A+", lambda: self._change_font(+1))
        self.act_font_down.setToolTip("Diminuir fonte (livros refluíveis)")
        self.act_font_up.setToolTip("Aumentar fonte (livros refluíveis)")
        tb.addSeparator()
        tb.addAction("−", lambda: self._zoom_by(1 / 1.15)).setToolTip("Reduzir zoom (Ctrl + roda)")
        self.zoom_combo = QComboBox()
        self.zoom_combo.addItems(list(ZOOM_MODES.values()))
        self.zoom_combo.currentIndexChanged.connect(self._zoom_mode_selected)
        tb.addWidget(self.zoom_combo)
        tb.addAction("+", lambda: self._zoom_by(1.15)).setToolTip("Aumentar zoom (Ctrl + roda)")
        self.act_two = tb.addAction("▯▯ Duas páginas", self._toggle_two_pages)
        self.act_two.setCheckable(True)
        tb.addSeparator()
        self.theme_combo = QComboBox()
        for t in THEMES.values():
            self.theme_combo.addItem(t.label, t.key)
        self.theme_combo.currentIndexChanged.connect(
            lambda: self.theme_changed.emit(self.theme_combo.currentData()))
        tb.addWidget(self.theme_combo)
        tb.addAction("🔖 Marcar", self.add_bookmark).setToolTip("Adicionar marcador (Ctrl+D)")
        tb.addAction("⛶", self.fullscreen_requested.emit).setToolTip("Tela cheia (F11)")

        # Painel lateral
        self.side = QTabWidget()
        self.side.setMinimumWidth(220)
        self.toc_tree = QTreeWidget()
        self.toc_tree.setHeaderHidden(True)
        self.toc_tree.itemActivated.connect(self._toc_activated)
        self.toc_tree.itemClicked.connect(self._toc_activated)
        self.side.addTab(self.toc_tree, "Sumário")

        bm_panel = QWidget()
        bm_layout = QVBoxLayout(bm_panel)
        bm_layout.setContentsMargins(4, 4, 4, 4)
        self.bm_list = QListWidget()
        self.bm_list.setWordWrap(True)
        self.bm_list.itemClicked.connect(self._bookmark_activated)
        self.bm_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.bm_list.customContextMenuRequested.connect(self._bookmark_menu)
        add_bm = QPushButton("Adicionar marcador nesta página")
        add_bm.clicked.connect(self.add_bookmark)
        bm_layout.addWidget(self.bm_list)
        bm_layout.addWidget(add_bm)
        self.side.addTab(bm_panel, "Marcadores")

        search_panel = QWidget()
        s_layout = QVBoxLayout(search_panel)
        s_layout.setContentsMargins(4, 4, 4, 4)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar no livro…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self.start_search)
        self.search_status = QLabel()
        self.search_status.setObjectName("muted")
        self.search_list = QListWidget()
        self.search_list.setWordWrap(True)
        self.search_list.itemClicked.connect(lambda it: self._goto_hit(self.search_list.row(it)))
        s_layout.addWidget(self.search_edit)
        s_layout.addWidget(self.search_status)
        s_layout.addWidget(self.search_list)
        self.side.addTab(search_panel, "Busca")

        # Área da página
        self.page_label = QLabel(alignment=Qt.AlignCenter)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.page_label)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.viewport().installEventFilter(self)
        self.scroll.viewport().setMouseTracking(True)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.side)
        self.splitter.addWidget(self.scroll)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([280, 1000])

        # Rodapé
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(1)
        self.slider.valueChanged.connect(self._slider_moved)
        self.page_edit = QLineEdit()
        self.page_edit.setFixedWidth(64)
        self.page_edit.setAlignment(Qt.AlignCenter)
        self.page_edit.returnPressed.connect(self._page_typed)
        self.status_label = QLabel()
        self.status_label.setObjectName("muted")
        footer = QHBoxLayout()
        footer.setContentsMargins(12, 4, 12, 6)
        footer.addWidget(QLabel("Página"))
        footer.addWidget(self.page_edit)
        footer.addWidget(self.slider, 1)
        footer.addWidget(self.status_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(tb)
        layout.addWidget(self.splitter, 1)
        layout.addLayout(footer)

    def _build_shortcuts(self) -> None:
        bindings = {
            ("Right", "PgDown", "Space", "N"): self.next_page,
            ("Left", "PgUp", "Shift+Space", "P"): self.prev_page,
            ("Home",): lambda: self.goto(0),
            ("End",): lambda: self.goto(self.doc.page_count - 1 if self.doc else 0),
            ("Ctrl+D",): self.add_bookmark,
            ("Ctrl+F",): self.focus_search,
            ("F3",): lambda: self._goto_hit(self._current_hit + 1),
            ("Shift+F3",): lambda: self._goto_hit(self._current_hit - 1),
            ("Ctrl+=", "Ctrl++"): lambda: self._zoom_by(1.15),
            ("Ctrl+-",): lambda: self._zoom_by(1 / 1.15),
            ("Ctrl+0",): lambda: self._set_zoom_mode("pagina"),
            ("Ctrl+B",): lambda: (self.act_panel.toggle(), self._toggle_panel()),
            ("F11",): self.fullscreen_requested.emit,
        }
        for keys, slot in bindings.items():
            for key in keys:
                sc = QShortcut(QKeySequence(key), self)
                sc.setContext(Qt.WidgetWithChildrenShortcut)
                sc.activated.connect(slot)

    # ========================================================= abrir/fechar
    def open_book(self, book: Book, loaded: LoadedDocument) -> None:
        self.close_book()
        self.book, self.ldoc, self.doc = book, loaded, loaded.doc
        self.font_size = book.font_size or 12.0
        self.two_pages = book.two_pages
        self.zoom = book.zoom or 1.0
        self.zoom_mode = book.zoom_mode or ("largura" if not loaded.reflowable and not loaded.image_based
                                             else "pagina")
        self._layout_key = None
        self._cache.clear()
        self._clear_search()
        self.title_label.setText(f"  {book.title}" + (f" — {book.author}" if book.author else ""))
        self.act_font_down.setEnabled(loaded.reflowable)
        self.act_font_up.setEnabled(loaded.reflowable)
        self.act_two.setChecked(self.two_pages)
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.setCurrentIndex(list(ZOOM_MODES).index(self.zoom_mode))
        self.zoom_combo.blockSignals(False)

        self._relayout()
        page = book.page
        if loaded.reflowable and book.position:
            page = self._page_from_position(book.position, fallback=page)
        self.page_index = max(0, min(page, self.doc.page_count - 1))
        self._load_toc()
        self._load_bookmarks()
        self._last_interaction = time.monotonic()
        self._pending_seconds = 0
        self.library.mark_opened(book.id)
        self.render()
        self.scroll.setFocus()

    def close_book(self) -> None:
        if not self.doc:
            return
        self._search_timer.stop()
        self.save_state()
        self.doc.close()
        self.book = self.ldoc = self.doc = None
        self._cache.clear()
        self.page_label.clear()

    def save_state(self) -> None:
        if not (self.book and self.doc):
            return
        count = self.doc.page_count
        visible_last = min(self.page_index + (2 if self.two_pages else 1), count)
        progress = visible_last / count if count else 0
        self.library.save_reading_state(
            self.book.id, page=self.page_index, position=self._position_of(self.page_index),
            pages=count, progress=progress, font_size=self.font_size, zoom_mode=self.zoom_mode,
            zoom=self.zoom, two_pages=self.two_pages, extra_seconds=self._pending_seconds,
        )
        self.book.reading_seconds += self._pending_seconds
        self.book.progress = progress
        self._pending_seconds = 0

    # ===================================================== posição estável
    def _position_of(self, page: int) -> str | None:
        """Posição independente de layout: 'capítulo:fração' (só livros refluíveis)."""
        if not (self.ldoc and self.ldoc.reflowable):
            return None
        chapter, in_chapter = self.doc.location_from_page_number(page)
        total = max(self.doc.chapter_page_count(chapter), 1)
        return f"{chapter}:{in_chapter / total:.6f}"

    def _page_from_position(self, position: str, fallback: int = 0) -> int:
        try:
            chapter_s, frac_s = position.split(":")
            chapter = min(int(chapter_s), self.doc.chapter_count - 1)
            total = self.doc.chapter_page_count(chapter)
            in_chapter = min(int(round(float(frac_s) * total)), total - 1)
            return self.doc.page_number_from_location((chapter, max(in_chapter, 0)))
        except Exception:
            return fallback

    def _relayout(self) -> None:
        """Repagina livros refluíveis (EPUB, MOBI, HTML...) conforme janela e fonte."""
        if not (self.ldoc and self.ldoc.reflowable):
            return
        vp = self.scroll.viewport().size()
        cols = 2 if self.two_pages else 1
        height = 600.0
        aspect = (max(vp.width(), 200) / cols) / max(vp.height(), 200)
        width = max(300.0, min(500.0, round(height * aspect / 10) * 10))
        key = (width, height, self.font_size)
        if key == self._layout_key:
            return
        position = self._position_of(self.page_index) if self._layout_key else None
        self.doc.layout(width=width, height=height, fontsize=self.font_size)
        self._layout_key = key
        self._layout_version += 1
        self._cache.clear()
        if position:
            self.page_index = self._page_from_position(position, self.page_index)
            self._clear_search()
            self._load_toc()
            self._load_bookmarks()

    # =========================================================== renderizar
    def _effective_zoom(self) -> float:
        rect = self.doc[self.page_index].rect
        vp = self.scroll.viewport().size()
        avail_w = max(vp.width() - VIEW_MARGIN, 50)
        avail_h = max(vp.height() - VIEW_MARGIN, 50)
        pages_w = rect.width * (2 if self.two_pages else 1)
        gap = PAGE_GAP if self.two_pages else 0
        fit_w = (avail_w - gap) / pages_w
        if self.zoom_mode == "largura":
            return fit_w
        if self.zoom_mode == "pagina":
            return min(fit_w, avail_h / rect.height)
        return self.zoom

    def _render_raw(self, index: int, zoom: float, dpr: float) -> QImage:
        key = (index, round(zoom, 4), dpr, self.theme.key, self._layout_version,
               self._search_version, self._current_hit)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        scale = zoom * dpr
        pix = self.doc[index].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        if not self.ldoc.image_based and self.theme.page_ink is not None:
            if self.theme.invert:
                pix.invert_irect()
            # tint_with mapeia preto → primeira cor e branco → segunda.
            pix.tint_with(self.theme.page_ink, self.theme.page_paper)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()

        hits = self._search_hits.get(index)
        if hits:
            current = self._search_results[self._current_hit] if self._current_hit >= 0 else None
            painter = QPainter(img)
            for r in hits:
                is_current = current is not None and current[0] == index and current[1] == r
                color = QColor(255, 140, 0, 130) if is_current else QColor(255, 220, 0, 100)
                painter.fillRect(int(r.x0 * scale), int(r.y0 * scale),
                                 int(r.width * scale) + 1, int(r.height * scale) + 1, color)
            painter.end()

        self._cache[key] = img
        while len(self._cache) > 10:
            self._cache.popitem(last=False)
        return img

    def render(self) -> None:
        if not self.doc:
            return
        count = self.doc.page_count
        self.page_index = max(0, min(self.page_index, count - 1))
        dpr = self.devicePixelRatioF()
        zoom = self._effective_zoom()
        indices = [self.page_index]
        if self.two_pages and self.page_index + 1 < count:
            indices.append(self.page_index + 1)
        images = [self._render_raw(i, zoom, dpr) for i in indices]

        if len(images) == 1:
            final = images[0].copy()
        else:
            gap = int(PAGE_GAP * dpr)
            w = sum(i.width() for i in images) + gap
            h = max(i.height() for i in images)
            final = QImage(w, h, QImage.Format_RGB888)
            final.fill(QColor(self.theme.reader_bg))
            p = QPainter(final)
            p.drawImage(0, (h - images[0].height()) // 2, images[0])
            p.drawImage(images[0].width() + gap, (h - images[1].height()) // 2, images[1])
            p.end()
        final.setDevicePixelRatio(dpr)
        self.page_label.setPixmap(QPixmap.fromImage(final))
        self.page_label.setStyleSheet(f"background: {self.theme.reader_bg};")
        self._update_status(indices)
        self._save_timer.start()

    def _update_status(self, indices: list[int]) -> None:
        count = self.doc.page_count
        shown = f"{indices[0] + 1}" if len(indices) == 1 else f"{indices[0] + 1}-{indices[-1] + 1}"
        self.page_edit.setText(shown)
        self.slider.blockSignals(True)
        self.slider.setMaximum(count)
        self.slider.setValue(self.page_index + 1)
        self.slider.blockSignals(False)
        progress = (indices[-1] + 1) / count
        parts = [f"de {count}", f"{progress:.0%}"]
        seconds = self.book.reading_seconds + self._pending_seconds
        start_progress = 1 / count
        if seconds > 120 and progress > start_progress and progress < 1:
            remaining = seconds * (1 - progress) / progress
            parts.append(f"~{_format_duration(remaining)} restantes")
        chapter = self._current_chapter_title()
        if chapter:
            parts.append(chapter)
        self.status_label.setText("  ·  ".join(parts))
        self._highlight_toc()

    # ============================================================ navegação
    def goto(self, index: int, at_bottom: bool = False) -> None:
        if not self.doc:
            return
        self.page_index = max(0, min(index, self.doc.page_count - 1))
        self._touch()
        self.render()
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum() if at_bottom else 0)

    def next_page(self) -> None:
        if self.doc:
            step = 2 if self.two_pages else 1
            if self.page_index + step < self.doc.page_count:
                self.goto(self.page_index + step)

    def prev_page(self, at_bottom: bool = False) -> None:
        if self.doc and self.page_index > 0:
            step = 2 if self.two_pages else 1
            self.goto(self.page_index - step, at_bottom=at_bottom)

    def _slider_moved(self, value: int) -> None:
        self.goto(value - 1)

    def _page_typed(self) -> None:
        text = self.page_edit.text().split("-")[0].strip()
        if text.isdigit():
            self.goto(int(text) - 1)
        self.scroll.setFocus()

    def _touch(self) -> None:
        self._last_interaction = time.monotonic()

    def _tick(self) -> None:
        active = (self.book is not None and self.isVisible()
                  and QApplication.activeWindow() is not None
                  and time.monotonic() - self._last_interaction < IDLE_LIMIT)
        if active:
            self._pending_seconds += TICK_SECONDS
            if self._pending_seconds >= 60:
                self.save_state()

    # ================================================================ zoom
    def _set_zoom_mode(self, mode: str) -> None:
        self.zoom_mode = mode
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.setCurrentIndex(list(ZOOM_MODES).index(mode))
        self.zoom_combo.blockSignals(False)
        self.render()

    def _zoom_mode_selected(self, idx: int) -> None:
        mode = list(ZOOM_MODES)[idx]
        if mode == "livre" and self.doc:
            self.zoom = self._effective_zoom()
        self._set_zoom_mode(mode)

    def _zoom_by(self, factor: float) -> None:
        if not self.doc:
            return
        self.zoom = max(0.2, min(self._effective_zoom() * factor, 8.0))
        self._set_zoom_mode("livre")

    def _change_font(self, delta: int) -> None:
        if self.ldoc and self.ldoc.reflowable:
            self.font_size = max(7.0, min(self.font_size + delta, 32.0))
            self._relayout()
            self.render()

    def _toggle_two_pages(self) -> None:
        self.two_pages = self.act_two.isChecked()
        self._relayout()
        self.render()

    def _toggle_panel(self) -> None:
        self.side.setVisible(self.act_panel.isChecked())
        self._resize_timer.start()

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(list(THEMES).index(theme.key))
        self.theme_combo.blockSignals(False)
        self._cache.clear()
        self.scroll.setStyleSheet(f"QScrollArea {{ background: {theme.reader_bg}; }}")
        self.render()

    def set_chrome_visible(self, visible: bool) -> None:
        """Esconde barras no modo tela cheia."""
        self.toolbar.setVisible(visible)
        self.side.setVisible(visible and self.act_panel.isChecked())

    # ====================================================== eventos de tela
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_timer.start()

    def _on_resized(self) -> None:
        if self.doc:
            self._relayout()
            self.render()

    def eventFilter(self, obj, event) -> bool:
        if obj is not self.scroll.viewport() or not self.doc:
            return super().eventFilter(obj, event)
        et = event.type()
        if et == QEvent.Wheel:
            self._touch()
            dy = event.angleDelta().y()
            if event.modifiers() & Qt.ControlModifier:
                self._zoom_by(1.1 if dy > 0 else 1 / 1.1)
                return True
            bar = self.scroll.verticalScrollBar()
            at_end = bar.value() >= bar.maximum()
            at_start = bar.value() <= bar.minimum()
            if (dy < 0 and at_end) or (dy > 0 and at_start):
                self._wheel_accum += dy
                if self._wheel_accum <= -120:
                    self._wheel_accum = 0
                    self.next_page()
                elif self._wheel_accum >= 120:
                    self._wheel_accum = 0
                    self.prev_page(at_bottom=True)
                return True
            self._wheel_accum = 0
        elif et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._drag_origin = event.position().toPoint()
            self._drag_scroll = (self.scroll.horizontalScrollBar().value(),
                                 self.scroll.verticalScrollBar().value())
            return True
        elif et == QEvent.MouseMove and self._drag_origin is not None:
            delta = event.position().toPoint() - self._drag_origin
            self.scroll.horizontalScrollBar().setValue(self._drag_scroll[0] - delta.x())
            self.scroll.verticalScrollBar().setValue(self._drag_scroll[1] - delta.y())
            return True
        elif et == QEvent.MouseButtonRelease and self._drag_origin is not None:
            moved = (event.position().toPoint() - self._drag_origin).manhattanLength()
            self._drag_origin = None
            if moved < 6:
                x = event.position().x() / max(self.scroll.viewport().width(), 1)
                if x < 0.3:
                    self.prev_page()
                elif x > 0.7:
                    self.next_page()
            return True
        return super().eventFilter(obj, event)

    # ============================================================= sumário
    def _load_toc(self) -> None:
        self.toc_tree.clear()
        self._toc_items = []
        try:
            toc = self.doc.get_toc(simple=True)
        except Exception:
            toc = []
        parents: dict[int, QTreeWidgetItem] = {}
        for level, title, page in toc:
            parent = parents.get(level - 1)
            item = QTreeWidgetItem([title.strip() or "(sem título)"])
            target = max(page - 1, 0)
            item.setData(0, Qt.UserRole, target)
            (parent.addChild(item) if parent else self.toc_tree.addTopLevelItem(item))
            parents[level] = item
            self._toc_items.append((target, item))
        if not toc:
            self.toc_tree.addTopLevelItem(QTreeWidgetItem(["Este livro não possui sumário."]))
        self.toc_tree.expandToDepth(0)

    def _toc_activated(self, item: QTreeWidgetItem) -> None:
        target = item.data(0, Qt.UserRole)
        if target is not None:
            self.goto(target)

    def _current_toc_item(self) -> QTreeWidgetItem | None:
        best = None
        for page, item in self._toc_items:
            if page <= self.page_index:
                best = item
        return best

    def _current_chapter_title(self) -> str:
        item = self._current_toc_item()
        return item.text(0) if item else ""

    def _highlight_toc(self) -> None:
        item = self._current_toc_item()
        if item:
            self.toc_tree.blockSignals(True)
            self.toc_tree.setCurrentItem(item)
            self.toc_tree.blockSignals(False)

    # ========================================================== marcadores
    def _load_bookmarks(self) -> None:
        self.bm_list.clear()
        if not self.book:
            return
        for bm in self.library.bookmarks(self.book.id):
            page = self._page_from_position(bm.position, bm.page) if bm.position else bm.page
            text = f"Pág. {page + 1}  ·  {bm.label}" if bm.label else f"Pág. {page + 1}"
            if bm.note:
                text += f"\n{bm.note}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, (bm.id, page, bm.note))
            item.setToolTip(f"Criado em {bm.created_at.replace('T', ' ')}")
            self.bm_list.addItem(item)
        if self.bm_list.count() == 0:
            placeholder = QListWidgetItem("Nenhum marcador. Use Ctrl+D para marcar a página atual.")
            placeholder.setFlags(Qt.NoItemFlags)
            self.bm_list.addItem(placeholder)

    def add_bookmark(self) -> None:
        if not self.book:
            return
        label = self._current_chapter_title() or self._page_snippet(self.page_index)
        note, ok = QInputDialog.getMultiLineText(
            self, "Novo marcador", f"Página {self.page_index + 1} — anotação (opcional):")
        if not ok:
            return
        self.library.add_bookmark(self.book.id, self.page_index, self._position_of(self.page_index),
                                  label, note.strip())
        self._load_bookmarks()
        self.side.setCurrentIndex(1)
        if not self.side.isVisible():
            self.act_panel.setChecked(True)
            self._toggle_panel()

    def _page_snippet(self, index: int) -> str:
        text = " ".join(self.doc[index].get_text().split())
        return (text[:60] + "…") if len(text) > 60 else text

    def _bookmark_activated(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole)
        if data:
            self.goto(data[1])

    def _bookmark_menu(self, pos) -> None:
        item = self.bm_list.itemAt(pos)
        data = item.data(Qt.UserRole) if item else None
        if not data:
            return
        bm_id, page, note = data
        menu = QMenu(self)
        act_go = menu.addAction("Ir para a página")
        act_edit = menu.addAction("Editar anotação…")
        act_del = menu.addAction("Remover marcador")
        chosen = menu.exec(self.bm_list.mapToGlobal(pos))
        if chosen == act_go:
            self.goto(page)
        elif chosen == act_edit:
            text, ok = QInputDialog.getMultiLineText(self, "Anotação", "Anotação:", note)
            if ok:
                self.library.update_bookmark_note(bm_id, text.strip())
                self._load_bookmarks()
        elif chosen == act_del:
            self.library.remove_bookmark(bm_id)
            self._load_bookmarks()

    # =============================================================== busca
    def focus_search(self) -> None:
        if not self.side.isVisible():
            self.act_panel.setChecked(True)
            self._toggle_panel()
        self.side.setCurrentIndex(2)
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _clear_search(self) -> None:
        self._search_timer.stop()
        self._search_hits = {}
        self._search_results = []
        self._search_version += 1
        self._current_hit = -1
        self._search_state = None
        self.search_list.clear()
        self.search_status.clear()

    def start_search(self) -> None:
        query = self.search_edit.text().strip()
        self._clear_search()
        if not (self.doc and query):
            self.render()
            return
        self._search_state = {"query": query, "page": 0}
        self.search_status.setText("Buscando…")
        self._search_timer.start()

    def _search_step(self) -> None:
        state = self._search_state
        if not state or not self.doc:
            self._search_timer.stop()
            return
        end = min(state["page"] + 15, self.doc.page_count)
        hits = dict(self._search_hits)
        for index in range(state["page"], end):
            page = self.doc[index]
            rects = page.search_for(state["query"])
            if not rects:
                continue
            hits[index] = rects
            for r in rects:
                line = page.get_textbox(pymupdf.Rect(0, r.y0 - 1, page.rect.width, r.y1 + 1))
                snippet = " ".join(line.split()) or state["query"]
                item = QListWidgetItem(f"Pág. {index + 1}: {snippet[:120]}")
                self.search_list.addItem(item)
                self._search_results.append((index, r))
        self._search_hits = hits
        self._search_version += 1
        state["page"] = end
        total = len(self._search_results)
        if end >= self.doc.page_count:
            self._search_timer.stop()
            self.search_status.setText(f"{total} resultado(s)." if total else "Nenhum resultado.")
            if total:
                self._goto_hit(0)
        else:
            self.search_status.setText(f"Buscando… página {end} de {self.doc.page_count} ({total})")

    def _goto_hit(self, idx: int) -> None:
        if not self._search_results:
            return
        idx %= len(self._search_results)
        self._current_hit = idx
        page, rect = self._search_results[idx]
        self.search_list.setCurrentRow(idx)
        if self.two_pages and page == self.page_index + 1:
            page = self.page_index
        self.goto(page)
        zoom = self._effective_zoom()
        bar = self.scroll.verticalScrollBar()
        bar.setValue(int(rect.y0 * zoom) - self.scroll.viewport().height() // 3)


def _format_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{max(minutes, 1)} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"
