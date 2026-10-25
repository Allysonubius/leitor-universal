from pathlib import Path

import pytest

from leitor_universal import updater
from leitor_universal.documents import open_document
from leitor_universal.library import Library

FORMATOS = ["teste.pdf", "livro.epub", "romance.txt", "notas.md", "doc.rtf", "documento.docx",
            "pagina.html", "quadrinho.cbz", "imagem.png"]


@pytest.mark.parametrize("nome", FORMATOS)
def test_abre_todos_os_formatos(amostras: Path, tmp_path: Path, nome: str):
    loaded = open_document(amostras / nome, tmp_path)
    assert loaded.doc.page_count > 0
    loaded.doc[0].get_pixmap()


def test_texto_ansi_preserva_acentos(amostras: Path, tmp_path: Path):
    loaded = open_document(amostras / "romance.txt", tmp_path)
    assert "CAPÍTULO 1" in loaded.doc[0].get_text()
    assert loaded.doc.get_toc()


def test_biblioteca_reconhece_arquivo_movido(amostras: Path, tmp_path: Path):
    lib = Library(tmp_path / "dados")
    original = lib.import_file(amostras / "teste.pdf")
    copia = tmp_path / "renomeado.pdf"
    copia.write_bytes((amostras / "teste.pdf").read_bytes())
    movido = lib.import_file(copia)
    assert movido.id == original.id
    assert movido.path == str(copia.resolve())
    assert movido.author == "Autora Exemplo"


def test_posicao_sobrevive_a_mudanca_de_fonte_e_reabertura(amostras: Path, tmp_path: Path, qapp):
    from leitor_universal.app import MainWindow

    lib = Library(tmp_path / "dados")
    janela = MainWindow(lib)
    janela.resize(1200, 800)
    janela.show()
    livro = lib.import_file(amostras / "livro.epub")
    janela.open_book(livro.id)
    leitor = janela.reader
    leitor.goto(6)
    posicao = leitor._position_of(6)
    leitor._change_font(+4)
    assert leitor._position_of(leitor.page_index) == posicao

    janela.show_library()
    janela.open_book(livro.id)
    assert janela.reader._position_of(janela.reader.page_index) == posicao
    janela.show_library()
    assert lib.get(livro.id).font_size == 16


def test_busca_encontra_termo(amostras: Path, tmp_path: Path, qapp):
    from leitor_universal.app import MainWindow

    lib = Library(tmp_path / "dados")
    janela = MainWindow(lib)
    janela.open_book(lib.import_file(amostras / "teste.pdf").id)
    leitor = janela.reader
    leitor.search_edit.setText("agulha")
    leitor.start_search()
    while leitor._search_timer.isActive():
        leitor._search_step()
    assert len(leitor._search_results) == 1
    assert leitor.page_index == 17


@pytest.mark.parametrize("candidata,atual,esperado", [
    ("1.0.1", "1.0.0", True), ("1.10.0", "1.9.9", True), ("1.0.0", "1.0.0", False),
    ("0.9.0", "1.0.0", False), ("v2.0.0", "1.5.3", True),
])
def test_comparacao_de_versoes(candidata, atual, esperado):
    assert updater.is_newer(candidata.lstrip("v"), atual) is esperado
