"""Tela de leitura: páginas (uma, duas ou rolagem contínua), seleção de texto, grifos,
marcadores, sumário, busca, leitura em voz alta, dicionário e tradução."""
from __future__ import annotations

import time
from bisect import bisect_right
from collections import OrderedDict

import pymupdf
from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSlider, QSplitter,
    QTabWidget, QTextBrowser, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import online
from .annotations_view import COLOR_NAMES, color_icon, save_markdown
from .documents import LoadedDocument
from .library import HIGHLIGHT_COLORS, Book, Highlight, Library
from .speech import Narrator
from .themes import THEMES, Theme

PAGE_GAP = 16          # espaço entre páginas (modo duplo e rolagem contínua)
VIEW_MARGIN = 24       # margem em volta da página
IDLE_LIMIT = 180       # segundos sem interação que interrompem a contagem de tempo
TICK_SECONDS = 15
ZOOM_MODES = {"largura": "Ajustar à largura", "pagina": "Página inteira", "livre": "Zoom livre"}
SELECTION_COLOR = QColor(60, 130, 255, 85)
RENDER_AHEAD = 2       # páginas renderizadas além das visíveis na rolagem contínua


def merge_line_rects(words: list) -> list[list[float]]:
    """Une os retângulos das palavras de uma mesma linha (grifo contínuo)."""
    lines: dict[tuple, list[float]] = {}
    for w in words:
        key = (w[5], w[6])
        r = lines.get(key)
        lines[key] = [w[0], w[1], w[2], w[3]] if r is None else [
            min(r[0], w[0]), min(r[1], w[1]), max(r[2], w[2]), max(r[3], w[3])]
    return list(lines.values())


def words_text(words: list) -> str:
    out, last = [], None
    for w in words:
        key = (w[5], w[6])
        if last is not None:
            out.append("\n" if key[0] != last[0] else " ")
        out.append(w[4])
        last = key
    return "".join(out)


def nearest_word(words: list, x: float, y: float) -> int | None:
    best, best_d = None, None
    for i, w in enumerate(words):
        dx = 0 if w[0] <= x <= w[2] else min(abs(x - w[0]), abs(x - w[2]))
        dy = 0 if w[1] <= y <= w[3] else min(abs(y - w[1]), abs(y - w[3]))
        d = dy * 4 + dx  # prioriza a linha certa
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


class LookupDialog(QDialog):
    """Janela pequena com a definição ou a tradução do trecho selecionado."""

    def __init__(self, title: str, query: str, fn, browser_url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 360)
        self.text = QTextBrowser()
        self.text.setOpenExternalLinks(True)
        self.text.setPlainText("Consultando…")
        header = QLabel(f"<b>{query[:200]}</b>")
        header.setWordWrap(True)
        open_btn = QPushButton("Abrir no navegador")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(browser_url)))
        close_btn = QPushButton("Fechar")
        close_btn.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addWidget(open_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout = QVBoxLayout(self)
        layout.addWidget(header)
        layout.addWidget(self.text, 1)
        layout.addLayout(buttons)
        self.task = online.Task(fn, query, parent=self)
        self.task.done.connect(lambda result, error: self.text.setPlainText(error or result))
        self.task.start()


class ReaderWidget(QWidget):
    back_requested = Signal()
    fullscreen_requested = Signal()
    theme_changed = Signal(str)
    annotations_changed = Signal()

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
        self.continuous = False
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
        self._last_interaction = time.monotonic()
        self._pending_seconds = 0
        self._pages_seen: set[int] = set()
        self._pages_read = 0
        # Geometria das páginas exibidas (para saber onde o mouse está no texto).
        self._page_geoms: list[tuple[int, QRect, float]] = []
        self._slots: list[QLabel] = []
        self._slot_y: list[int] = []
        self._slot_zoom: list[float] = []
        self._rendered: set[int] = set()
        # Seleção e grifos
        self._words: dict[int, list] = {}
        self._sel: dict | None = None
        self._press: dict | None = None
        self._pan: tuple | None = None
        self._highlights: list[Highlight] = []
        self._hl_cache: dict[int, list] = {}
        self._annot_version = 0
        self._tts_on = False

        self.narrator = Narrator(self)
        self.narrator.finished.connect(self._tts_page_done)
        self.narrator.error.connect(self._tts_error)

        self._build_ui()
        self._build_shortcuts()

        self._save_timer = QTimer(self, singleShot=True, interval=800, timeout=self.save_state)
        self._resize_timer = QTimer(self, singleShot=True, interval=150, timeout=self._on_resized)
        self._search_timer = QTimer(self, interval=0, timeout=self._search_step)
        self._visible_timer = QTimer(self, singleShot=True, interval=30, timeout=self._update_visible)
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

        self.act_tts = tb.addAction("🔊 Ouvir", self._toggle_tts)
        self.act_tts.setCheckable(True)
        self.act_tts.setToolTip("Ler em voz alta a partir desta página (F5)")
        tb.addSeparator()
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
        self.act_continuous = tb.addAction("⇕ Contínuo", self._toggle_continuous)
        self.act_continuous.setCheckable(True)
        self.act_continuous.setToolTip("Rolagem contínua: páginas em sequência")
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
        self.side.setMinimumWidth(240)
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
        self.bm_panel = bm_panel
        self.side.addTab(bm_panel, "Marcadores")

        hl_panel = QWidget()
        hl_layout = QVBoxLayout(hl_panel)
        hl_layout.setContentsMargins(4, 4, 4, 4)
        self.hl_list = QListWidget()
        self.hl_list.setWordWrap(True)
        self.hl_list.itemClicked.connect(self._highlight_activated)
        self.hl_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.hl_list.customContextMenuRequested.connect(self._highlight_list_menu)
        export_btn = QPushButton("⇩ Exportar anotações deste livro")
        export_btn.clicked.connect(lambda: self.book and save_markdown(self, self.library, self.book.id))
        hint = QLabel("Selecione um texto na página e clique com o botão direito para grifar.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hl_layout.addWidget(self.hl_list)
        hl_layout.addWidget(hint)
        hl_layout.addWidget(export_btn)
        self.hl_panel = hl_panel
        self.side.addTab(hl_panel, "Grifos")

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
        self.search_panel = search_panel
        self.side.addTab(search_panel, "Busca")

        # Área da página: um QLabel (modo página) ou uma coluna de QLabels (contínuo).
        self.page_label = QLabel(alignment=Qt.AlignCenter)
        self.cont_widget = QWidget()
        self.cont_layout = QVBoxLayout(self.cont_widget)
        self.cont_layout.setSpacing(PAGE_GAP)
        self.cont_layout.setContentsMargins(0, VIEW_MARGIN // 2, 0, VIEW_MARGIN // 2)
        for w in (self.page_label, self.cont_widget):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)  # o mouse é tratado na viewport
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.page_label)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.viewport().installEventFilter(self)
        self.scroll.viewport().setMouseTracking(True)
        self.scroll.verticalScrollBar().valueChanged.connect(lambda _: self._visible_timer.start())

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
            ("Ctrl+C",): self.copy_selection,
            ("Ctrl+H",): lambda: self.highlight_selection("amarelo"),
            ("Escape",): self._clear_selection,
            ("F3",): lambda: self._goto_hit(self._current_hit + 1),
            ("Shift+F3",): lambda: self._goto_hit(self._current_hit - 1),
            ("F5",): lambda: (self.act_tts.toggle(), self._toggle_tts()),
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
        self.continuous = book.continuous
        self.two_pages = book.two_pages and not self.continuous
        self.zoom = book.zoom or 1.0
        self.zoom_mode = book.zoom_mode or ("largura" if not loaded.reflowable and not loaded.image_based
                                             else "pagina")
        self._layout_key = None
        self._cache.clear()
        self._words.clear()
        self._sel = None
        self._clear_search()
        self.title_label.setText(f"  {book.title}" + (f" — {book.author}" if book.author else ""))
        self.act_font_down.setEnabled(loaded.reflowable)
        self.act_font_up.setEnabled(loaded.reflowable)
        self.act_two.setChecked(self.two_pages)
        self.act_two.setEnabled(not self.continuous)
        self.act_continuous.setChecked(self.continuous)
        self.act_tts.setEnabled(self.narrator.available and not loaded.image_based)
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.setCurrentIndex(list(ZOOM_MODES).index(self.zoom_mode))
        self.zoom_combo.blockSignals(False)

        self._relayout()
        page = book.page
        if loaded.reflowable and book.position:
            page = self._page_from_position(book.position, fallback=page)
        self.page_index = max(0, min(page, self.doc.page_count - 1))
        self._pages_seen = {self.page_index}
        self._pages_read = 0
        self._load_toc()
        self._load_bookmarks()
        self._load_highlights()
        self._last_interaction = time.monotonic()
        self._pending_seconds = 0
        self.library.mark_opened(book.id)
        self._apply_mode()
        self.scroll.setFocus()

    def open_at(self, page: int, position: str = "") -> None:
        """Vai para uma anotação salva (posição estável em livros refluíveis)."""
        if self.doc:
            if position and self.ldoc.reflowable:
                page = self._page_from_position(position, page)
            self.goto(page)

    def close_book(self) -> None:
        if not self.doc:
            return
        self._stop_tts()
        self._search_timer.stop()
        self.save_state()
        self.doc.close()
        self.book = self.ldoc = self.doc = None
        self._cache.clear()
        self._words.clear()
        self._sel = None
        self.page_label.clear()
        self._clear_slots()

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
            pages_read=self._pages_read, continuous=self.continuous,
        )
        self.book.reading_seconds += self._pending_seconds
        self.book.progress = progress
        self._pending_seconds = 0
        self._pages_read = 0

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
        self._words.clear()
        self._hl_cache.clear()
        self._sel = None
        if position:
            self.page_index = self._page_from_position(position, self.page_index)
            self._clear_search()
            self._load_toc()
            self._load_bookmarks()
            self._load_highlights()

    # =========================================================== renderizar
    def _fit_zoom(self, rect: pymupdf.Rect, columns: int = 1) -> float:
        vp = self.scroll.viewport().size()
        scrollbar = self.scroll.verticalScrollBar().sizeHint().width() if self.continuous else 0
        avail_w = max(vp.width() - VIEW_MARGIN - scrollbar, 50)
        avail_h = max(vp.height() - VIEW_MARGIN, 50)
        gap = PAGE_GAP if columns == 2 else 0
        fit_w = (avail_w - gap) / (rect.width * columns)
        if self.zoom_mode == "largura":
            return fit_w
        if self.zoom_mode == "pagina":
            return min(fit_w, avail_h / rect.height)
        return self.zoom

    def _effective_zoom(self) -> float:
        rect = self.doc[self.page_index].rect
        return self._fit_zoom(rect, 2 if self.two_pages else 1)

    def _render_raw(self, index: int, zoom: float, dpr: float) -> QImage:
        key = (index, round(zoom, 4), dpr, self.theme.key, self._layout_version,
               self._search_version, self._current_hit, self._annot_version)
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

        painter = QPainter(img)
        for hl, rects in self._highlights_on(index):
            color = QColor(HIGHLIGHT_COLORS.get(hl.color, "#ffd54a"))
            color.setAlpha(110)
            for r in rects:
                painter.fillRect(int(r[0] * scale), int(r[1] * scale),
                                 int((r[2] - r[0]) * scale) + 1, int((r[3] - r[1]) * scale) + 1, color)
        hits = self._search_hits.get(index)
        if hits:
            current = self._search_results[self._current_hit] if self._current_hit >= 0 else None
            for r in hits:
                is_current = current is not None and current[0] == index and current[1] == r
                color = QColor(255, 140, 0, 130) if is_current else QColor(255, 220, 0, 100)
                painter.fillRect(int(r.x0 * scale), int(r.y0 * scale),
                                 int(r.width * scale) + 1, int(r.height * scale) + 1, color)
        painter.end()

        self._cache[key] = img
        while len(self._cache) > 14:
            self._cache.popitem(last=False)
        return img

    def _with_selection(self, img: QImage, index: int, zoom: float, dpr: float) -> QImage:
        if not self._sel or self._sel["page"] != index:
            return img
        img = img.copy()
        scale = zoom * dpr
        painter = QPainter(img)
        for r in self._sel["rects"]:
            painter.fillRect(int(r[0] * scale), int(r[1] * scale),
                             int((r[2] - r[0]) * scale) + 1, int((r[3] - r[1]) * scale) + 1, SELECTION_COLOR)
        painter.end()
        return img

    def _apply_mode(self) -> None:
        """Troca o conteúdo da área de rolagem entre modo página e contínuo."""
        wanted = self.cont_widget if self.continuous else self.page_label
        if self.scroll.widget() is not wanted:
            self.scroll.takeWidget()
            self.scroll.setWidget(wanted)
        if self.continuous:
            self._build_continuous()
            self.goto(self.page_index)
        else:
            self._clear_slots()
            self.render()

    def render(self) -> None:
        if not self.doc:
            return
        if self.continuous:
            self._rendered.clear()
            self._update_visible()
            return
        count = self.doc.page_count
        self.page_index = max(0, min(self.page_index, count - 1))
        dpr = self.devicePixelRatioF()
        zoom = self._effective_zoom()
        indices = [self.page_index]
        if self.two_pages and self.page_index + 1 < count:
            indices.append(self.page_index + 1)
        images = [self._with_selection(self._render_raw(i, zoom, dpr), i, zoom, dpr) for i in indices]

        self._page_geoms = []
        if len(images) == 1:
            final = images[0].copy()
            self._page_geoms.append((indices[0], QRect(0, 0, int(final.width() / dpr), int(final.height() / dpr)), zoom))
        else:
            gap = int(PAGE_GAP * dpr)
            w = sum(i.width() for i in images) + gap
            h = max(i.height() for i in images)
            final = QImage(w, h, QImage.Format_RGB888)
            final.fill(QColor(self.theme.reader_bg))
            p = QPainter(final)
            x = 0
            for idx, img in zip(indices, images):
                y = (h - img.height()) // 2
                p.drawImage(x, y, img)
                self._page_geoms.append((idx, QRect(int(x / dpr), int(y / dpr), int(img.width() / dpr),
                                                    int(img.height() / dpr)), zoom))
                x += img.width() + gap
            p.end()
        final.setDevicePixelRatio(dpr)
        self.page_label.setPixmap(QPixmap.fromImage(final))
        self.page_label.setStyleSheet(f"background: {self.theme.reader_bg};")
        self._update_status(indices)
        self._save_timer.start()

    # ------------------------------------------------------ rolagem contínua
    def _clear_slots(self) -> None:
        for slot in self._slots:
            self.cont_layout.removeWidget(slot)
            slot.setParent(None)  # sai da tela já, sem esperar o deleteLater
            slot.deleteLater()
        self._slots, self._slot_y, self._slot_zoom = [], [], []
        self._rendered.clear()

    def _build_continuous(self) -> None:
        """Cria um espaço do tamanho certo para cada página; só as visíveis são desenhadas."""
        self._clear_slots()
        y = VIEW_MARGIN // 2
        for i in range(self.doc.page_count):
            rect = self.doc[i].rect
            zoom = self._fit_zoom(rect)
            slot = QLabel()
            slot.setAttribute(Qt.WA_TransparentForMouseEvents)
            slot.setFixedSize(max(int(rect.width * zoom), 1), max(int(rect.height * zoom), 1))
            slot.setStyleSheet(f"background: {self.theme.surface};")
            self.cont_layout.addWidget(slot, 0, Qt.AlignHCenter)
            self._slots.append(slot)
            self._slot_zoom.append(zoom)
            self._slot_y.append(y)
            y += slot.height() + PAGE_GAP
        self.cont_widget.setStyleSheet(f"background: {self.theme.reader_bg};")
        # Altura definida já: permite rolar até a página salva antes do próximo ciclo de layout.
        self.cont_widget.setMinimumHeight(y + VIEW_MARGIN // 2)
        self.cont_widget.resize(max(self.cont_widget.width(), self.scroll.viewport().width()),
                                y + VIEW_MARGIN // 2)

    def _slot_index_at(self, y: int) -> int:
        return max(0, min(bisect_right(self._slot_y, y) - 1, len(self._slots) - 1))

    def _update_visible(self, keep_page: int | None = None) -> None:
        if not (self.doc and self.continuous and self._slots):
            return
        bar = self.scroll.verticalScrollBar()
        top, height = bar.value(), self.scroll.viewport().height()
        first = self._slot_index_at(top)
        last = self._slot_index_at(top + height)
        wanted = set(range(max(0, first - RENDER_AHEAD), min(len(self._slots), last + RENDER_AHEAD + 1)))
        dpr = self.devicePixelRatioF()
        for i in sorted(wanted - self._rendered):
            self._paint_slot(i, dpr)
        for i in self._rendered - wanted:
            self._slots[i].clear()  # libera memória das páginas distantes
        self._rendered = wanted
        current = keep_page if keep_page is not None else self._slot_index_at(top + height // 3)
        if current != self.page_index:
            self._page_changed(current)
        self._update_status([self.page_index])
        self._save_timer.start()

    def _paint_slot(self, index: int, dpr: float) -> None:
        zoom = self._slot_zoom[index]
        img = self._with_selection(self._render_raw(index, zoom, dpr), index, zoom, dpr)
        img.setDevicePixelRatio(dpr)
        self._slots[index].setPixmap(QPixmap.fromImage(img))

    def _refresh_page(self, index: int) -> None:
        """Redesenha só a página indicada (seleção mudou)."""
        if self.continuous:
            if 0 <= index < len(self._slots) and index in self._rendered:
                self._paint_slot(index, self.devicePixelRatioF())
        else:
            self.render()

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
        if seconds > 120 and 1 / count < progress < 1:
            parts.append(f"~{_format_duration(seconds * (1 - progress) / progress)} restantes")
        chapter = self._current_chapter_title()
        if chapter:
            parts.append(chapter)
        self.status_label.setText("  ·  ".join(parts))
        self._highlight_toc()

    # ============================================================ navegação
    def _page_changed(self, index: int) -> None:
        self.page_index = index
        if index not in self._pages_seen:
            self._pages_seen.add(index)
            self._pages_read += 1

    def goto(self, index: int, at_bottom: bool = False) -> None:
        if not self.doc:
            return
        index = max(0, min(index, self.doc.page_count - 1))
        self._touch()
        if self.continuous:
            self._page_changed(index)
            bar = self.scroll.verticalScrollBar()
            bar.blockSignals(True)  # evita recalcular a página no meio da rolagem
            bar.setValue(self._slot_y[index] - VIEW_MARGIN // 2)
            bar.blockSignals(False)
            self._update_visible(keep_page=index)
            return
        self._page_changed(index)
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
        reading = self._tts_on or time.monotonic() - self._last_interaction < IDLE_LIMIT
        if self.book is not None and self.isVisible() and (QApplication.activeWindow() or self._tts_on) and reading:
            self._pending_seconds += TICK_SECONDS
            if self._pending_seconds >= 60:
                self.save_state()

    # ================================================================ zoom
    def _set_zoom_mode(self, mode: str) -> None:
        self.zoom_mode = mode
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.setCurrentIndex(list(ZOOM_MODES).index(mode))
        self.zoom_combo.blockSignals(False)
        self._rebuild()

    def _rebuild(self) -> None:
        if not self.doc:
            return
        if self.continuous:
            page = self.page_index
            self._build_continuous()
            self.goto(page)
        else:
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

    def _zoom_at(self, factor: float, global_pos: QPoint) -> None:
        """Zoom mantendo sob o cursor o mesmo ponto da página."""
        viewport = self.scroll.viewport()
        content = self.scroll.widget()
        hbar, vbar = self.scroll.horizontalScrollBar(), self.scroll.verticalScrollBar()
        cursor = viewport.mapFromGlobal(global_pos)
        old_w, old_h = max(content.width(), 1), max(content.height(), 1)
        fx, fy = (hbar.value() + cursor.x()) / old_w, (vbar.value() + cursor.y()) / old_h
        self._zoom_by(factor)
        QApplication.processEvents()  # aplica o novo tamanho antes de reposicionar
        hbar.setValue(int(fx * content.width() - cursor.x()))
        vbar.setValue(int(fy * content.height() - cursor.y()))

    def _change_font(self, delta: int) -> None:
        if self.ldoc and self.ldoc.reflowable:
            self.font_size = max(7.0, min(self.font_size + delta, 32.0))
            self._relayout()
            self._rebuild()

    def _toggle_two_pages(self) -> None:
        self.two_pages = self.act_two.isChecked()
        self._relayout()
        self.render()

    def _toggle_continuous(self) -> None:
        self.continuous = self.act_continuous.isChecked()
        if self.continuous and self.two_pages:
            self.two_pages = False
            self.act_two.setChecked(False)
            self._relayout()
        self.act_two.setEnabled(not self.continuous)
        if self.doc:
            self._apply_mode()

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
        self.cont_widget.setStyleSheet(f"background: {theme.reader_bg};")
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
            if self.continuous and self.zoom_mode == "livre":
                self._update_visible()
            else:
                self._rebuild()

    def _hit(self, global_pos: QPoint) -> tuple[int, float, float] | None:
        """Página e coordenada (em pontos do documento) sob o cursor."""
        if not self.doc:
            return None
        if self.continuous:
            p = self.cont_widget.mapFromGlobal(global_pos)
            i = self._slot_index_at(p.y())
            if not self._slots:
                return None
            g = self._slots[i].geometry()
            if g.contains(p):
                z = self._slot_zoom[i]
                return i, (p.x() - g.x()) / z, (p.y() - g.y()) / z
            return None
        pix = self.page_label.pixmap()
        if pix is None or pix.isNull():
            return None
        p = self.page_label.mapFromGlobal(global_pos)
        dpr = pix.devicePixelRatio()
        ox = (self.page_label.width() - pix.width() / dpr) / 2
        oy = (self.page_label.height() - pix.height() / dpr) / 2
        for index, rect, zoom in self._page_geoms:
            x, y = p.x() - ox - rect.x(), p.y() - oy - rect.y()
            if 0 <= x <= rect.width() and 0 <= y <= rect.height():
                return index, x / zoom, y / zoom
        return None

    def eventFilter(self, obj, event) -> bool:
        if obj is not self.scroll.viewport() or not self.doc:
            return super().eventFilter(obj, event)
        et = event.type()
        if et == QEvent.Wheel:
            self._touch()
            dy = event.angleDelta().y() or event.angleDelta().x()
            if event.modifiers() & Qt.ControlModifier:
                if dy:
                    self._zoom_at(1.1 ** (dy / 120), event.globalPosition().toPoint())
                return True
            if self.continuous:
                return False  # rolagem normal
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
        elif et == QEvent.MouseButtonPress:
            gp = event.globalPosition().toPoint()
            self._touch()
            if event.button() == Qt.MiddleButton:
                self._pan = (gp, self.scroll.horizontalScrollBar().value(), self.scroll.verticalScrollBar().value())
                self.scroll.viewport().setCursor(Qt.ClosedHandCursor)
                return True
            if event.button() == Qt.LeftButton:
                self._press = {"pos": gp, "hit": self._hit(gp), "selecting": False}
                return True
            if event.button() == Qt.RightButton:
                self._context_menu(gp)
                return True
        elif et == QEvent.MouseMove:
            gp = event.globalPosition().toPoint()
            if self._pan:
                origin, hx, vy = self._pan
                delta = gp - origin
                self.scroll.horizontalScrollBar().setValue(hx - delta.x())
                self.scroll.verticalScrollBar().setValue(vy - delta.y())
                return True
            if self._press and self._press["hit"] and (gp - self._press["pos"]).manhattanLength() > 4:
                self._press["selecting"] = True
                self._update_selection(self._press["hit"], self._hit(gp))
                return True
            hit = self._hit(gp)
            self.scroll.viewport().setCursor(Qt.IBeamCursor if hit and self._word_at(hit) is not None
                                             else Qt.ArrowCursor)
        elif et == QEvent.MouseButtonRelease:
            if self._pan and event.button() == Qt.MiddleButton:
                self._pan = None
                self.scroll.viewport().unsetCursor()
                return True
            press, self._press = self._press, None
            if press and event.button() == Qt.LeftButton and not press["selecting"]:
                self._click(press["hit"], event.globalPosition().toPoint())
            return True
        elif et == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            hit = self._hit(event.globalPosition().toPoint())
            if hit:
                self._update_selection(hit, hit)
            return True
        return super().eventFilter(obj, event)

    def _click(self, hit, global_pos: QPoint) -> None:
        if hit:
            highlight = self._highlight_at(hit)
            if highlight:
                self._highlight_menu(highlight, global_pos)
                return
        if self._sel:
            self._clear_selection()
            return
        if not self.continuous:
            viewport = self.scroll.viewport()
            x = viewport.mapFromGlobal(global_pos).x() / max(viewport.width(), 1)
            if x < 0.3:
                self.prev_page()
            elif x > 0.7:
                self.next_page()

    # ============================================================ seleção
    def _page_words(self, index: int) -> list:
        if index not in self._words:
            self._words[index] = self.doc[index].get_text("words", sort=False)
        return self._words[index]

    def _word_at(self, hit) -> int | None:
        index, x, y = hit
        for i, w in enumerate(self._page_words(index)):
            if w[0] <= x <= w[2] and w[1] <= y <= w[3]:
                return i
        return None

    def _update_selection(self, start, end) -> None:
        if not start:
            return
        index = start[0]
        words = self._page_words(index)
        if not words:
            return
        if not end or end[0] != index:  # seleção limitada à página onde começou
            end = (index, start[1], start[2]) if not end else (
                index, 1e9 if end[0] > index else -1, 1e9 if end[0] > index else -1)
        a = nearest_word(words, start[1], start[2])
        b = nearest_word(words, end[1], end[2])
        lo, hi = sorted((a, b))
        chosen = words[lo:hi + 1]
        previous = self._sel["page"] if self._sel else None
        self._sel = {"page": index, "lo": lo, "hi": hi, "rects": merge_line_rects(chosen),
                     "text": words_text(chosen)}
        if previous is not None and previous != index:
            self._refresh_page(previous)
        self._refresh_page(index)

    def _clear_selection(self) -> None:
        if self._sel:
            page = self._sel["page"]
            self._sel = None
            self._refresh_page(page)

    def selected_text(self) -> str:
        return self._sel["text"] if self._sel else ""

    def copy_selection(self) -> None:
        if self._sel:
            QApplication.clipboard().setText(self._sel["text"])

    def _context_menu(self, global_pos: QPoint) -> None:
        hit = self._hit(global_pos)
        menu = QMenu(self)
        handlers = {}
        if self._sel:
            text = self._sel["text"]
            handlers[menu.addAction("Copiar\tCtrl+C")] = self.copy_selection
            colors = menu.addMenu("Grifar")
            for key, label in COLOR_NAMES.items():
                handlers[colors.addAction(color_icon(key), label)] = lambda k=key: self.highlight_selection(k)
            handlers[menu.addAction("Grifar com anotação…")] = lambda: self.highlight_selection("amarelo", ask_note=True)
            menu.addSeparator()
            first_word = text.split()[0] if text.split() else ""
            if first_word:
                handlers[menu.addAction(f"Definição de “{first_word[:30]}”")] = lambda: self.lookup_definition(first_word)
            handlers[menu.addAction("Traduzir seleção")] = lambda: self.lookup_translation(text)
            if self.narrator.available:
                handlers[menu.addAction("Ler em voz alta a partir daqui")] = self._tts_from_selection
        else:
            highlight = self._highlight_at(hit) if hit else None
            if highlight:
                self._highlight_menu(highlight, global_pos)
                return
            handlers[menu.addAction("Adicionar marcador nesta página")] = self.add_bookmark
            if self.narrator.available and not self.ldoc.image_based:
                handlers[menu.addAction("Ler em voz alta a partir desta página")] = self._start_tts_here
            handlers[menu.addAction("Copiar o texto da página")] = lambda: QApplication.clipboard().setText(
                self.doc[hit[0] if hit else self.page_index].get_text())
        chosen = menu.exec(global_pos)
        if chosen in handlers:
            handlers[chosen]()

    # =============================================================== grifos
    def _load_highlights(self) -> None:
        self._highlights = self.library.highlights(self.book.id) if self.book else []
        self._hl_cache.clear()
        self._annot_version += 1
        self.hl_list.clear()
        for h in self._highlights:
            page = self._highlight_page(h)
            text = f"“{h.text.strip()[:220]}”\nPág. {page + 1}"
            if h.note:
                text += f"  ·  📝 {h.note}"
            item = QListWidgetItem(color_icon(h.color), text)
            item.setData(Qt.UserRole, h.id)
            self.hl_list.addItem(item)
        if not self._highlights:
            empty = QListWidgetItem("Nenhum grifo neste livro.")
            empty.setFlags(Qt.NoItemFlags)
            self.hl_list.addItem(empty)

    def _highlight_page(self, h: Highlight) -> int:
        if self.ldoc and self.ldoc.reflowable and h.position:
            return self._page_from_position(h.position, h.page)
        return h.page

    def _highlights_on(self, index: int) -> list[tuple[Highlight, list]]:
        """Grifos visíveis na página; em livros refluíveis o texto é reencontrado após repaginar."""
        if index in self._hl_cache:
            return self._hl_cache[index]
        found = []
        for h in self._highlights:
            if not (self.ldoc.reflowable and h.position):
                if h.page == index:
                    found.append((h, h.rects))
                continue
            if abs(self._highlight_page(h) - index) > 1:
                continue
            rects = self._search_text(index, h.text)
            if rects:
                found.append((h, rects))
        self._hl_cache[index] = found
        return found

    def _search_text(self, index: int, text: str) -> list:
        page = self.doc[index]
        text = " ".join(text.split())
        quads = page.search_for(text) or []
        if not quads and len(text) > 50:  # trecho cortado pela quebra de página
            quads = (page.search_for(text[:50]) or []) + (page.search_for(text[-50:]) or [])
        return [[r.x0, r.y0, r.x1, r.y1] for r in quads]

    def _highlight_at(self, hit) -> Highlight | None:
        index, x, y = hit
        for h, rects in self._highlights_on(index):
            if any(r[0] <= x <= r[2] and r[1] <= y <= r[3] for r in rects):
                return h
        return None

    def highlight_selection(self, color: str, ask_note: bool = False) -> None:
        if not (self._sel and self.book):
            return
        note = ""
        if ask_note:
            note, ok = QInputDialog.getMultiLineText(self, "Anotação", "Anotação para o trecho grifado:")
            if not ok:
                return
        sel = self._sel
        self.library.add_highlight(self.book.id, sel["page"], self._position_of(sel["page"]), color,
                                   sel["text"], note.strip(), sel["rects"])
        self._sel = None
        self._cache.clear()
        self._load_highlights()
        self._refresh_page(sel["page"])
        self.annotations_changed.emit()

    def _highlight_menu(self, h: Highlight, global_pos: QPoint) -> None:
        menu = QMenu(self)
        handlers = {}
        colors = menu.addMenu("Mudar cor")
        for key, label in COLOR_NAMES.items():
            handlers[colors.addAction(color_icon(key), label)] = lambda k=key: self._update_highlight(h, color=k)
        handlers[menu.addAction("Editar anotação…")] = lambda: self._edit_highlight_note(h)
        handlers[menu.addAction("Copiar texto")] = lambda: QApplication.clipboard().setText(h.text)
        menu.addSeparator()
        handlers[menu.addAction("Remover grifo")] = lambda: self._remove_highlight(h)
        chosen = menu.exec(global_pos)
        if chosen in handlers:
            handlers[chosen]()

    def _update_highlight(self, h: Highlight, color: str | None = None, note: str | None = None) -> None:
        self.library.update_highlight(h.id, color=color, note=note)
        self._cache.clear()
        self._load_highlights()
        self.render()
        self.annotations_changed.emit()

    def _edit_highlight_note(self, h: Highlight) -> None:
        text, ok = QInputDialog.getMultiLineText(self, "Anotação", "Anotação:", h.note)
        if ok:
            self._update_highlight(h, note=text.strip())

    def _remove_highlight(self, h: Highlight) -> None:
        self.library.remove_highlight(h.id)
        self._cache.clear()
        self._load_highlights()
        self.render()
        self.annotations_changed.emit()

    def _highlight_by_id(self, highlight_id) -> Highlight | None:
        return next((h for h in self._highlights if h.id == highlight_id), None)

    def _highlight_activated(self, item: QListWidgetItem) -> None:
        h = self._highlight_by_id(item.data(Qt.UserRole))
        if h:
            self.goto(self._highlight_page(h))

    def _highlight_list_menu(self, pos) -> None:
        item = self.hl_list.itemAt(pos)
        h = self._highlight_by_id(item.data(Qt.UserRole)) if item else None
        if h:
            self._highlight_menu(h, self.hl_list.mapToGlobal(pos))

    # ==================================================== dicionário/tradução
    def lookup_definition(self, word: str) -> None:
        clean = word.strip(".,;:!?\"'“”()[]«»")
        LookupDialog("Dicionário", clean, online.define,
                     f"https://pt.wiktionary.org/wiki/{QUrl.toPercentEncoding(clean.lower()).data().decode()}",
                     self).show()

    def lookup_translation(self, text: str) -> None:
        LookupDialog("Tradução", " ".join(text.split()), online.translate,
                     "https://translate.google.com/?sl=auto&tl=pt&text="
                     + QUrl.toPercentEncoding(" ".join(text.split())[:1500]).data().decode(), self).show()

    # ====================================================== leitura em voz alta
    def _configure_voice(self) -> None:
        rate = float(self.library.setting("voz_velocidade", "0") or 0)
        self.narrator.configure(self.library.setting("voz"), rate)

    def _toggle_tts(self) -> None:
        if self.act_tts.isChecked():
            self._start_tts_here()
        else:
            self._stop_tts()

    def _start_tts_here(self, from_word: int = 0) -> None:
        if not (self.doc and self.narrator.available):
            return
        self._configure_voice()
        self._tts_on = True
        self.act_tts.setChecked(True)
        self._speak_page(self.page_index, from_word)

    def _tts_from_selection(self) -> None:
        if self._sel:
            page, lo = self._sel["page"], self._sel["lo"]
            self._clear_selection()
            self.page_index = page
            self._start_tts_here(lo)

    def _speak_page(self, index: int, from_word: int = 0) -> None:
        words = self._page_words(index)
        text = words_text(words[from_word:]) if words else self.doc[index].get_text()
        self.narrator.speak(text)

    def _tts_page_done(self) -> None:
        if not self._tts_on or not self.doc:
            return
        nxt = self.page_index + 1
        if nxt >= self.doc.page_count:
            self._stop_tts()
            return
        self.goto(nxt)
        self._speak_page(nxt)

    def _stop_tts(self) -> None:
        self._tts_on = False
        self.act_tts.setChecked(False)
        self.narrator.stop()

    def _tts_error(self, message: str) -> None:
        self._stop_tts()
        QMessageBox.warning(self, "Leitura em voz alta", message)

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
        self._show_side_tab(self.bm_panel)
        self.annotations_changed.emit()

    def _show_side_tab(self, widget: QWidget) -> None:
        self.side.setCurrentWidget(widget)
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
                self.annotations_changed.emit()
        elif chosen == act_del:
            self.library.remove_bookmark(bm_id)
            self._load_bookmarks()
            self.annotations_changed.emit()

    # =============================================================== busca
    def focus_search(self) -> None:
        self._show_side_tab(self.search_panel)
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
                self.search_list.addItem(QListWidgetItem(f"Pág. {index + 1}: {snippet[:120]}"))
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
        bar = self.scroll.verticalScrollBar()
        if self.continuous:
            bar.setValue(self._slot_y[page] + int(rect.y0 * self._slot_zoom[page]) - self.scroll.viewport().height() // 3)
            self.render()
        else:
            bar.setValue(int(rect.y0 * self._effective_zoom()) - self.scroll.viewport().height() // 3)


def _format_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{max(minutes, 1)} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"
