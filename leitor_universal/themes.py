"""Temas visuais: paleta da interface e coloração aplicada às páginas."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    window: str
    surface: str
    text: str
    muted: str
    accent: str
    reader_bg: str
    page_ink: int | None   # cor que substitui o preto do texto
    page_paper: int | None  # cor que substitui o branco do papel
    invert: bool = False


THEMES: dict[str, Theme] = {
    "claro": Theme("claro", "Claro", "#f3f3f5", "#ffffff", "#1d1d1f", "#6e6e73", "#2f6fde",
                   "#e4e4e8", None, None),
    "sepia": Theme("sepia", "Sépia", "#efe6d2", "#f8f1e1", "#3b2f22", "#7a6a55", "#a0642d",
                   "#e2d6bc", 0x3B2F22, 0xF6EEDC),
    "escuro": Theme("escuro", "Escuro", "#1c1c1f", "#26262a", "#e6e6e6", "#9a9aa0", "#5b9cff",
                    "#121214", 0x15151A, 0xCFCFCF, invert=True),
}


def apply_theme(app: QApplication, theme: Theme) -> None:
    pal = QPalette()
    window, surface, text = QColor(theme.window), QColor(theme.surface), QColor(theme.text)
    accent, muted = QColor(theme.accent), QColor(theme.muted)
    pal.setColor(QPalette.Window, window)
    pal.setColor(QPalette.WindowText, text)
    pal.setColor(QPalette.Base, surface)
    pal.setColor(QPalette.AlternateBase, window)
    pal.setColor(QPalette.Text, text)
    pal.setColor(QPalette.Button, surface)
    pal.setColor(QPalette.ButtonText, text)
    pal.setColor(QPalette.ToolTipBase, surface)
    pal.setColor(QPalette.ToolTipText, text)
    pal.setColor(QPalette.PlaceholderText, muted)
    pal.setColor(QPalette.Highlight, accent)
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.Link, accent)
    pal.setColor(QPalette.Disabled, QPalette.Text, muted)
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, muted)
    pal.setColor(QPalette.Disabled, QPalette.WindowText, muted)
    app.setPalette(pal)
    app.setStyleSheet(f"""
        QToolBar {{ border: none; spacing: 4px; padding: 4px; background: {theme.window}; }}
        QToolButton {{ padding: 4px 8px; border-radius: 6px; }}
        QToolButton:hover {{ background: {theme.reader_bg}; }}
        QToolButton:checked {{ background: {theme.accent}; color: white; }}
        QToolButton::menu-indicator {{ image: none; width: 0; }}
        QPushButton {{ padding: 6px 12px; border-radius: 6px; border: 1px solid {theme.reader_bg};
                       background: {theme.surface}; }}
        QPushButton:hover {{ border-color: {theme.accent}; }}
        QPushButton#primary {{ background: {theme.accent}; color: white; border: none; }}
        QLineEdit, QComboBox, QSpinBox {{ padding: 5px 8px; border-radius: 6px;
                       border: 1px solid {theme.reader_bg}; background: {theme.surface}; }}
        QLineEdit:focus {{ border-color: {theme.accent}; }}
        QListWidget, QTreeWidget {{ border: none; background: {theme.surface}; }}
        QTabWidget::pane {{ border: none; }}
        QTabBar::tab {{ padding: 6px 12px; border: none; background: {theme.window}; color: {theme.muted}; }}
        QTabBar::tab:selected {{ background: {theme.surface}; color: {theme.text};
                       border-bottom: 2px solid {theme.accent}; }}
        QTreeWidget::item:selected, QListWidget::item:selected {{ background: {theme.reader_bg};
                       color: {theme.text}; }}
        QSlider::groove:horizontal {{ height: 4px; background: {theme.reader_bg}; border-radius: 2px; }}
        QSlider::sub-page:horizontal {{ background: {theme.accent}; border-radius: 2px; }}
        QSlider::handle:horizontal {{ background: {theme.accent}; width: 14px; margin: -6px 0;
                       border-radius: 7px; }}
        QProgressBar {{ border: none; border-radius: 6px; background: {theme.reader_bg}; height: 14px;
                       text-align: center; color: {theme.text}; font-size: 11px; }}
        QProgressBar::chunk {{ background: {theme.accent}; border-radius: 6px; }}
        QFrame#sidebar {{ background: {theme.surface}; border-right: 1px solid {theme.reader_bg}; }}
        QLabel#brand {{ font-size: 15px; font-weight: 600; padding: 4px 6px; }}
        QToolButton#nav {{ text-align: left; padding: 9px 12px; border-radius: 8px; font-size: 13px; }}
        QToolButton#nav:hover {{ background: {theme.reader_bg}; }}
        QToolButton#nav:checked {{ background: {theme.accent}; color: white; }}
        QLabel#muted {{ color: {theme.muted}; }}
        QLabel#heading {{ font-size: 20px; font-weight: 600; }}
    """)
