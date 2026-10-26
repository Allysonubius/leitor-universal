"""Serviços online opcionais: dicionário (Wikcionário), tradução (MyMemory) e
dados de livros (Open Library). Tudo é acionado pelo usuário e roda em threads."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

from . import __version__

USER_AGENT = f"LeitorUniversal/{__version__} (+https://github.com/Allysonubius/leitor-universal)"


class OnlineError(Exception):
    pass


def _get(url: str, timeout: float = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as exc:
        raise OnlineError(f"Sem resposta do serviço ({exc}). Verifique a internet.") from exc


def _json(url: str):
    return json.loads(_get(url).decode("utf-8", "replace"))


# ------------------------------------------------------------- dicionário
def define(word: str) -> str:
    """Definição em português pelo Wikcionário; devolve texto simples."""
    word = word.strip().strip(".,;:!?\"'“”()[]«»").lower()
    if not word:
        raise OnlineError("Selecione uma palavra.")
    params = {"action": "query", "prop": "extracts", "explaintext": 1, "format": "json",
              "redirects": 1, "titles": word}
    data = _json("https://pt.wiktionary.org/w/api.php?" + urllib.parse.urlencode(params))
    pages = data.get("query", {}).get("pages", {})
    extract = next((p.get("extract") for p in pages.values() if p.get("extract")), "")
    if not extract:
        raise OnlineError(f"“{word}” não foi encontrada no Wikcionário.")
    return _clean_wiktionary(extract)


def _clean_wiktionary(text: str) -> str:
    # Mantém a seção em português, quando houver, e remove excesso de linhas vazias.
    sections = re.split(r"\n= (.+?) =\n", "\n" + text)
    if len(sections) > 1:
        pairs = dict(zip(sections[1::2], sections[2::2]))
        text = pairs.get("Português", next(iter(pairs.values())))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    text = re.sub(r"^=+ *(.+?) *=+$", r"\1:", text, flags=re.M)
    return text[:3000]


# -------------------------------------------------------------- tradução
def translate(text: str, target: str = "pt-BR") -> str:
    text = " ".join(text.split())[:480]  # limite da API gratuita
    if not text:
        raise OnlineError("Selecione um trecho.")
    source = "en" if target.startswith("pt") else "pt-BR"
    if target.startswith("pt") and _looks_portuguese(text):
        target, source = "en", "pt-BR"
    data = _json("https://api.mymemory.translated.net/get?"
                 + urllib.parse.urlencode({"q": text, "langpair": f"{source}|{target}"}))
    result = (data.get("responseData") or {}).get("translatedText") or ""
    if data.get("responseStatus") not in (200, "200") or not result:
        raise OnlineError(data.get("responseDetails") or "Não foi possível traduzir.")
    return result


def _looks_portuguese(text: str) -> bool:
    words = re.findall(r"[a-zà-ú]+", text.lower())
    common = {"de", "que", "não", "uma", "para", "com", "os", "as", "do", "da", "em", "um", "é", "ao", "se",
              "o", "e", "no", "na", "mas", "por", "mais", "como", "deve", "seu", "sua", "ele", "ela", "foi"}
    english = {"the", "of", "and", "to", "is", "in", "it", "you", "that", "was", "for", "with", "be"}
    if not words:
        return False
    pt = sum(w in common for w in words) + 2 * bool(re.search(r"[ãõçâêôáéíóú]", text))
    return pt > sum(w in english for w in words)


# ------------------------------------------------------------ Open Library
@dataclass
class BookMatch:
    title: str
    author: str
    year: int | None
    cover_id: int | None
    work_key: str

    @property
    def cover_url(self) -> str | None:
        return f"https://covers.openlibrary.org/b/id/{self.cover_id}-L.jpg" if self.cover_id else None

    @property
    def thumb_url(self) -> str | None:
        return f"https://covers.openlibrary.org/b/id/{self.cover_id}-M.jpg" if self.cover_id else None


def search_books(title: str, author: str = "", limit: int = 8) -> list[BookMatch]:
    params = {"title": title, "limit": limit,
              "fields": "title,author_name,first_publish_year,cover_i,key"}
    if author:
        params["author"] = author
    data = _json("https://openlibrary.org/search.json?" + urllib.parse.urlencode(params))
    if not data.get("docs") and author:
        return search_books(title, "", limit)
    return [BookMatch(d.get("title", ""), ", ".join(d.get("author_name", [])[:2]), d.get("first_publish_year"),
                      d.get("cover_i"), d.get("key", "")) for d in data.get("docs", [])]


def book_description(work_key: str) -> str:
    if not work_key:
        return ""
    data = _json(f"https://openlibrary.org{work_key}.json")
    desc = data.get("description", "")
    if isinstance(desc, dict):
        desc = desc.get("value", "")
    return re.sub(r"\(\[source\].*?\)|-{3,}.*", "", desc, flags=re.S).strip()


def download(url: str) -> bytes:
    return _get(url, timeout=30)


class Task(QThread):
    """Executa uma função de rede fora da interface: done(resultado, erro)."""
    done = Signal(object, str)

    def __init__(self, fn, *args, parent=None):
        super().__init__(parent)
        self.fn, self.args = fn, args

    def run(self) -> None:
        try:
            self.done.emit(self.fn(*self.args), "")
        except Exception as exc:
            self.done.emit(None, str(exc))
