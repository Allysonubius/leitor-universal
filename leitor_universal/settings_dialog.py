"""Janela de Configurações: pastas da biblioteca, formatos, aparência e atualizações."""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from . import __version__
from .documents import DEFAULT_FORMAT_GROUPS, FORMAT_GROUPS, find_libreoffice
from .library import Library
from .themes import THEMES


@dataclass
class Preferences:
    """Preferências persistidas na tabela settings."""
    recursive: bool = True
    watch: bool = True
    formats: tuple[str, ...] = DEFAULT_FORMAT_GROUPS
    theme: str = "claro"
    open_last: bool = False
    auto_update: bool = True
    folders: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, library: Library) -> "Preferences":
        flag = lambda key, default: library.setting(key, "1" if default else "0") == "1"
        formats = library.setting("formatos")
        return cls(
            recursive=flag("pastas_subpastas", True),
            watch=flag("pastas_monitorar", True),
            formats=tuple(f for f in formats.split(",") if f in FORMAT_GROUPS) if formats is not None
            else DEFAULT_FORMAT_GROUPS,
            theme=library.setting("tema", "claro") if library.setting("tema", "claro") in THEMES else "claro",
            open_last=flag("abrir_ultimo", False),
            auto_update=flag("atualizacao_automatica", True),
            folders=library.folders(),
        )

    def save(self, library: Library) -> None:
        library.set_setting("pastas_subpastas", "1" if self.recursive else "0")
        library.set_setting("pastas_monitorar", "1" if self.watch else "0")
        library.set_setting("formatos", ",".join(self.formats))
        library.set_setting("tema", self.theme)
        library.set_setting("abrir_ultimo", "1" if self.open_last else "0")
        library.set_setting("atualizacao_automatica", "1" if self.auto_update else "0")


class SettingsDialog(QDialog):
    def __init__(self, prefs: Preferences, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurações")
        self.setMinimumWidth(560)
        self.prefs = prefs
        self.removed_folders: list[str] = []
        self.check_updates_now = False

        # Pastas
        folders_box = QGroupBox("Pastas da biblioteca")
        hint = QLabel("Os livros destas pastas entram na biblioteca automaticamente, em qualquer formato.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        self.folder_list = QListWidget()
        self.folder_list.setMinimumHeight(130)
        for folder in prefs.folders:
            self.folder_list.addItem(QListWidgetItem(folder))
        add_btn = QPushButton("＋ Adicionar pasta…")
        add_btn.clicked.connect(self._add_folder)
        self.remove_btn = QPushButton("Remover")
        self.remove_btn.clicked.connect(self._remove_folder)
        buttons = QHBoxLayout()
        buttons.addWidget(add_btn)
        buttons.addWidget(self.remove_btn)
        buttons.addStretch(1)
        self.recursive_cb = QCheckBox("Incluir subpastas")
        self.recursive_cb.setChecked(prefs.recursive)
        self.watch_cb = QCheckBox("Atualizar a biblioteca sozinha quando arquivos forem adicionados ou removidos")
        self.watch_cb.setChecked(prefs.watch)
        fl = QVBoxLayout(folders_box)
        fl.addWidget(hint)
        fl.addWidget(self.folder_list)
        fl.addLayout(buttons)
        fl.addWidget(self.recursive_cb)
        fl.addWidget(self.watch_cb)

        # Formatos
        formats_box = QGroupBox("Formatos incluídos")
        fmt_layout = QVBoxLayout(formats_box)
        self.format_cbs: dict[str, QCheckBox] = {}
        for key, (label, _) in FORMAT_GROUPS.items():
            cb = QCheckBox(label)
            cb.setChecked(key in prefs.formats)
            fmt_layout.addWidget(cb)
            self.format_cbs[key] = cb
        if not find_libreoffice():
            note = QLabel("DOC, ODT, PPTX e XLSX exigem o LibreOffice instalado; DOCX funciona sem ele.")
            note.setObjectName("muted")
            note.setWordWrap(True)
            fmt_layout.addWidget(note)

        # Geral
        general_box = QGroupBox("Geral")
        form = QFormLayout(general_box)
        self.theme_combo = QComboBox()
        for theme in THEMES.values():
            self.theme_combo.addItem(theme.label, theme.key)
        self.theme_combo.setCurrentIndex(list(THEMES).index(prefs.theme))
        form.addRow("Tema:", self.theme_combo)
        self.open_last_cb = QCheckBox("Abrir o último livro ao iniciar")
        self.open_last_cb.setChecked(prefs.open_last)
        form.addRow(self.open_last_cb)
        self.auto_update_cb = QCheckBox("Procurar atualizações automaticamente")
        self.auto_update_cb.setChecked(prefs.auto_update)
        check_now = QPushButton("Verificar agora")
        check_now.clicked.connect(self._check_now)
        update_row = QHBoxLayout()
        update_row.addWidget(self.auto_update_cb)
        update_row.addStretch(1)
        update_row.addWidget(check_now)
        form.addRow(update_row)
        version = QLabel(f"Leitor Universal {__version__}")
        version.setObjectName("muted")
        form.addRow(version)

        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setText("Salvar")
        box.button(QDialogButtonBox.Cancel).setText("Cancelar")
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(folders_box)
        layout.addWidget(formats_box)
        layout.addWidget(general_box)
        layout.addWidget(box)
        self._update_buttons()
        self.folder_list.currentRowChanged.connect(self._update_buttons)

    def _update_buttons(self) -> None:
        self.remove_btn.setEnabled(self.folder_list.currentItem() is not None)

    def _folders(self) -> list[str]:
        return [self.folder_list.item(i).text() for i in range(self.folder_list.count())]

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Escolha uma pasta com livros")
        if folder and folder not in self._folders():
            self.folder_list.addItem(QListWidgetItem(folder))
            if folder in self.removed_folders:
                self.removed_folders.remove(folder)

    def _remove_folder(self) -> None:
        item = self.folder_list.currentItem()
        if not item:
            return
        answer = QMessageBox.question(
            self, "Remover pasta",
            f"Remover a pasta da biblioteca?\n\n{item.text()}\n\n"
            "Os livros dela saem da biblioteca, mas os arquivos no disco NÃO são apagados.")
        if answer == QMessageBox.Yes:
            if item.text() in self.prefs.folders:
                self.removed_folders.append(item.text())
            self.folder_list.takeItem(self.folder_list.row(item))

    def _check_now(self) -> None:
        self.check_updates_now = True
        self._accept()

    def _accept(self) -> None:
        formats = tuple(k for k, cb in self.format_cbs.items() if cb.isChecked())
        if not formats:
            QMessageBox.warning(self, "Formatos", "Selecione pelo menos um formato.")
            return
        self.prefs = Preferences(
            recursive=self.recursive_cb.isChecked(),
            watch=self.watch_cb.isChecked(),
            formats=formats,
            theme=self.theme_combo.currentData(),
            open_last=self.open_last_cb.isChecked(),
            auto_update=self.auto_update_cb.isChecked(),
            folders=self._folders(),
        )
        self.accept()
