"""Abertura universal de documentos sobre o motor MuPDF (PyMuPDF).

Formatos nativos são abertos diretamente; os demais são convertidos para HTML
ou PDF em memória (ou via LibreOffice, se instalado) antes da abertura.
"""
from __future__ import annotations

import hashlib
import html
import io
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pymupdf

pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".jxr",
              ".pnm", ".pgm", ".ppm", ".pbm"}

NATIVE_FORMATS = {
    ".pdf": "PDF", ".xps": "XPS", ".oxps": "XPS", ".epub": "EPUB",
    ".mobi": "MOBI", ".prc": "MOBI", ".azw": "Kindle", ".azw3": "Kindle",
    ".fb2": "FictionBook", ".fbz": "FictionBook", ".cbz": "Quadrinhos",
    ".svg": "SVG", ".html": "HTML", ".htm": "HTML", ".xhtml": "XHTML",
    **{ext: "Imagem" for ext in IMAGE_EXTS},
}
CONVERTED_FORMATS = {
    ".txt": "Texto", ".text": "Texto", ".md": "Markdown", ".markdown": "Markdown",
    ".rtf": "RTF", ".docx": "Word", ".cbr": "Quadrinhos", ".zip": "Quadrinhos",
}
OFFICE_FORMATS = {
    ".doc": "Word", ".odt": "OpenDocument", ".ott": "OpenDocument", ".wps": "Works",
    ".pptx": "PowerPoint", ".ppt": "PowerPoint", ".odp": "OpenDocument",
    ".xlsx": "Excel", ".xls": "Excel", ".ods": "OpenDocument",
}
ALL_FORMATS = {**NATIVE_FORMATS, **CONVERTED_FORMATS, **OFFICE_FORMATS}
# Formatos considerados "livros" ao varrer pastas (imagens soltas ficam de fora).
BOOK_EXTS = set(ALL_FORMATS) - IMAGE_EXTS - {".svg", ".zip", ".html", ".htm"}

# Grupos exibidos nas Configurações para escolher o que entra na biblioteca.
FORMAT_GROUPS: dict[str, tuple[str, set[str]]] = {
    "pdf": ("PDF e XPS", {".pdf", ".xps", ".oxps"}),
    "ebook": ("E-books (EPUB, MOBI, AZW, FB2)", {".epub", ".mobi", ".prc", ".azw", ".azw3", ".fb2", ".fbz"}),
    "quadrinhos": ("Quadrinhos (CBZ, CBR)", {".cbz", ".cbr"}),
    "texto": ("Textos (TXT, Markdown, RTF)", {".txt", ".text", ".md", ".markdown", ".rtf"}),
    "office": ("Documentos (DOCX, DOC, ODT, PPTX…)", {".docx"} | set(OFFICE_FORMATS)),
}
DEFAULT_FORMAT_GROUPS = tuple(FORMAT_GROUPS)


def extensions_for(groups) -> set[str]:
    return set().union(*(FORMAT_GROUPS[g][1] for g in groups if g in FORMAT_GROUPS))

READING_CSS = """
body { font-family: serif; line-height: 1.5; text-align: justify; margin: 0; }
p { margin: 0 0 0.7em 0; text-indent: 1.2em; }
h1, h2, h3 { text-align: left; line-height: 1.25; margin: 1em 0 0.6em 0; }
pre, code { font-family: monospace; white-space: pre-wrap; text-align: left; }
img { max-width: 100%; }
blockquote { margin: 0.5em 1.5em; font-style: italic; }
table { border-collapse: collapse; }
td, th { border: 1px solid #888; padding: 2px 4px; }
"""

CHAPTER_RE = re.compile(
    r"^\s*(cap[ií]tulo|chapter|parte|part|livro|book|pr[oó]logo|ep[ií]logo|prologue|epilogue)\b.{0,80}$",
    re.IGNORECASE,
)


class UnsupportedFormat(Exception):
    pass


@dataclass
class LoadedDocument:
    doc: pymupdf.Document
    path: Path
    kind: str
    reflowable: bool
    image_based: bool
    title: str
    author: str


def fingerprint(path: str | Path) -> str:
    """Identidade do arquivo resistente a renomear/mover: tamanho + início + fim."""
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.sha1(str(size).encode())
    with p.open("rb") as f:
        h.update(f.read(65536))
        if size > 131072:
            f.seek(-65536, io.SEEK_END)
            h.update(f.read(65536))
    return h.hexdigest()


def is_supported(path: str | Path) -> bool:
    return Path(path).suffix.lower() in ALL_FORMATS


def format_label(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    return ALL_FORMATS.get(ext, ext.lstrip(".").upper() or "Arquivo")


def find_libreoffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return found
    for base in (r"C:\Program Files\LibreOffice\program", r"C:\Program Files (x86)\LibreOffice\program"):
        candidate = Path(base) / "soffice.exe"
        if candidate.exists():
            return str(candidate)
    return None


def open_document(path: str | Path, cache_dir: Path) -> LoadedDocument:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {p}")
    ext = p.suffix.lower()
    image_based = ext in IMAGE_EXTS or ext in {".cbz", ".cbr", ".zip", ".svg"}

    if ext in NATIVE_FORMATS:
        doc = pymupdf.open(p)
    elif ext in {".txt", ".text"}:
        doc = _html_document(_text_to_html(_read_text(p)), p.stem)
    elif ext in {".md", ".markdown"}:
        import markdown
        body = markdown.markdown(_read_text(p), extensions=["extra", "sane_lists", "toc"])
        doc = _html_document(body, p.stem)
    elif ext == ".rtf":
        from striprtf.striprtf import rtf_to_text
        doc = _html_document(_text_to_html(rtf_to_text(_read_text(p))), p.stem)
    elif ext == ".docx":
        import mammoth
        with p.open("rb") as f:
            body = mammoth.convert_to_html(f).value
        doc = _html_document(body, p.stem)
    elif ext in {".cbr", ".zip"}:
        doc = _open_archive_comic(p)
    elif ext in OFFICE_FORMATS:
        doc = pymupdf.open(_convert_with_libreoffice(p, cache_dir))
    elif _looks_like_text(p):
        doc = _html_document(_text_to_html(_read_text(p)), p.stem)
    else:
        try:
            doc = pymupdf.open(p)
        except Exception as exc:
            raise UnsupportedFormat(f"Formato não suportado: {p.suffix or p.name}") from exc

    if doc.needs_pass:
        raise UnsupportedFormat("O documento é protegido por senha.")
    if doc.page_count == 0:
        raise UnsupportedFormat("O documento não possui páginas legíveis.")

    meta = doc.metadata or {}
    title = (meta.get("title") or "").strip() or p.stem
    author = (meta.get("author") or "").strip()
    return LoadedDocument(
        doc=doc, path=p, kind=format_label(p), reflowable=doc.is_reflowable,
        image_based=image_based, title=title, author=author,
    )


def render_cover(doc: pymupdf.Document, width: int = 240) -> bytes:
    page = doc[0]
    zoom = width / max(page.rect.width, 1)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    return pix.tobytes("png")


# --------------------------------------------------------------------------- #
# Conversores
# --------------------------------------------------------------------------- #

def _html_document(body: str, title: str) -> pymupdf.Document:
    page = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title><style>{READING_CSS}</style></head>"
        f"<body>{body}</body></html>"
    )
    return pymupdf.open(stream=page.encode("utf-8"), filetype="html")


def _read_text(p: Path) -> str:
    raw = p.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _looks_like_text(p: Path) -> bool:
    try:
        chunk = p.open("rb").read(8192)
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    try:
        chunk.decode("utf-8")
        return True
    except UnicodeDecodeError:
        printable = sum(32 <= b < 127 or b in (9, 10, 13) or b >= 160 for b in chunk)
        return printable / max(len(chunk), 1) > 0.9


def _text_to_html(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    blank = sum(1 for line in lines if not line.strip())
    # Textos sem linhas em branco tratam cada linha como parágrafo.
    if blank < len(lines) / 10:
        blocks = [line for line in lines if line.strip()]
    else:
        blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    out = []
    for block in blocks:
        stripped = block.strip()
        if "\n" not in stripped and CHAPTER_RE.match(stripped):
            out.append(f"<h2>{html.escape(stripped)}</h2>")
        else:
            out.append("<p>" + "<br/>".join(html.escape(l.strip()) for l in stripped.split("\n")) + "</p>")
    return "\n".join(out)


def _natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _images_to_pdf(images: list[tuple[str, bytes]]) -> pymupdf.Document:
    out = pymupdf.open()
    for name, data in sorted(images, key=lambda item: _natural_key(item[0])):
        try:
            img = pymupdf.open(stream=data, filetype=Path(name).suffix.lstrip(".") or "png")
            out.insert_pdf(pymupdf.open("pdf", img.convert_to_pdf()))
        except Exception:
            continue
    return out


def _open_archive_comic(p: Path) -> pymupdf.Document:
    if zipfile.is_zipfile(p):  # muitos .cbr são, na verdade, ZIP
        return pymupdf.open(p, filetype="cbz")
    try:
        import rarfile
        with rarfile.RarFile(p) as rf:
            images = [(n, rf.read(n)) for n in rf.namelist() if Path(n).suffix.lower() in IMAGE_EXTS]
    except Exception as exc:
        raise UnsupportedFormat(
            "Não foi possível abrir o arquivo RAR. Instale o WinRAR (unrar) ou o 7-Zip e tente novamente."
        ) from exc
    if not images:
        raise UnsupportedFormat("O arquivo não contém imagens.")
    return _images_to_pdf(images)


def _convert_with_libreoffice(p: Path, cache_dir: Path) -> Path:
    target = cache_dir / f"{fingerprint(p)}.pdf"
    if target.exists():
        return target
    soffice = find_libreoffice()
    if not soffice:
        raise UnsupportedFormat(
            f"Arquivos {p.suffix} exigem o LibreOffice instalado (https://www.libreoffice.org)."
        )
    work = cache_dir / "conversao"
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(work), str(p)],
        check=True, timeout=180, capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    produced = work / f"{p.stem}.pdf"
    if not produced.exists():
        raise UnsupportedFormat("O LibreOffice não conseguiu converter o arquivo.")
    produced.replace(target)
    return target
