"""Testes do visual futurista: tema padrão, janela sem moldura, destaque e leitura imersiva."""
from PySide6.QtCore import Qt

from leitor_universal.library import Library
from leitor_universal.themes import DEFAULT_THEME, THEMES, stylesheet


def _janela(tmp_path, preparar=None):
    from leitor_universal.app import MainWindow
    lib = Library(tmp_path / "dados")
    if preparar:
        preparar(lib)
    janela = MainWindow(lib)
    janela.resize(1200, 800)
    janela.show()
    return lib, janela


def test_tema_futurista_vira_padrao_uma_vez(tmp_path, qapp):
    lib, janela = _janela(tmp_path, lambda l: l.set_setting("tema", "claro"))
    assert DEFAULT_THEME == "futurista" and lib.setting("tema") == "futurista"
    janela.set_theme("sepia")
    janela.close()
    lib2, _ = _janela(tmp_path)  # na segunda abertura a escolha do usuário é respeitada
    assert lib2.setting("tema") == "sepia"


def test_todos_os_temas_geram_estilo():
    for theme in THEMES.values():
        css = stylesheet(theme)
        assert theme.accent in css and "QToolButton#nav:checked" in css


def test_janela_sem_moldura_com_barra_propria(tmp_path, qapp):
    _, janela = _janela(tmp_path)
    assert janela.windowFlags() & Qt.FramelessWindowHint
    assert janela.titlebar.isVisible()
    janela.setWindowTitle("Duna — Leitor Universal")
    assert janela.titlebar.title.text() == "Duna — Leitor Universal"
    margem = janela.frame.layout().contentsMargins().left()
    janela.showMaximized()
    assert janela.frame.layout().contentsMargins().left() == 0 < margem


def test_moldura_padrao_do_windows_opcional(tmp_path, qapp):
    _, janela = _janela(tmp_path, lambda l: l.set_setting("moldura_nativa", "1"))
    assert not janela.windowFlags() & Qt.FramelessWindowHint
    assert not janela.titlebar.isVisible()


def test_destaque_continue_lendo(amostras, tmp_path, qapp):
    lib, janela = _janela(tmp_path)
    livro = lib.import_file(amostras / "teste.pdf")
    card = janela.library_view.continue_card
    janela.library_view.refresh()
    assert not card.isVisible()  # nada lido ainda
    janela.open_book(livro.id)
    janela.reader.goto(14)
    janela.show_library()
    assert card.isVisible() and card.title.text() == "Livro de Teste PDF"
    assert 0.4 < card.ring.value < 0.6 and "página 15 de 30" in card.detail.text()


def test_leitura_imersiva_esmaece_as_barras(amostras, tmp_path, qapp):
    lib, janela = _janela(tmp_path)
    janela.open_book(lib.import_file(amostras / "teste.pdf").id)
    leitor = janela.reader
    leitor._chrome_timer.timeout.emit()
    assert leitor._chrome_hidden
    leitor._fade_chrome(True)
    assert not leitor._chrome_hidden and leitor._chrome_timer.isActive()

    lib.set_setting("leitura_imersiva", "0")
    janela.show_library()
    janela.open_book(lib.all_books()[0].id)
    janela.reader._chrome_timer.timeout.emit()
    assert not janela.reader._chrome_hidden
