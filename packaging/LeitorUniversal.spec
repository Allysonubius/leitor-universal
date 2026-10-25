# Especificação do PyInstaller. Uso (na raiz do projeto):
#   pyinstaller packaging/LeitorUniversal.spec --noconfirm
import os
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "run.pyw")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "leitor_universal" / "icone.png"), "leitor_universal")],
    hiddenimports=["mammoth", "markdown", "markdown.extensions.extra", "markdown.extensions.toc",
                   "markdown.extensions.sane_lists", "striprtf.striprtf", "rarfile"],
    excludes=["tkinter", "pytest", "pymupdf.layout", "pymupdf_layout", "pymupdf4llm", "onnxruntime",
              "networkx", "numpy", "psutil", "tabulate", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LeitorUniversal",
    icon=str(ROOT / "packaging" / "icone.ico"),
    console=bool(os.environ.get("LEITOR_CONSOLE")),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="LeitorUniversal", upx=False)
