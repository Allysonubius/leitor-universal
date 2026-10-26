"""Janela de Configurações: biblioteca, leitura, sincronização/backup e atualizações."""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSlider,
    QTabWidget, QVBoxLayout, QWidget,
)

from . import __version__
from .documents import DEFAULT_FORMAT_GROUPS, FORMAT_GROUPS, find_libreoffice
from .library import Library
from .themes import DEFAULT_THEME, THEMES


@dataclass
class Preferences:
    """Preferências persistidas na tabela settings."""
    recursive: bool = True
    watch: bool = True
    formats: tuple[str, ...] = DEFAULT_FORMAT_GROUPS
    theme: str = DEFAULT_THEME
    open_last: bool = False
    folders: list[str] = field(default_factory=list)
    voice: str = ""
    voice_rate: float = 0.0
    sync_folder: str = ""
    native_frame: bool = False
    immersive: bool = True

    @classmethod
    def load(cls, library: Library) -> "Preferences":
        flag = lambda key, default: library.setting(key, "1" if default else "0") == "1"
        formats = library.setting("formatos")
        theme = library.setting("tema", DEFAULT_THEME)
        return cls(
            recursive=flag("pastas_subpastas", True),
            watch=flag("pastas_monitorar", True),
            formats=tuple(f for f in formats.split(",") if f in FORMAT_GROUPS) if formats is not None
            else DEFAULT_FORMAT_GROUPS,
            theme=theme if theme in THEMES else DEFAULT_THEME,
            open_last=flag("abrir_ultimo", False),
            folders=library.folders(),
            voice=library.setting("voz", "") or "",
            voice_rate=float(library.setting("voz_velocidade", "0") or 0),
            sync_folder=library.setting("sync_pasta", "") or "",
            native_frame=flag("moldura_nativa", False),
            immersive=flag("leitura_imersiva", True),
        )

    def save(self, library: Library) -> None:
        library.set_setting("pastas_subpastas", "1" if self.recursive else "0")
        library.set_setting("pastas_monitorar", "1" if self.watch else "0")
        library.set_setting("formatos", ",".join(self.formats))
        library.set_setting("tema", self.theme)
        library.set_setting("abrir_ultimo", "1" if self.open_last else "0")
        library.set_setting("voz", self.voice)
        library.set_setting("voz_velocidade", f"{self.voice_rate:.2f}")
        library.set_setting("sync_pasta", self.sync_folder)
        library.set_setting("moldura_nativa", "1" if self.native_frame else "0")
        library.set_setting("leitura_imersiva", "1" if self.immersive else "0")


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


class SettingsDialog(QDialog):
    backup_requested = Signal()
    restore_requested = Signal()
    sync_now_requested = Signal()

    def __init__(self, prefs: Preferences, voices: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurações")
        self.setMinimumWidth(600)
        self.prefs = prefs
        self.removed_folders: list[str] = []
        self.check_updates_now = False

        tabs = QTabWidget()
        tabs.addTab(self._library_tab(prefs), "Biblioteca")
        tabs.addTab(self._reading_tab(prefs, voices or []), "Leitura")
        tabs.addTab(self._sync_tab(prefs), "Sincronização e backup")
        tabs.addTab(self._about_tab(), "Atualizações")

        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setText("Salvar")
        box.button(QDialogButtonBox.Cancel).setText("Cancelar")
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(box)
        self._update_buttons()

    # ------------------------------------------------------------- abas
    def _library_tab(self, prefs: Preferences) -> QWidget:
        tab = QWidget()
        folders_box = QGroupBox("Pastas da biblioteca")
        self.folder_list = QListWidget()
        self.folder_list.setMinimumHeight(130)
        for folder in prefs.folders:
            self.folder_list.addItem(QListWidgetItem(folder))
        self.folder_list.currentRowChanged.connect(self._update_buttons)
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
        fl.addWidget(_muted("Os livros destas pastas entram na biblioteca automaticamente, em qualquer formato."))
        fl.addWidget(self.folder_list)
        fl.addLayout(buttons)
        fl.addWidget(self.recursive_cb)
        fl.addWidget(self.watch_cb)

        formats_box = QGroupBox("Formatos incluídos")
        fmt_layout = QVBoxLayout(formats_box)
        self.format_cbs: dict[str, QCheckBox] = {}
        for key, (label, _) in FORMAT_GROUPS.items():
            cb = QCheckBox(label)
            cb.setChecked(key in prefs.formats)
            fmt_layout.addWidget(cb)
            self.format_cbs[key] = cb
        if not find_libreoffice():
            fmt_layout.addWidget(_muted("DOC, ODT, PPTX e XLSX exigem o LibreOffice instalado; DOCX funciona sem ele."))

        layout = QVBoxLayout(tab)
        layout.addWidget(folders_box)
        layout.addWidget(formats_box)
        layout.addStretch(1)
        return tab

    def _reading_tab(self, prefs: Preferences, voices: list[str]) -> QWidget:
        tab = QWidget()
        general = QGroupBox("Geral")
        form = QFormLayout(general)
        self.theme_combo = QComboBox()
        for theme in THEMES.values():
            self.theme_combo.addItem(theme.label, theme.key)
        self.theme_combo.setCurrentIndex(list(THEMES).index(prefs.theme))
        form.addRow("Tema:", self.theme_combo)
        self.open_last_cb = QCheckBox("Abrir o último livro ao iniciar")
        self.open_last_cb.setChecked(prefs.open_last)
        form.addRow(self.open_last_cb)
        self.immersive_cb = QCheckBox("Leitura imersiva: esconder as barras enquanto você lê")
        self.immersive_cb.setChecked(prefs.immersive)
        form.addRow(self.immersive_cb)
        self.native_frame_cb = QCheckBox("Usar a moldura padrão do Windows (vale ao reabrir o app)")
        self.native_frame_cb.setChecked(prefs.native_frame)
        form.addRow(self.native_frame_cb)

        voice_box = QGroupBox("Leitura em voz alta")
        vform = QFormLayout(voice_box)
        self.voice_combo = QComboBox()
        self.voice_combo.addItem("Automática (português, se houver)", "")
        for name in voices:
            self.voice_combo.addItem(name, name)
        self.voice_combo.setCurrentIndex(max(self.voice_combo.findData(prefs.voice), 0))
        self.rate_slider = QSlider(Qt.Horizontal)
        self.rate_slider.setRange(-10, 10)
        self.rate_slider.setValue(int(round(prefs.voice_rate * 10)))
        self.rate_label = QLabel()
        self.rate_slider.valueChanged.connect(self._show_rate)
        self._show_rate(self.rate_slider.value())
        rate_row = QHBoxLayout()
        rate_row.addWidget(self.rate_slider, 1)
        rate_row.addWidget(self.rate_label)
        vform.addRow("Voz:", self.voice_combo)
        vform.addRow("Velocidade:", rate_row)
        if not voices:
            vform.addRow(_muted("Nenhuma voz encontrada. Instale vozes em Configurações do Windows → Hora e idioma → Fala."))

        layout = QVBoxLayout(tab)
        layout.addWidget(general)
        layout.addWidget(voice_box)
        layout.addStretch(1)
        return tab

    def _sync_tab(self, prefs: Preferences) -> QWidget:
        tab = QWidget()
        sync_box = QGroupBox("Sincronizar entre computadores")
        self.sync_label = QLabel(prefs.sync_folder or "Desativada")
        self.sync_label.setWordWrap(True)
        choose = QPushButton("Escolher pasta…")
        choose.clicked.connect(self._choose_sync)
        clear = QPushButton("Desativar")
        clear.clicked.connect(lambda: self._set_sync(""))
        now = QPushButton("Sincronizar agora")
        now.clicked.connect(self.sync_now_requested.emit)
        row = QHBoxLayout()
        row.addWidget(choose)
        row.addWidget(clear)
        row.addStretch(1)
        row.addWidget(now)
        sl = QVBoxLayout(sync_box)
        sl.addWidget(_muted(
            "Escolha uma pasta do OneDrive, Google Drive ou Dropbox, a mesma em todos os seus PCs. "
            "Progresso, marcadores, grifos e coleções são combinados automaticamente. Os livros são "
            "reconhecidos pelo conteúdo do arquivo, então cada PC precisa ter os mesmos arquivos."))
        sl.addWidget(self.sync_label)
        sl.addLayout(row)

        backup_box = QGroupBox("Backup")
        backup_btn = QPushButton("Fazer backup agora…")
        backup_btn.clicked.connect(self.backup_requested.emit)
        restore_btn = QPushButton("Restaurar um backup…")
        restore_btn.clicked.connect(self.restore_requested.emit)
        brow = QHBoxLayout()
        brow.addWidget(backup_btn)
        brow.addWidget(restore_btn)
        brow.addStretch(1)
        bl = QVBoxLayout(backup_box)
        bl.addWidget(_muted("Guarda biblioteca, progresso, marcadores, grifos, coleções, estatísticas e "
                            "preferências em um único arquivo .zip. Os livros em si não entram no backup."))
        bl.addLayout(brow)

        layout = QVBoxLayout(tab)
        layout.addWidget(sync_box)
        layout.addWidget(backup_box)
        layout.addStretch(1)
        self._sync_folder = prefs.sync_folder
        return tab

    def _about_tab(self) -> QWidget:
        tab = QWidget()
        check_now = QPushButton("Verificar atualizações agora")
        check_now.clicked.connect(self._check_now)
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel(f"<b>Leitor Universal {__version__}</b>"))
        layout.addWidget(_muted("Atualizações são obrigatórias e instaladas automaticamente ao abrir o aplicativo."))
        layout.addWidget(check_now, 0, Qt.AlignLeft)
        layout.addStretch(1)
        return tab

    # ----------------------------------------------------------- ações
    def _show_rate(self, value: int) -> None:
        self.rate_label.setText("normal" if value == 0 else f"{'+' if value > 0 else ''}{value * 10}%")

    def _choose_sync(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Pasta sincronizada (OneDrive, Google Drive…)")
        if folder:
            self._set_sync(folder)

    def _set_sync(self, folder: str) -> None:
        self._sync_folder = folder
        self.sync_label.setText(folder or "Desativada")

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
            folders=self._folders(),
            voice=self.voice_combo.currentData() or "",
            voice_rate=self.rate_slider.value() / 10,
            sync_folder=self._sync_folder,
            native_frame=self.native_frame_cb.isChecked(),
            immersive=self.immersive_cb.isChecked(),
        )
        self.accept()
