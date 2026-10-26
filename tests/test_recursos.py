"""Testes dos recursos da 1.3.0: grifos, coleções, séries, estatísticas, sincronização,
backup, instância única, rolagem contínua, seleção de texto e voz."""
import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

from leitor_universal import online, sync
from leitor_universal.annotations_view import annotations_markdown
from leitor_universal.documents import detect_series
from leitor_universal.library import Library
from leitor_universal.speech import split_sentences
from leitor_universal.stats_view import finished_per_month, reading_streak


@pytest.mark.parametrize("titulo,esperado", [
    ("Duna 2", ("Duna", 2.0)),
    ("Harry Potter - Livro 3", ("Harry Potter", 3.0)),
    ("O Senhor dos Anéis, vol. 1", ("O Senhor dos Anéis", 1.0)),
    ("Fundação #4", ("Fundação", 4.0)),
    ("1984", (None, None)),
    ("Romance de 2019", (None, None)),
    ("Capítulo 12", (None, None)),
])
def test_deteccao_de_series(titulo, esperado):
    assert detect_series(titulo) == esperado


def test_capas_carregadas_sob_demanda(amostras, tmp_path):
    lib = Library(tmp_path / "d")
    livro = lib.import_file(amostras / "teste.pdf")
    assert not hasattr(livro, "cover")
    assert lib.cover(livro.id)[:4] == b"\x89PNG"


def test_grifos_colecoes_e_exportacao(amostras, tmp_path):
    lib = Library(tmp_path / "d")
    livro = lib.import_file(amostras / "teste.pdf")
    uid = lib.add_highlight(livro.id, 3, None, "verde", "um leitor que gostava", "ótimo trecho", [[1, 2, 3, 4]])
    lib.add_bookmark(livro.id, 5, None, "Capítulo 2", "voltar aqui")
    [h] = lib.highlights(livro.id)
    assert (h.uuid, h.color, h.rects, h.book_title) == (uid, "verde", [[1, 2, 3, 4]], "Livro de Teste PDF")
    lib.update_highlight(h.id, color="rosa", note="nova nota")
    assert lib.highlights(livro.id)[0].note == "nova nota"

    md = annotations_markdown(lib)
    assert "## Livro de Teste PDF" in md and "> um leitor que gostava" in md and "voltar aqui" in md

    col = lib.create_collection("Favoritos de 2026")
    lib.set_in_collection(col, livro.id, True)
    assert [(c.name, c.count) for c in lib.collections()] == [("Favoritos de 2026", 1)]
    assert lib.collections_of(livro.id) == {col}

    lib.remove_highlight(h.id)
    assert lib.highlights(livro.id) == [] and uid in lib.deleted_uuids()


def test_estatisticas_sequencia_e_meses():
    hoje = date(2026, 10, 26)
    dias = {(hoje - timedelta(days=i)).isoformat(): {"seconds": 600, "pages": 5} for i in range(4)}
    dias[(hoje - timedelta(days=10)).isoformat()] = {"seconds": 600, "pages": 1}
    dias[(hoje - timedelta(days=11)).isoformat()] = {"seconds": 30, "pages": 1}  # menos de 1 min não conta
    assert reading_streak(dias, hoje) == (4, 4)
    del dias[hoje.isoformat()]
    assert reading_streak(dias, hoje) == (3, 3)  # hoje ainda pode ler: a sequência não quebra
    assert finished_per_month(["2026-01-05T10:00:00", "2026-01-20", "2025-03-01", "2026-10-02"], 2026)[:2] == [2, 0]


def test_registro_diario_de_leitura(amostras, tmp_path):
    lib = Library(tmp_path / "d")
    livro = lib.import_file(amostras / "teste.pdf")
    lib.save_reading_state(livro.id, page=29, position=None, pages=30, progress=1.0, font_size=12,
                           zoom_mode="pagina", zoom=1, two_pages=False, extra_seconds=120, pages_read=7)
    hoje = lib.daily_reading()[date.today().isoformat()]
    assert hoje == {"seconds": 120, "pages": 7}
    assert lib.get(livro.id).finished and lib.finished_dates()


def _duas_bibliotecas(amostras, tmp_path):
    a, b = Library(tmp_path / "pc-a"), Library(tmp_path / "pc-b")
    copia = tmp_path / "outro-caminho"
    copia.mkdir()
    shutil.copy(amostras / "teste.pdf", copia / "renomeado.pdf")
    return a, b, a.import_file(amostras / "teste.pdf"), b.import_file(copia / "renomeado.pdf")


def test_sincronizacao_entre_pcs(amostras, tmp_path):
    a, b, livro_a, livro_b = _duas_bibliotecas(amostras, tmp_path)
    nuvem = tmp_path / "OneDrive"
    nuvem.mkdir()
    a.save_reading_state(livro_a.id, page=12, position=None, pages=30, progress=0.43, font_size=12,
                         zoom_mode="pagina", zoom=1, two_pages=False)
    uid = a.add_highlight(livro_a.id, 12, None, "azul", "trecho do PC A")
    a.set_in_collection(a.create_collection("Ficção"), livro_a.id, True)
    sync.sync_folder(a, nuvem)

    resultado = sync.sync_folder(b, nuvem)
    assert (resultado.devices, resultado.progress, resultado.annotations) == (1, 1, 1)
    assert b.get(livro_b.id).page == 12
    assert [h.uuid for h in b.highlights(livro_b.id)] == [uid]
    assert b.collections()[0].name == "Ficção"

    # Exclusão no PC B chega ao PC A e não "ressuscita" na próxima sincronização.
    b.remove_highlight(b.highlights(livro_b.id)[0].id)
    sync.sync_folder(b, nuvem)
    assert sync.sync_folder(a, nuvem).removed == 1
    assert a.highlights(livro_a.id) == []
    sync.sync_folder(b, nuvem)
    assert b.highlights(livro_b.id) == []
    assert len(list((nuvem / sync.SYNC_DIR_NAME).glob("*.json"))) == 2


def test_progresso_mais_antigo_nao_sobrescreve(amostras, tmp_path):
    a, b, livro_a, livro_b = _duas_bibliotecas(amostras, tmp_path)
    nuvem = tmp_path / "nuvem"
    b.save_reading_state(livro_b.id, page=3, position=None, pages=30, progress=0.1, font_size=12,
                         zoom_mode="pagina", zoom=1, two_pages=False)
    estado = sync.export_state(b)
    a.save_reading_state(livro_a.id, page=20, position=None, pages=30, progress=0.7, font_size=12,
                         zoom_mode="pagina", zoom=1, two_pages=False)
    estado["livros"][livro_b.fingerprint]["progress_updated_at"] = "2000-01-01T00:00:00"
    assert sync.merge_state(a, estado).progress == 0
    assert a.get(livro_a.id).page == 20
    nuvem.mkdir()


def test_backup_e_restauracao(amostras, tmp_path):
    lib = Library(tmp_path / "dados")
    livro = lib.import_file(amostras / "livro.epub")
    lib.add_highlight(livro.id, 1, "0:0.5", "amarelo", "Capítulo")
    zip_path = sync.create_backup(lib, tmp_path / "backup.zip")
    info = sync.validate_backup(zip_path)
    assert info["livros"] == 1 and info["app"] == "Leitor Universal"

    lib.remove(livro.id)
    lib.close()
    sync.restore_backup(zip_path, tmp_path / "dados")
    restaurada = Library(tmp_path / "dados")
    assert [b.title for b in restaurada.all_books()] == ["EPUB de Teste"]
    assert len(restaurada.all_highlights()) == 1
    assert list((tmp_path / "dados").glob("biblioteca-antes-da-restauracao-*.db"))

    (tmp_path / "falso.zip").write_bytes(b"nada")
    with pytest.raises(ValueError):
        sync.validate_backup(tmp_path / "falso.zip")


def test_instancia_unica_repassa_arquivos(qapp):
    """Uma segunda abertura (outro processo) entrega os arquivos à janela já aberta."""
    import subprocess
    import sys
    import time
    from PySide6.QtCore import QCoreApplication, QEventLoop
    from leitor_universal.single_instance import InstanceServer, send_to_running

    nome = "LeitorUniversal-teste-instancia"
    recebidos = []
    servidor = InstanceServer(nome)
    servidor.files_received.connect(recebidos.extend)
    raiz = str(Path(__file__).resolve().parents[1])
    segunda = subprocess.Popen([sys.executable, "-c", (
        f"import sys; sys.path.insert(0, {raiz!r});"
        "from PySide6.QtCore import QCoreApplication; app = QCoreApplication([]);"
        "from leitor_universal.single_instance import send_to_running;"
        f"sys.exit(0 if send_to_running([r'C:\\Livros\\Duna.epub'], {nome!r}) else 1)")])
    limite = time.monotonic() + 15
    while not recebidos and time.monotonic() < limite:
        QCoreApplication.processEvents(QEventLoop.AllEvents, 50)
    assert segunda.wait(10) == 0
    assert recebidos == [r"C:\Livros\Duna.epub"]
    servidor.server.close()
    assert not send_to_running(["x"], "LeitorUniversal-nao-existe")


def test_frases_para_leitura_em_voz_alta():
    partes = split_sentences("Primeira frase. Segunda com hífen-\nizada! " + "palavra " * 120)
    assert partes[0] == "Primeira frase." and partes[1] == "Segunda com hífenizada!"
    assert all(len(p) <= 400 for p in partes)


def test_narrador_fala_os_trechos_em_sequencia(qapp):
    """Usa o motor "mock" do Qt: percorre a fila sem emitir som."""
    import time
    from PySide6.QtCore import QCoreApplication, QEventLoop
    from leitor_universal.speech import Narrator

    narrador = Narrator(engines=("mock",))
    if not narrador.available:
        pytest.skip("motor de voz de teste indisponível")
    fim = []
    narrador.finished.connect(lambda: fim.append(True))
    assert narrador.speak("Primeira frase. Segunda frase. Terceira.")
    limite = time.monotonic() + 20
    while not fim and time.monotonic() < limite:
        QCoreApplication.processEvents(QEventLoop.AllEvents, 50)
    assert fim and not narrador.speaking


def test_textos_de_servicos_online_sem_rede():
    texto = "\n= Português =\n\n== Substantivo ==\n\ncasa, feminino\n\nmoradia\n\n= Galego =\n\noutra"
    limpo = online._clean_wiktionary(texto)
    assert "moradia" in limpo and "Galego" not in limpo
    assert online._looks_portuguese("A especiaria deve fluir.")
    assert not online._looks_portuguese("The spice must flow.")


def _janela(amostras, tmp_path, nome):
    from leitor_universal.app import MainWindow
    lib = Library(tmp_path / "dados")
    janela = MainWindow(lib)
    janela.resize(1200, 800)
    janela.show()
    janela.open_book(lib.import_file(amostras / nome).id)
    return lib, janela, janela.reader


def test_rolagem_continua_e_posicao(amostras, tmp_path, qapp):
    lib, janela, leitor = _janela(amostras, tmp_path, "teste.pdf")
    leitor.act_continuous.setChecked(True)
    leitor._toggle_continuous()
    assert leitor.scroll.widget() is leitor.cont_widget and len(leitor._slots) == 30
    leitor.goto(17)
    assert leitor.page_index == 17 and 17 in leitor._rendered
    assert len(leitor._rendered) < 10  # só as páginas próximas ficam desenhadas
    janela.show_library()
    livro = lib.all_books()[0]
    assert livro.continuous and livro.page == 17
    janela.open_book(livro.id)
    assert janela.reader.continuous and janela.reader.page_index == 17


@pytest.mark.parametrize("nome", ["teste.pdf", "livro.epub"])
def test_selecao_grifo_e_copia(amostras, tmp_path, qapp, nome):
    from PySide6.QtWidgets import QApplication
    lib, janela, leitor = _janela(amostras, tmp_path, nome)
    palavras = leitor._page_words(leitor.page_index)
    inicio, fim = palavras[2], palavras[8]
    leitor._update_selection((leitor.page_index, inicio[0] + 1, inicio[1] + 1),
                             (leitor.page_index, fim[2] - 1, fim[3] - 1))
    esperado = " ".join(w[4] for w in palavras[2:9])
    assert leitor.selected_text().replace("\n", " ") == esperado
    leitor.copy_selection()
    assert QApplication.clipboard().text() == leitor.selected_text()

    leitor.highlight_selection("verde")
    [grifo] = lib.highlights(lib.all_books()[0].id)
    assert grifo.color == "verde" and leitor._highlights_on(leitor.page_index)
    hit = (leitor.page_index, (inicio[0] + inicio[2]) / 2, (inicio[1] + inicio[3]) / 2)
    assert leitor._highlight_at(hit).id == grifo.id
    if nome == "livro.epub":  # o grifo sobrevive à mudança de fonte (texto reencontrado)
        leitor._change_font(+4)
        pagina = leitor._highlight_page(grifo)
        assert leitor._highlights_on(pagina)


def test_clique_na_pagina_pela_janela(amostras, tmp_path, qapp):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    lib, janela, leitor = _janela(amostras, tmp_path, "teste.pdf")
    vp = leitor.scroll.viewport()

    def clicar(x_frac):
        glob = vp.mapToGlobal(QPointF(vp.width() * x_frac, vp.height() / 2))
        local = QPointF(janela.mapFromGlobal(glob.toPoint()))
        for tipo, botoes in ((QEvent.MouseButtonPress, Qt.LeftButton), (QEvent.MouseButtonRelease, Qt.NoButton)):
            QApplication.sendEvent(janela.windowHandle(),
                                   QMouseEvent(tipo, local, glob, Qt.LeftButton, botoes, Qt.NoModifier))
        QApplication.processEvents()

    clicar(0.9)
    assert leitor.page_index == 1
    clicar(0.1)
    assert leitor.page_index == 0
