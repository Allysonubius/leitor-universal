"""Janela principal: alterna entre biblioteca e leitor, importa arquivos e guarda preferências."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


from PySide6.QtCore import QByteArray, QFileSystemWatcher, QLibraryInfo, Qt, QTimer, QTranslator, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QInputDialog, QMainWindow, QMessageBox, QProgressDialog,
    QStackedWidget,
)

from . import __version__, updater
from .documents import ALL_FORMATS, extensions_for, is_supported, open_document
from .library import Library
from .library_view import LibraryView
from .reader import ReaderWidget
from .scanner import ScanThread
from .settings_dialog import Preferences, SettingsDialog
from .update_dialog import UpdateDialog
from .themes import THEMES, apply_theme

APP_NAME = "Leitor Universal"
UPDATE_CHECK_INTERVAL_MS = 6 * 3600 * 1000  # nova verificação enquanto o app fica aberto
RESYNC_INTERVAL_MS = 10 * 60 * 1000  # varredura periódica das pastas monitoradas
MAX_WATCHED_DIRS = 400
log = logging.getLogger("leitor")


def data_directory() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    path = base / "LeitorUniversal"
    path.mkdir(parents=True, exist_ok=True)
    return path


def file_dialog_filter() -> str:
    patterns = " ".join(f"*{ext}" for ext in sorted(ALL_FORMATS))
    return f"Livros e documentos ({patterns});;Todos os arquivos (*.*)"


class MainWindow(QMainWindow):
    def __init__(self, library: Library):
        super().__init__()
        self.library = library
        self.prefs = Preferences.load(library)
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(1280, 820)

        theme = THEMES.get(library.setting("tema", "claro"), THEMES["claro"])
        self.library_view = LibraryView(library, theme)
        self.reader = ReaderWidget(library)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.library_view)
        self.stack.addWidget(self.reader)
        self.setCentralWidget(self.stack)

        lv = self.library_view
        lv.open_requested.connect(self.open_book)
        lv.add_files_requested.connect(self.choose_files)
        lv.add_folder_requested.connect(self.choose_folder)
        lv.remove_requested.connect(self.remove_book)
        lv.locate_requested.connect(self.locate_book)
        lv.reveal_requested.connect(self.reveal_book)
        lv.edit_requested.connect(self.edit_book)
        lv.check_updates_requested.connect(lambda: self.check_for_updates(manual=True))
        lv.about_requested.connect(self.show_about)
        lv.settings_requested.connect(self.open_settings)
        lv.sync_requested.connect(self.start_sync)
        self.reader.back_requested.connect(self.show_library)
        self.reader.fullscreen_requested.connect(self.toggle_fullscreen)
        self.reader.theme_changed.connect(self.set_theme)

        geometry = library.setting("geometria")
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode()))
        self.set_theme(theme.key)

        # Atualizações são obrigatórias: verifica ao abrir e periodicamente.
        self._update_thread = None
        self._download_thread = None
        self._update_dialog: UpdateDialog | None = None
        self._update_timer = QTimer(self, interval=UPDATE_CHECK_INTERVAL_MS,
                                    timeout=lambda: self.check_for_updates(manual=False))
        self._update_timer.start()
        QTimer.singleShot(800, lambda: self.check_for_updates(manual=False))

        self._scan_thread: ScanThread | None = None
        self._sync_again = False
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(lambda _: self._sync_debounce.start())
        self._sync_debounce = QTimer(self, singleShot=True, interval=3000, timeout=self.start_sync)
        self._resync_timer = QTimer(self, interval=RESYNC_INTERVAL_MS, timeout=self.start_sync)
        self._status_timer = QTimer(self, singleShot=True, interval=6000,
                                    timeout=lambda: self.library_view.set_sync_status(""))
        self._apply_watch()
        if self.library.folders():
            QTimer.singleShot(300, self.start_sync)

    # ------------------------------------------------------ pastas e sincronização
    def _apply_watch(self) -> None:
        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())
        if not self.prefs.watch:
            self._resync_timer.stop()
            return
        dirs: list[str] = []
        for folder in self.library.folders():
            if not Path(folder).is_dir():
                continue
            dirs.append(folder)
            if self.prefs.recursive:
                for root, subdirs, _ in os.walk(folder, onerror=lambda _: None):
                    subdirs[:] = [d for d in subdirs if not d.startswith(".")]
                    dirs.extend(os.path.join(root, d) for d in subdirs)
                    if len(dirs) >= MAX_WATCHED_DIRS:
                        break
        if dirs:
            self._watcher.addPaths(dirs[:MAX_WATCHED_DIRS])
        self._resync_timer.start()

    def start_sync(self) -> None:
        if not self.library.folders():
            return
        if self._scan_thread and self._scan_thread.isRunning():
            self._sync_again = True
            return
        self._status_timer.stop()
        self.library_view.set_sync_status("Sincronizando a biblioteca…")
        thread = ScanThread(self.library.data_dir, extensions_for(self.prefs.formats), self.prefs.recursive, self)
        thread.progress.connect(self._on_sync_progress)
        thread.finished_scan.connect(self._on_sync_finished)
        self._scan_thread = thread
        thread.start()

    def _on_sync_progress(self, done: int, total: int, name: str) -> None:
        if total:
            self.library_view.set_sync_status(f"Sincronizando… {done} de {total}  {name}")

    def _on_sync_finished(self, result) -> None:
        parts = []
        if result.added:
            parts.append(f"{result.added} livro(s) novo(s)")
        if result.updated:
            parts.append(f"{result.updated} atualizado(s)")
        if result.missing:
            parts.append(f"{result.missing} arquivo(s) não encontrado(s)")
        if result.errors:
            parts.append(f"{len(result.errors)} arquivo(s) não puderam ser lidos (detalhes em leitor.log)")
        self.library_view.set_sync_status(
            "Biblioteca sincronizada: " + ", ".join(parts) + "." if parts else "")
        if parts:
            self._status_timer.start()
        if self.stack.currentWidget() is self.library_view:
            self.library_view.refresh()
        self._apply_watch()
        if self._sync_again:
            self._sync_again = False
            QTimer.singleShot(500, self.start_sync)

    def add_library_folder(self, folder: str) -> None:
        self.library.add_folder(folder)
        self.prefs.folders = self.library.folders()
        self.library_view.refresh()
        self._apply_watch()
        self.start_sync()

    def open_settings(self) -> None:
        dialog = SettingsDialog(Preferences.load(self.library), self)
        if dialog.exec() != SettingsDialog.Accepted:
            return
        old, new = self.prefs, dialog.prefs
        for folder in dialog.removed_folders:
            self.library.remove_folder(folder)
        for folder in new.folders:
            if folder not in old.folders:
                self.library.add_folder(folder)
        new.save(self.library)
        new.folders = self.library.folders()
        self.prefs = new
        if new.theme != old.theme:
            self.set_theme(new.theme)
        self._apply_watch()
        self.library_view.refresh()
        if (new.folders != old.folders or new.formats != old.formats
                or new.recursive != old.recursive):
            self.start_sync()
        if dialog.check_updates_now:
            self.check_for_updates(manual=True)

    def open_last_book(self) -> None:
        last = self.library.last_read()
        if last:
            self.open_book(last.id)

    # ------------------------------------------------------- atualizações
    def check_for_updates(self, manual: bool) -> None:
        if (self._update_thread and self._update_thread.isRunning()) or self._update_dialog:
            return
        self._update_thread = updater.UpdateCheckThread(self)
        self._update_thread.finished_check.connect(
            lambda release, error: self._on_update_checked(release, error, manual))
        self._update_thread.start()

    def _on_update_checked(self, release, error: str, manual: bool) -> None:
        if error:
            log.warning("Verificação de atualização falhou: %s", error)
            if manual:
                QMessageBox.warning(self, "Atualizações", error)
            return
        if release is None:
            if manual:
                QMessageBox.information(self, "Atualizações",
                                        f"Você já está na versão mais recente ({__version__}).")
            return
        log.info("Atualização obrigatória disponível: %s", release.version)
        installable = updater.is_installed_build() and bool(release.installer_url)
        icon = QPixmap(str(Path(__file__).with_name("icone.png")))
        dialog = UpdateDialog(release, icon, installable, self)
        dialog.update_requested.connect(
            lambda: self._start_update(release) if installable else self._open_release_page(release))
        dialog.rejected.connect(lambda: self._update_declined(installable))
        self._update_dialog = dialog
        dialog.open()

    def _open_release_page(self, release) -> None:
        QDesktopServices.openUrl(QUrl(release.page_url))
        self._update_dialog.accept()
        self._update_dialog = None

    def _update_declined(self, installable: bool) -> None:
        self._update_dialog = None
        if installable:
            log.info("Atualização recusada: encerrando o aplicativo.")
            self.close()

    def _start_update(self, release) -> None:
        dialog = self._update_dialog
        dialog.show_downloading()
        thread = updater.UpdateDownloadThread(release, self)
        thread.progress.connect(dialog.set_progress)
        thread.done.connect(self._on_update_downloaded)
        self._download_thread = thread
        thread.start()

    def _on_update_downloaded(self, path: str, error: str) -> None:
        if error:
            log.warning("Falha ao baixar a atualização: %s", error)
            self._update_dialog.show_error(error)
            return
        updater.launch_installer(Path(path))
        self._update_dialog.accept()
        self.close()

    def show_about(self) -> None:
        QMessageBox.about(
            self, "Sobre",
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>Leitor de livros universal com biblioteca, marcadores e retomada de leitura.</p>"
            f"<p><a href='https://github.com/{updater.REPOSITORY}'>github.com/{updater.REPOSITORY}</a></p>")

    # ------------------------------------------------------------ temas
    def set_theme(self, key: str) -> None:
        theme = THEMES[key]
        apply_theme(QApplication.instance(), theme)
        self.library_view.set_theme(theme)
        self.reader.set_theme(theme)
        self.library.set_setting("tema", key)

    # --------------------------------------------------------- navegação
    def show_library(self) -> None:
        if self.isFullScreen():
            self.toggle_fullscreen()
        self.reader.close_book()
        self.setWindowTitle(APP_NAME)
        self.library_view.refresh()
        self.stack.setCurrentWidget(self.library_view)

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.reader.set_chrome_visible(True)
        elif self.stack.currentWidget() is self.reader:
            self.showFullScreen()
            self.reader.set_chrome_visible(False)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
        else:
            super().keyPressEvent(event)

    # ----------------------------------------------------------- abertura
    def open_book(self, book_id: int) -> None:
        book = self.library.get(book_id)
        if not book:
            return
        if not Path(book.path).exists():
            answer = QMessageBox.question(
                self, "Arquivo não encontrado",
                f"O arquivo de “{book.title}” não foi encontrado em:\n{book.path}\n\nDeseja localizá-lo?")
            if answer != QMessageBox.Yes or not self.locate_book(book_id):
                return
            book = self.library.get(book_id)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            loaded = open_document(book.path, self.library.cache_dir)
        except Exception as exc:
            log.exception("Falha ao abrir %s", book.path)
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Não foi possível abrir", str(exc))
            return
        QApplication.restoreOverrideCursor()
        self.stack.setCurrentWidget(self.reader)
        self.reader.open_book(book, loaded)
        self.setWindowTitle(f"{book.title} — {APP_NAME}")

    def open_paths(self, paths: list[str]) -> None:
        """Pastas viram pastas da biblioteca; arquivos são importados (um único já abre)."""
        files: list[Path] = []
        for raw in paths:
            p = Path(raw)
            if p.is_dir():
                self.add_library_folder(str(p))
            elif p.is_file():
                files.append(p)
        if not files:
            return
        imported, errors = self._import(files)
        if errors:
            details = "\n".join(f"• {name}: {msg}" for name, msg in errors[:15])
            more = f"\n… e mais {len(errors) - 15}" if len(errors) > 15 else ""
            QMessageBox.warning(self, "Alguns arquivos não foram importados", details + more)
        if len(files) == 1 and imported:
            self.open_book(imported[0])
        else:
            self.library_view.refresh()

    def _import(self, files: list[Path]) -> tuple[list[int], list[tuple[str, str]]]:
        imported, errors = [], []
        progress = None
        if len(files) > 3:
            progress = QProgressDialog("Importando livros…", "Cancelar", 0, len(files), self)
            progress.setWindowTitle(APP_NAME)
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(300)
        for i, f in enumerate(files):
            if progress:
                if progress.wasCanceled():
                    break
                progress.setLabelText(f"Importando {f.name}…")
                progress.setValue(i)
                QApplication.processEvents()
            try:
                if not is_supported(f) and len(files) > 1:
                    continue
                imported.append(self.library.import_file(f).id)
            except Exception as exc:
                log.exception("Falha ao importar %s", f)
                errors.append((f.name, str(exc) or exc.__class__.__name__))
        if progress:
            progress.setValue(len(files))
        return imported, errors

    def choose_files(self) -> None:
        start = self.library.setting("ultima_pasta", str(Path.home()))
        files, _ = QFileDialog.getOpenFileNames(self, "Adicionar livros", start, file_dialog_filter())
        if files:
            self.library.set_setting("ultima_pasta", str(Path(files[0]).parent))
            self.open_paths(files)

    def choose_folder(self) -> None:
        start = self.library.setting("ultima_pasta", str(Path.home()))
        folder = QFileDialog.getExistingDirectory(self, "Escolha a pasta onde ficam seus livros", start)
        if folder:
            self.library.set_setting("ultima_pasta", folder)
            self.add_library_folder(folder)

    # ------------------------------------------------------- gerenciamento
    def remove_book(self, book_id: int) -> None:
        book = self.library.get(book_id)
        answer = QMessageBox.question(
            self, "Remover da biblioteca",
            f"Remover “{book.title}” da biblioteca?\n\nO progresso e os marcadores serão apagados. "
            "O arquivo no disco NÃO será excluído.")
        if answer == QMessageBox.Yes:
            self.library.remove(book_id)
            self.library_view.invalidate_cover(book_id)

    def locate_book(self, book_id: int) -> bool:
        book = self.library.get(book_id)
        path, _ = QFileDialog.getOpenFileName(self, f"Localizar “{book.title}”",
                                              str(Path(book.path).parent), file_dialog_filter())
        if not path:
            return False
        self.library.set_path(book_id, path)
        self.library_view.refresh()
        return True

    def reveal_book(self, book_id: int) -> None:
        book = self.library.get(book_id)
        if Path(book.path).exists():
            subprocess.Popen(["explorer", "/select,", os.path.normpath(book.path)])

    def edit_book(self, book_id: int) -> None:
        book = self.library.get(book_id)
        title, ok = QInputDialog.getText(self, "Editar livro", "Título:", text=book.title)
        if not ok:
            return
        author, ok = QInputDialog.getText(self, "Editar livro", "Autor:", text=book.author)
        if ok:
            self.library.update_metadata(book_id, title.strip() or book.title, author.strip())

    # ------------------------------------------------------ arrastar/soltar
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            if self.stack.currentWidget() is self.reader:
                self.show_library()
            self.open_paths(paths)

    def closeEvent(self, event) -> None:
        if self._scan_thread and self._scan_thread.isRunning():
            self._scan_thread.requestInterruption()
            self._scan_thread.wait(5000)
        self.reader.close_book()
        self.library.set_setting("geometria", bytes(self.saveGeometry().toBase64()).decode())
        self.library.close()
        super().closeEvent(event)


def setup_logging(data_dir: Path) -> None:
    handler = RotatingFileHandler(data_dir / "leitor.log", maxBytes=1_000_000, backupCount=2,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    sys.excepthook = lambda *exc: log.critical("Erro não tratado", exc_info=exc)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    data_dir = data_directory()
    setup_logging(data_dir)
    log.info("Iniciando %s %s", APP_NAME, __version__)
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LeitorUniversal.App")
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    import PySide6
    translator = QTranslator(app)
    for folder in (QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath),
                   str(Path(PySide6.__file__).parent / "translations")):
        if translator.load("qtbase_pt_BR", folder):
            app.installTranslator(translator)
            break
    icon_path = Path(__file__).with_name("icone.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    library = Library(data_dir)
    window = MainWindow(library)
    window.show()
    if len(argv) > 1:
        window.open_paths(argv[1:])
    elif window.prefs.open_last:
        QTimer.singleShot(0, window.open_last_book)
    return app.exec()
