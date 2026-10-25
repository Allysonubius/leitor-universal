"""Gera arquivos de exemplo em vários formatos para testes.

Uso direto: python tests/amostras.py <pasta>
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pymupdf

PARA = "Era uma vez um leitor que gostava de livros em todos os formatos possíveis. " * 12


def gerar(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)

    pdf = pymupdf.open()
    for i in range(30):
        page = pdf.new_page()
        extra = " agulha " if i == 17 else ""
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 790),
                            f"Capítulo {i // 5 + 1} - página {i + 1}\n\n{PARA}{extra}", fontsize=11)
    pdf.set_toc([[1, f"Capítulo {c + 1}", c * 5 + 1] for c in range(6)])
    pdf.set_metadata({"title": "Livro de Teste PDF", "author": "Autora Exemplo"})
    pdf.save(out / "teste.pdf")

    txt = "\n\n".join(f"CAPÍTULO {i}\n\n" + PARA * 3 for i in range(1, 8))
    (out / "romance.txt").write_bytes(txt.encode("cp1252"))
    (out / "notas.md").write_text(
        "# Título MD\n\n" + "\n\n".join(f"## Seção {i}\n\n{PARA}\n\n- item a\n- item b" for i in range(6)),
        encoding="utf-8")
    (out / "doc.rtf").write_text(
        r"{\rtf1\ansi Ol\'e1 mundo RTF.\par Segunda linha com acentua\'e7\'e3o.\par}", encoding="ascii")
    (out / "pagina.html").write_text(
        f"<html><head><meta charset='utf-8'><title>HTML Teste</title></head><body><h1>Olá</h1><p>{PARA}</p></body></html>",
        encoding="utf-8")

    _epub(out / "livro.epub")
    _docx(out / "documento.docx")

    with zipfile.ZipFile(out / "quadrinho.cbz", "w") as cbz:
        for i in range(1, 4):
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 300, 450), 0)
            pix.set_rect(pix.irect, (40 * i, 100, 200))
            cbz.writestr(f"pag{i}.png", pix.tobytes("png"))

    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), 0)
    pix.set_rect(pix.irect, (10, 200, 90))
    pix.save(out / "imagem.png")
    return sorted(out.iterdir())


def _epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as ep:
        ep.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        ep.writestr("META-INF/container.xml",
                    '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                    '</rootfiles></container>')
        items = "".join(f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>' for i in range(5))
        spine = "".join(f'<itemref idref="c{i}"/>' for i in range(5))
        ep.writestr("OEBPS/content.opf",
                    '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">'
                    '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>EPUB de Teste</dc:title>'
                    '<dc:creator>Fulano de Tal</dc:creator><dc:identifier id="id">x</dc:identifier>'
                    f'<dc:language>pt</dc:language></metadata><manifest>{items}'
                    '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>'
                    f'<spine toc="ncx">{spine}</spine></package>')
        nav = "".join(f'<navPoint id="n{i}" playOrder="{i + 1}"><navLabel><text>Capítulo {i + 1}</text></navLabel>'
                      f'<content src="c{i}.xhtml"/></navPoint>' for i in range(5))
        ep.writestr("OEBPS/toc.ncx",
                    '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
                    f'<head/><docTitle><text>EPUB</text></docTitle><navMap>{nav}</navMap></ncx>')
        for i in range(5):
            ep.writestr(f"OEBPS/c{i}.xhtml",
                        '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml">'
                        f'<head><title>c</title></head><body><h1>Capítulo {i + 1}</h1>'
                        + f"<p>{PARA}</p>" * 6 + "</body></html>")


def _docx(path: Path) -> None:
    w = "http://schemas.openxmlformats.org"
    with zipfile.ZipFile(path, "w") as dx:
        dx.writestr("[Content_Types].xml",
                    f'<?xml version="1.0"?><Types xmlns="{w}/package/2006/content-types">'
                    f'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                    '<Default Extension="xml" ContentType="application/xml"/>'
                    '<Override PartName="/word/document.xml" '
                    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        dx.writestr("_rels/.rels",
                    f'<?xml version="1.0"?><Relationships xmlns="{w}/package/2006/relationships">'
                    f'<Relationship Id="r1" Type="{w}/officeDocument/2006/relationships/officeDocument" '
                    'Target="word/document.xml"/></Relationships>')
        body = "".join(f"<w:p><w:r><w:t>Parágrafo {i} do Word. {PARA}</w:t></w:r></w:p>" for i in range(10))
        dx.writestr("word/document.xml",
                    f'<?xml version="1.0"?><w:document xmlns:w="{w}/wordprocessingml/2006/main">'
                    f"<w:body>{body}</w:body></w:document>")


if __name__ == "__main__":
    print("\n".join(p.name for p in gerar(Path(sys.argv[1]))))
