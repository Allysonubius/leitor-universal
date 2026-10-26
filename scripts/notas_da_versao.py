"""Extrai do CHANGELOG.md a seção de uma versão (usada como notas da release).

Uso: python scripts/notas_da_versao.py 1.2.0 [saida.md]
"""
import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


def notes_for(version: str, text: str) -> str:
    match = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    return match.group(1).strip() if match else ""


if __name__ == "__main__":
    notes = notes_for(sys.argv[1], CHANGELOG.read_text(encoding="utf-8"))
    if not notes:
        sys.exit(f"CHANGELOG.md não tem a seção [{sys.argv[1]}].")
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(notes + "\n", encoding="utf-8")
    else:
        print(notes)
