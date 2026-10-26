"""Temas visuais: paleta da interface, folha de estilo e coloração aplicada às páginas."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    window: str        # fundo da janela
    surface: str       # cartões, painéis, campos
    text: str
    muted: str
    accent: str        # cor principal
    accent2: str       # segunda cor dos gradientes
    reader_bg: str     # fundo atrás das páginas
    border: str
    page_ink: int | None = None    # cor que substitui o preto do texto da página
    page_paper: int | None = None  # cor que substitui o branco do papel
    invert: bool = False
    dark: bool = False
    glow: bool = False             # brilho nos destaques (tema futurista)

    @property
    def gradient(self) -> str:
        return (f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {self.accent}, stop:1 {self.accent2})")


THEMES: dict[str, Theme] = {
    "futurista": Theme(
        key="futurista", label="Futurista", window="#0a0e1a", surface="#121a2e", text="#e6edff",
        muted="#8a96b8", accent="#22d3ee", accent2="#8b5cf6", reader_bg="#060912", border="#223052",
        page_ink=0x0E1426, page_paper=0xD9E4FF, invert=True, dark=True, glow=True),
    "claro": Theme(
        key="claro", label="Claro", window="#f4f5f9", surface="#ffffff", text="#161a26", muted="#6b7280",
        accent="#2f6fde", accent2="#7c3aed", reader_bg="#e6e8ef", border="#dde1ea"),
    "sepia": Theme(
        key="sepia", label="Sépia", window="#efe6d2", surface="#f8f1e1", text="#3b2f22", muted="#7a6a55",
        accent="#a0642d", accent2="#c2410c", reader_bg="#e2d6bc", border="#dccfb2",
        page_ink=0x3B2F22, page_paper=0xF6EEDC),
    "escuro": Theme(
        key="escuro", label="Escuro", window="#18181b", surface="#232327", text="#e6e6e6", muted="#9a9aa0",
        accent="#5b9cff", accent2="#a78bfa", reader_bg="#111113", border="#2e2e34",
        page_ink=0x15151A, page_paper=0xCFCFCF, invert=True, dark=True),
}
DEFAULT_THEME = "futurista"


def _ui_font() -> QFont:
    families = set(QFontDatabase.families())
    for name in ("Segoe UI Variable Text", "Segoe UI", "Inter"):
        if name in families:
            font = QFont(name)
            font.setPointSizeF(9.5)
            return font
    return QFont()


def apply_theme(app: QApplication, theme: Theme) -> None:
    app.setFont(_ui_font())
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
    pal.setColor(QPalette.HighlightedText, QColor("#06101c" if theme.glow else "#ffffff"))
    pal.setColor(QPalette.Link, accent)
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        pal.setColor(QPalette.Disabled, role, muted)
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(theme))


def stylesheet(t: Theme) -> str:
    on_accent = "#06101c" if t.glow else "#ffffff"
    hover = "rgba(255,255,255,0.06)" if t.dark else "rgba(0,0,0,0.05)"
    return f"""
    QMainWindow, QDialog {{ background: {t.window}; }}
    QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
                border-radius: 6px; padding: 5px 8px; }}

    /* Barra de título própria */
    QFrame#titlebar {{ background: {t.window}; border-bottom: 1px solid {t.border}; }}
    QLabel#titletext {{ color: {t.muted}; font-size: 12px; }}
    QToolButton#winbtn {{ border: none; border-radius: 0; padding: 0; min-width: 46px; min-height: 34px;
                          font-size: 13px; color: {t.muted}; background: transparent; }}
    QToolButton#winbtn:hover {{ background: {hover}; color: {t.text}; }}
    QToolButton#winclose:hover {{ background: #e5484d; color: white; }}
    QToolButton#winclose {{ border: none; border-radius: 0; min-width: 46px; min-height: 34px;
                            font-size: 13px; color: {t.muted}; background: transparent; }}

    /* Barra lateral */
    QFrame#sidebar {{ background: {t.surface}; border-right: 1px solid {t.border}; }}
    QLabel#brand {{ font-size: 16px; font-weight: 700; padding: 4px 8px; color: {t.text}; }}
    QLabel#brandsub {{ font-size: 11px; padding: 0 8px; color: {t.muted}; letter-spacing: 1px; }}
    QToolButton#nav {{ text-align: left; padding: 10px 14px; border-radius: 10px; font-size: 13px;
                       color: {t.muted}; border: 1px solid transparent; }}
    QToolButton#nav:hover {{ background: {hover}; color: {t.text}; }}
    QToolButton#nav:checked {{ background: {t.gradient}; color: {on_accent}; font-weight: 600; }}

    /* Botões */
    QToolBar {{ border: none; spacing: 4px; padding: 6px 8px; background: {t.window};
                border-bottom: 1px solid {t.border}; }}
    QToolButton {{ padding: 5px 9px; border-radius: 8px; color: {t.text}; }}
    QToolButton:hover {{ background: {hover}; }}
    QToolButton:checked {{ background: {t.gradient}; color: {on_accent}; }}
    QToolButton:disabled {{ color: {t.border}; }}
    QToolButton::menu-indicator {{ image: none; width: 0; }}
    QPushButton {{ padding: 7px 14px; border-radius: 9px; border: 1px solid {t.border};
                   background: {t.surface}; color: {t.text}; }}
    QPushButton:hover {{ border-color: {t.accent}; color: {t.accent if t.glow else t.text}; }}
    QPushButton:pressed {{ background: {hover}; }}
    QPushButton:disabled {{ color: {t.muted}; border-color: {t.border}; }}
    QPushButton#primary {{ background: {t.gradient}; color: {on_accent}; border: none; font-weight: 600; }}
    QPushButton#primary:hover {{ border: 1px solid {t.text}; }}

    /* Campos */
    QLineEdit, QComboBox, QSpinBox, QTextBrowser, QPlainTextEdit, QTextEdit {{
        padding: 6px 10px; border-radius: 9px; border: 1px solid {t.border};
        background: {t.surface}; color: {t.text}; selection-background-color: {t.accent};
        selection-color: {on_accent}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {t.accent}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
                                   selection-background-color: {t.accent}; selection-color: {on_accent};
                                   outline: none; padding: 4px; }}
    QCheckBox {{ spacing: 8px; }}

    /* Listas e abas */
    QListWidget, QTreeWidget {{ border: none; background: {t.surface}; color: {t.text}; outline: none;
                                border-radius: 12px; padding: 4px; }}
    QListWidget::item, QTreeWidget::item {{ padding: 6px; border-radius: 8px; }}
    QListWidget::item:hover, QTreeWidget::item:hover {{ background: {hover}; }}
    QTreeWidget::item:selected, QListWidget::item:selected {{ background: {hover}; color: {t.accent if t.glow else t.text};
                                                             border: 1px solid {t.border}; }}
    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{ padding: 7px 14px; border: none; background: transparent; color: {t.muted}; }}
    QTabBar::tab:hover {{ color: {t.text}; }}
    QTabBar::tab:selected {{ color: {t.text}; border-bottom: 2px solid {t.accent}; }}
    QGroupBox {{ border: 1px solid {t.border}; border-radius: 12px; margin-top: 14px; padding: 12px 10px 10px 10px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {t.muted}; }}

    /* Menus */
    QMenu {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; border-radius: 10px; padding: 6px; }}
    QMenu::item {{ padding: 7px 22px 7px 12px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {t.gradient}; color: {on_accent}; }}
    QMenu::separator {{ height: 1px; background: {t.border}; margin: 5px 8px; }}

    /* Rolagem, slider e progresso */
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle {{ background: {t.border}; border-radius: 4px; min-height: 30px; min-width: 30px; }}
    QScrollBar::handle:hover {{ background: {t.accent}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QSlider::groove:horizontal {{ height: 4px; background: {t.border}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {t.gradient}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {t.text if t.glow else t.accent}; width: 14px; margin: -6px 0;
                                  border-radius: 7px; border: 2px solid {t.accent}; }}
    QProgressBar {{ border: none; border-radius: 7px; background: {t.border}; min-height: 14px;
                    text-align: center; color: {t.text}; font-size: 11px; }}
    QProgressBar::chunk {{ background: {t.gradient}; border-radius: 7px; }}
    QSplitter::handle {{ background: {t.border}; width: 1px; }}

    /* Textos */
    QLabel {{ color: {t.text}; }}
    QLabel#muted {{ color: {t.muted}; }}
    QLabel#heading {{ font-size: 22px; font-weight: 700; }}
    QFrame#card {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 14px; }}
    QFrame#hero {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 18px; }}
    QLabel#herotitle {{ font-size: 20px; font-weight: 700; }}
    QLabel#herokicker {{ color: {t.accent}; font-size: 11px; font-weight: 700; letter-spacing: 2px; }}
    """
