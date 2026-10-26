"""Aviso de atualização obrigatória com as novidades de cada versão."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextBrowser, QVBoxLayout,
)

from . import __version__
from .updater import Release


class UpdateDialog(QDialog):
    """Não oferece "Depois": fechar a janela encerra o aplicativo (atualização obrigatória)."""

    update_requested = Signal()

    def __init__(self, release: Release, icon: QPixmap | None, installable: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Atualização obrigatória")
        self.setModal(True)
        self.setMinimumSize(520, 440)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        logo = QLabel()
        if icon and not icon.isNull():
            logo.setPixmap(icon.scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        title = QLabel(f"<span style='font-size:17px; font-weight:600'>"
                       f"Leitor Universal {release.version}</span><br/>"
                       f"Você está usando a versão {__version__}.")
        title.setTextFormat(Qt.RichText)
        top = QHBoxLayout()
        top.addWidget(logo, 0, Qt.AlignTop)
        top.addWidget(title, 1)

        intro = QLabel(
            "Esta atualização é necessária para continuar usando o aplicativo. "
            "Sua biblioteca, o progresso de leitura e os marcadores são preservados."
            if installable else
            "Você está executando a partir do código-fonte: baixe a nova versão na página da release.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")

        heading = QLabel("<b>O que há de novo</b>")
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setMarkdown(release.notes or "- Melhorias e correções.")

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(True)
        self.progress.hide()
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)

        self.update_btn = QPushButton("Atualizar agora" if installable else "Abrir página da versão")
        self.update_btn.setObjectName("primary")
        self.update_btn.setDefault(True)
        self.update_btn.clicked.connect(self.update_requested.emit)
        buttons = QHBoxLayout()
        self.close_btn = QPushButton("Fechar o aplicativo" if installable else "Continuar")
        self.close_btn.clicked.connect(self.reject)
        buttons.addWidget(self.close_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.update_btn)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addLayout(top)
        layout.addWidget(intro)
        layout.addWidget(heading)
        layout.addWidget(self.notes, 1)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addLayout(buttons)

    def show_downloading(self) -> None:
        self.update_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.status.setText("Baixando e verificando a atualização…")

    def set_progress(self, done: int, total: int) -> None:
        if total:
            self.progress.setValue(int(done * 100 / total))

    def show_error(self, message: str) -> None:
        self.progress.hide()
        self.status.setText(f"Não foi possível atualizar: {message}")
        self.update_btn.setText("Tentar novamente")
        self.update_btn.setEnabled(True)
        self.close_btn.setEnabled(True)
