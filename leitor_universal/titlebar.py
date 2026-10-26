"""Barra de título própria para a janela sem moldura do Windows.

Mover e redimensionar usam startSystemMove/startSystemResize, então o Windows continua
cuidando do encaixe nas bordas da tela (Aero Snap) e da maximização.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QCursor, QFont, QFontDatabase, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QWidget

RESIZE_MARGIN = 6
EDGE_CURSORS = {
    Qt.LeftEdge: Qt.SizeHorCursor, Qt.RightEdge: Qt.SizeHorCursor,
    Qt.TopEdge: Qt.SizeVerCursor, Qt.BottomEdge: Qt.SizeVerCursor,
    Qt.LeftEdge | Qt.TopEdge: Qt.SizeFDiagCursor, Qt.RightEdge | Qt.BottomEdge: Qt.SizeFDiagCursor,
    Qt.RightEdge | Qt.TopEdge: Qt.SizeBDiagCursor, Qt.LeftEdge | Qt.BottomEdge: Qt.SizeBDiagCursor,
}


def _window_glyphs() -> dict:
    """Ícones nativos do Windows 10/11 (Segoe Fluent Icons / MDL2); texto simples como reserva."""
    families = set(QFontDatabase.families())
    for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if name in families:
            return {"font": name, "min": "", "max": "", "restore": "", "close": ""}
    return {"font": "", "min": "—", "max": "☐", "restore": "❐", "close": "✕"}


class TitleBar(QFrame):
    def __init__(self, window: QWidget, icon: QPixmap | None = None):
        super().__init__(window)
        self.window_ = window
        self.setObjectName("titlebar")
        self.setFixedHeight(34)
        logo = QLabel()
        if icon and not icon.isNull():
            logo.setPixmap(icon.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.title = QLabel()
        self.title.setObjectName("titletext")
        self.glyphs = _window_glyphs()
        self.min_btn = self._button(self.glyphs["min"], "Minimizar", window.showMinimized)
        self.max_btn = self._button(self.glyphs["max"], "Maximizar", self.toggle_maximized)
        self.close_btn = self._button(self.glyphs["close"], "Fechar", window.close, name="winclose")
        if self.glyphs["font"]:
            font = QFont(self.glyphs["font"])
            font.setPointSizeF(7.5)
            for btn in (self.min_btn, self.max_btn, self.close_btn):
                btn.setFont(font)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(logo)
        layout.addWidget(self.title)
        layout.addStretch(1)
        layout.setSpacing(0)
        for btn in (self.min_btn, self.max_btn, self.close_btn):
            layout.addWidget(btn)

    def _button(self, text: str, tip: str, slot, name: str = "winbtn") -> QToolButton:
        btn = QToolButton(self)
        btn.setObjectName(name)
        btn.setText(text)
        btn.setToolTip(tip)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.clicked.connect(slot)
        return btn

    def set_title(self, text: str) -> None:
        self.title.setText(text)

    def toggle_maximized(self) -> None:
        if self.window_.isMaximized():
            self.window_.showNormal()
        else:
            self.window_.showMaximized()

    def sync_state(self) -> None:
        maximized = self.window_.isMaximized()
        self.max_btn.setText(self.glyphs["restore" if maximized else "max"])
        self.max_btn.setToolTip("Restaurar" if maximized else "Maximizar")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.window_.windowHandle():
            self.window_.windowHandle().startSystemMove()
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.toggle_maximized()


class FramelessResizer(QObject):
    """Redimensiona a janela sem moldura pela borda fina do widget `frame`
    (o contêiner central, com margens de RESIZE_MARGIN em volta do conteúdo)."""

    def __init__(self, window: QWidget, frame: QWidget):
        super().__init__(window)
        self.window_ = window
        self.frame = frame
        frame.setMouseTracking(True)
        frame.installEventFilter(self)

    def _edges(self, global_pos: QPoint):
        w = self.window_
        if w.isMaximized() or w.isFullScreen() or not w.isVisible():
            return Qt.Edges()
        rect = w.frameGeometry()
        x, y = global_pos.x(), global_pos.y()
        edges = Qt.Edges()
        if x - rect.left() <= RESIZE_MARGIN:
            edges |= Qt.LeftEdge
        elif rect.right() - x <= RESIZE_MARGIN:
            edges |= Qt.RightEdge
        if y - rect.top() <= RESIZE_MARGIN:
            edges |= Qt.TopEdge
        elif rect.bottom() - y <= RESIZE_MARGIN:
            edges |= Qt.BottomEdge
        return edges

    def eventFilter(self, obj, event) -> bool:
        et = event.type()
        if obj is not self.frame or et not in (QEvent.MouseMove, QEvent.MouseButtonPress):
            return False
        edges = self._edges(QCursor.pos())
        if et == QEvent.MouseButtonPress and edges and event.button() == Qt.LeftButton:
            self.window_.windowHandle().startSystemResize(edges)
            return True
        # O cursor do contêiner só vale sobre a borda; os filhos mantêm o deles.
        self.frame.setCursor(EDGE_CURSORS.get(edges, Qt.ArrowCursor))
        return False
