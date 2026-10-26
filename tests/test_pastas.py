import shutil
import sqlite3
from pathlib import Path

from leitor_universal.documents import DEFAULT_FORMAT_GROUPS, extensions_for
from leitor_universal.library import Library
from leitor_universal.scanner import scan
from leitor_universal.settings_dialog import Preferences

TODOS = extensions_for(DEFAULT_FORMAT_GROUPS)


def _pasta_com_livros(amostras: Path, destino: Path) -> Path:
    (destino / "sub").mkdir(parents=True)
    for nome in ["teste.pdf", "livro.epub", "romance.txt"]:
        shutil.copy(amostras / nome, destino / nome)
    shutil.copy(amostras / "quadrinho.cbz", destino / "sub" / "quadrinho.cbz")
    shutil.copy(amostras / "imagem.png", destino / "imagem.png")  # imagens soltas não entram
    (destino / "~$temporario.docx").write_bytes(b"lixo do Office")
    return destino


def test_varredura_monta_biblioteca_e_e_incremental(amostras, tmp_path):
    pasta = _pasta_com_livros(amostras, tmp_path / "livros")
    lib = Library(tmp_path / "dados")
    lib.add_folder(pasta)

    primeira = scan(lib, TODOS, recursive=True)
    assert primeira.added == 4 and not primeira.errors
    assert {b.kind for b in lib.all_books()} == {"PDF", "EPUB", "Texto", "Quadrinhos"}

    segunda = scan(lib, TODOS, recursive=True)
    assert (segunda.added, segunda.updated, segunda.missing) == (0, 0, 0)


def test_sem_subpastas_e_filtro_de_formatos(amostras, tmp_path):
    pasta = _pasta_com_livros(amostras, tmp_path / "livros")
    lib = Library(tmp_path / "dados")
    lib.add_folder(pasta)
    resultado = scan(lib, extensions_for(["pdf", "quadrinhos"]), recursive=False)
    assert resultado.added == 1
    assert [b.kind for b in lib.all_books()] == ["PDF"]


def test_arquivo_removido_fica_oculto_e_volta_com_progresso(amostras, tmp_path):
    pasta = _pasta_com_livros(amostras, tmp_path / "livros")
    lib = Library(tmp_path / "dados")
    lib.add_folder(pasta)
    scan(lib, TODOS, recursive=True)
    pdf = next(b for b in lib.all_books() if b.kind == "PDF")
    lib.save_reading_state(pdf.id, page=12, position=None, pages=30, progress=0.4, font_size=12,
                           zoom_mode="pagina", zoom=1, two_pages=False)

    guardado = tmp_path / "fora.pdf"
    shutil.move(pasta / "teste.pdf", guardado)
    assert scan(lib, TODOS, recursive=True).missing == 1
    assert pdf.id not in {b.id for b in lib.all_books()}

    shutil.move(guardado, pasta / "renomeado.pdf")
    scan(lib, TODOS, recursive=True)
    volta = lib.get(pdf.id)
    assert not volta.missing and volta.page == 12 and volta.path.endswith("renomeado.pdf")


def test_pasta_desconectada_nao_esconde_livros(amostras, tmp_path):
    pasta = _pasta_com_livros(amostras, tmp_path / "livros")
    lib = Library(tmp_path / "dados")
    lib.add_folder(pasta)
    scan(lib, TODOS, recursive=True)
    pasta.rename(tmp_path / "desconectada")  # simula pen drive removido
    assert scan(lib, TODOS, recursive=True).missing == 0
    assert len(lib.all_books()) == 4


def test_remover_pasta_tira_somente_os_livros_dela(amostras, tmp_path):
    a = _pasta_com_livros(amostras, tmp_path / "a")
    b = tmp_path / "b"
    b.mkdir()
    shutil.copy(amostras / "notas.md", b / "notas.md")
    lib = Library(tmp_path / "dados")
    lib.add_folder(a)
    lib.add_folder(b)
    scan(lib, TODOS, recursive=True)
    assert lib.remove_folder(lib.folders()[0]) == 4
    assert [x.kind for x in lib.all_books()] == ["Markdown"]
    assert (a / "teste.pdf").exists()  # arquivos nunca são apagados


def test_migra_banco_da_versao_1_0_0(tmp_path):
    dados = tmp_path / "dados"
    dados.mkdir()
    conn = sqlite3.connect(dados / "biblioteca.db")
    conn.executescript("""
        CREATE TABLE books (id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, path TEXT NOT NULL,
            title TEXT NOT NULL, author TEXT DEFAULT '', kind TEXT DEFAULT '', pages INTEGER DEFAULT 0,
            page INTEGER DEFAULT 0, position TEXT, progress REAL DEFAULT 0, font_size REAL DEFAULT 12,
            zoom_mode TEXT DEFAULT '', zoom REAL DEFAULT 1, two_pages INTEGER DEFAULT 0,
            favorite INTEGER DEFAULT 0, finished INTEGER DEFAULT 0, reading_seconds INTEGER DEFAULT 0,
            added_at TEXT, last_opened TEXT, cover BLOB);
        INSERT INTO books (fingerprint, path, title, page) VALUES ('abc', 'C:/x.pdf', 'Antigo', 7);
    """)
    conn.commit()
    conn.close()
    livro = Library(dados).all_books()[0]
    assert livro.title == "Antigo" and livro.page == 7 and livro.missing is False


def test_preferencias_persistem(tmp_path):
    lib = Library(tmp_path / "dados")
    padrao = Preferences.load(lib)
    assert padrao.recursive and padrao.watch and padrao.formats == DEFAULT_FORMAT_GROUPS
    Preferences(recursive=False, watch=False, formats=("pdf",), theme="escuro",
                open_last=True, auto_update=False).save(lib)
    lidas = Preferences.load(lib)
    assert (lidas.recursive, lidas.watch, lidas.formats, lidas.theme, lidas.open_last, lidas.auto_update) == \
        (False, False, ("pdf",), "escuro", True, False)
