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


def test_ctrl_roda_do_mouse_faz_zoom_sobre_a_pagina(amostras: Path, tmp_path: Path, qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    from leitor_universal.app import MainWindow

    lib = Library(tmp_path / "dados")
    janela = MainWindow(lib)
    janela.resize(1200, 800)
    janela.show()
    janela.open_book(lib.import_file(amostras / "teste.pdf").id)
    leitor = janela.reader

    def girar(alvo, delta):
        # Entregue pela janela (como o sistema faz), e não direto ao widget.
        centro = alvo.mapToGlobal(QPointF(alvo.width() / 2, alvo.height() / 2))
        local = QPointF(janela.mapFromGlobal(centro.toPoint()))
        QApplication.sendEvent(janela.windowHandle(), QWheelEvent(
            local, centro, QPoint(), QPoint(0, delta), Qt.NoButton, Qt.ControlModifier, Qt.NoScrollPhase, False))
        QApplication.processEvents()

    inicial = leitor._effective_zoom()
    pagina = leitor.page_index
    girar(leitor.page_label, 120)          # cursor sobre a página
    ampliado = leitor._effective_zoom()
    assert ampliado > inicial and leitor.zoom_mode == "livre"
    girar(leitor.scroll.viewport(), -240)  # cursor na margem
    assert leitor._effective_zoom() < ampliado
    assert leitor.page_index == pagina     # Ctrl + roda não troca de página


@pytest.mark.parametrize("candidata,atual,esperado", [
    ("1.0.1", "1.0.0", True), ("1.10.0", "1.9.9", True), ("1.0.0", "1.0.0", False),
    ("0.9.0", "1.0.0", False), ("v2.0.0", "1.5.3", True),
])
def test_comparacao_de_versoes(candidata, atual, esperado):
    assert updater.is_newer(candidata.lstrip("v"), atual) is esperado


def _release(tag, body, draft=False, prerelease=False):
    return {"tag_name": tag, "body": body, "draft": draft, "prerelease": prerelease,
            "published_at": "2026-10-26T12:00:00Z", "html_url": f"https://x/{tag}",
            "assets": [{"name": f"LeitorUniversal-{tag[1:]}-setup.exe", "browser_download_url": "u"},
                       {"name": "SHA256SUMS.txt", "browser_download_url": "s"}]}


def test_atualizacao_acumula_novidades_das_versoes_puladas():
    dados = [
        _release("v1.3.0-beta", "- teste", prerelease=True),
        _release("v1.2.0", "- Atualização obrigatória\n\n**Full Changelog**: https://github.com/x"),
        _release("v1.1.0", "- Biblioteca por pastas"),
        _release("v1.0.1", "- Manutenção"),
    ]
    pendente = updater.pending_update(dados, current="1.0.1")
    assert pendente.version == "1.2.0"
    assert pendente.installer_name == "LeitorUniversal-1.2.0-setup.exe"
    assert pendente.notes.index("Versão 1.2.0 — 26/10/2026") < pendente.notes.index("Versão 1.1.0")
    assert "Biblioteca por pastas" in pendente.notes
    assert "Full Changelog" not in pendente.notes and "Manutenção" not in pendente.notes
    assert updater.pending_update(dados, current="1.2.0") is None


def test_recusar_atualizacao_obrigatoria_fecha_o_app(tmp_path, qapp, monkeypatch):
    from leitor_universal.app import MainWindow

    monkeypatch.setattr(updater, "is_installed_build", lambda: True)
    janela = MainWindow(Library(tmp_path / "dados"))
    janela.show()
    release = updater.pending_update([_release("v9.0.0", "- Novidade")], current="1.0.0")
    janela._on_update_checked(release, "", manual=False)
    dialogo = janela._update_dialog
    assert dialogo is not None and dialogo.isVisible()
    assert "Depois" not in [b.text() for b in dialogo.findChildren(type(dialogo.update_btn))]
    dialogo.reject()
    assert not janela.isVisible()


def test_notas_da_versao_vem_do_changelog():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from notas_da_versao import CHANGELOG, notes_for
    texto = CHANGELOG.read_text(encoding="utf-8")
    assert "Biblioteca por pastas" in notes_for("1.1.0", texto)
    assert "Primeira versão" not in notes_for("1.1.0", texto)
