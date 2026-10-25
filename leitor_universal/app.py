"""Janela principal: alterna entre biblioteca e leitor, importa arquivos e guarda preferências."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import time

from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QInputDialog, QMainWindow, QMessageBox, QProgressDialog,
    QStackedWidget,
)

from . import __version__, updater
from .documents import ALL_FORMATS, BOOK_EXTS, is_supported, open_document
from .library import Library
from .library_view import LibraryView
from .reader import ReaderWidget
from .themes import THEMES, apply_theme

APP_NAME = "Leitor Universal"
UPDATE_CHECK_INTERVAL = 12 * 3600  # verificação automática no máximo a cada 12 h
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
        self.reader.back_requested.connect(self.show_library)
        self.reader.fullscreen_requested.connect(self.toggle_fullscreen)
        self.reader.theme_changed.connect(self.set_theme)

        geometry = library.setting("geometria")
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode()))
        self.set_theme(theme.key)

        self._update_thread = None
        self._download_thread = None
        self._download_dialog = None
        QTimer.singleShot(4000, self._auto_check_updates)

    # ------------------------------------------------------- atualizações
    def _auto_check_updates(self) -> None:
        last = float(self.library.setting("atualizacao_verificada_em", "0") or 0)
        if time.time() - last >= UPDATE_CHECK_INTERVAL:
            self.check_for_updates(manual=False)

    def check_for_updates(self, manual: bool) -> None:
        if self._update_thread and self._update_thread.isRunning():
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
        self.library.set_setting("atualizacao_verificada_em", str(time.time()))
        newer = updater.is_newer(release.version)
        skipped = self.library.setting("atualizacao_ignorada") == release.version
        if not newer or (skipped and not manual):
            if manual:
                QMessageBox.information(self, "Atualizações",
                                        f"Você já está na versão mais recente ({__version__}).")
            return

        box = QMessageBox(self)
        box.setWindowTitle("Atualização disponível")
        box.setIcon(QMessageBox.Information)
        box.setText(f"<b>Leitor Universal {release.version}</b> está disponível "
                    f"(você usa a {__version__}).")
        box.setInformativeText(
            "Deseja atualizar agora? Sua biblioteca e o progresso de leitura são preservados."
            if updater.is_installed_build()
            else "Você está executando a partir do código-fonte; a página da release será aberta.")
        if release.notes:
            box.setDetailedText(release.notes)
        update_btn = box.addButton("Atualizar agora", QMessageBox.AcceptRole)
        box.addButton("Depois", QMessageBox.RejectRole)
        skip_btn = box.addButton("Ignorar esta versão", QMessageBox.DestructiveRole)
        box.exec()
        if box.clickedButton() is skip_btn:
            self.library.set_setting("atualizacao_ignorada", release.version)
        elif box.clickedButton() is update_btn:
            if updater.is_installed_build() and release.installer_url:
                self._download_update(release)
            else:
                QDesktopServices.openUrl(QUrl(release.page_url))

    def _download_update(self, release) -> None:
        dialog = QProgressDialog(f"Baixando a versão {release.version}…", None, 0, 100, self)
        dialog.setWindowTitle("Atualizando")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)
        self._download_dialog = dialog
        thread = updater.UpdateDownloadThread(release, self)
        thread.progress.connect(lambda d, t: dialog.setValue(int(d * 100 / t)) if t else None)
        thread.done.connect(self._on_update_downloaded)
        self._download_thread = thread
        thread.start()

    def _on_update_downloaded(self, path: str, error: str) -> None:
        self._download_dialog.close()
        if error:
            QMessageBox.warning(self, "Falha na atualização", error)
            return
        updater.launch_installer(Path(path))
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
        """Importa arquivos/pastas; se houver um único arquivo, já abre para leitura."""
        files: list[Path] = []
        for raw in paths:
            p = Path(raw)
            if p.is_dir():
                files.extend(f for f in sorted(p.rglob("*")) if f.suffix.lower() in BOOK_EXTS)
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
        folder = QFileDialog.getExistingDirectory(self, "Adicionar pasta de livros", start)
        if folder:
            self.library.set_setting("ultima_pasta", folder)
            self.open_paths([folder])

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
    icon_path = Path(__file__).with_name("icone.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    library = Library(data_dir)
    window = MainWindow(library)
    window.show()
    if len(argv) > 1:
        window.open_paths(argv[1:])
    return app.exec()
