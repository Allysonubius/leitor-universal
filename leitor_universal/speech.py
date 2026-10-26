"""Leitura em voz alta com as vozes instaladas no Windows (Qt TextToSpeech)."""
from __future__ import annotations

import logging
import re

from PySide6.QtCore import QLocale, QObject, Signal

log = logging.getLogger("leitor.voz")

try:
    from PySide6.QtTextToSpeech import QTextToSpeech, QVoice
except ImportError:  # módulo ausente: o recurso fica desativado
    QTextToSpeech = None
    QVoice = None


def split_sentences(text: str, max_len: int = 400) -> list[str]:
    """Divide em frases curtas: o motor responde melhor e dá para parar no meio da página."""
    text = re.sub(r"-\n(\w)", r"\1", text)  # junta palavras hifenizadas na quebra de linha
    text = " ".join(text.split())
    parts = re.split(r"(?<=[.!?…;:])\s+", text)
    chunks: list[str] = []
    for part in parts:
        while len(part) > max_len:
            cut = part.rfind(" ", 0, max_len)
            cut = cut if cut > 0 else max_len
            chunks.append(part[:cut])
            part = part[cut:].strip()
        if part.strip():
            chunks.append(part.strip())
    return chunks


class Narrator(QObject):
    """Fala uma lista de trechos em sequência e avisa quando acaba (para virar a página)."""

    finished = Signal()          # terminou todos os trechos entregues
    error = Signal(str)

    def __init__(self, parent=None, engines: tuple[str, ...] = ("winrt", "sapi", "")):
        super().__init__(parent)
        self._queue: list[str] = []
        self._active = False
        self._engines = engines
        self._engine = None
        self._tried = False

    @property
    def engine(self):
        """O motor é criado só no primeiro uso (abrir o app fica mais leve)."""
        if not self._tried:
            self._tried = True
            self._engine = self._create_engine()
        return self._engine

    def _create_engine(self):
        if QTextToSpeech is None:
            return None
        names = [n for n in self._engines if not n or n in QTextToSpeech.availableEngines()]
        for name in names:
            try:
                engine = QTextToSpeech(name, self) if name else QTextToSpeech(self)
            except Exception:
                continue
            if engine.state() != QTextToSpeech.State.Error:
                engine.stateChanged.connect(self._on_state)
                self._engine = engine
                self._pick_portuguese_voice()
                return engine
            engine.deleteLater()
        return None

    @property
    def available(self) -> bool:
        """Verificação barata, sem criar o motor."""
        if self._tried:
            return self._engine is not None
        return QTextToSpeech is not None and any(
            n in QTextToSpeech.availableEngines() for n in self._engines if n)

    def shutdown(self) -> None:
        """Libera o motor antes de o aplicativo encerrar."""
        self.stop()
        if self._engine is not None:
            self._engine.deleteLater()
            self._engine = None

    def voices(self) -> list[str]:
        return [v.name() for v in self.engine.availableVoices()] if self.engine else []

    def _pick_portuguese_voice(self) -> None:
        for locale in self.engine.availableLocales():
            if locale.language() == QLocale.Language.Portuguese:
                self.engine.setLocale(locale)
                break

    def configure(self, voice_name: str | None, rate: float) -> None:
        if not self.engine:
            return
        if voice_name:
            for voice in self.engine.availableVoices():
                if voice.name() == voice_name:
                    self.engine.setVoice(voice)
                    break
        self.engine.setRate(max(-1.0, min(rate, 1.0)))

    def speak(self, text: str) -> bool:
        if not self.engine:
            self.error.emit("Nenhuma voz disponível neste computador.")
            return False
        self._queue = split_sentences(text)
        self._active = True
        if not self._queue:
            self._active = False
            self.finished.emit()
            return True
        self._next()
        return True

    def stop(self) -> None:
        self._active = False
        self._queue = []
        if self._engine:
            self._engine.stop()

    @property
    def speaking(self) -> bool:
        return self._active

    def _next(self) -> None:
        if not self._queue:
            self._active = False
            self.finished.emit()
            return
        self.engine.say(self._queue.pop(0))

    def _on_state(self, state) -> None:
        if state == QTextToSpeech.State.Error:
            log.warning("Erro no motor de voz: %s", self.engine.errorString())
            self._active = False
            self.error.emit(self.engine.errorString() or "Falha no motor de voz.")
        elif state == QTextToSpeech.State.Ready and self._active:
            self._next()
