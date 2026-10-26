"""Garante uma única janela: uma segunda abertura repassa os arquivos à primeira."""
from __future__ import annotations

import getpass
import hashlib
import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

TIMEOUT_MS = 1500


def server_name() -> str:
    user = hashlib.sha1(getpass.getuser().encode("utf-8", "replace")).hexdigest()[:12]
    return f"LeitorUniversal-{user}"


def send_to_running(paths: list[str], name: str | None = None) -> bool:
    """True se outra instância recebeu os arquivos (esta deve então encerrar)."""
    socket = QLocalSocket()
    socket.connectToServer(name or server_name())
    if not socket.waitForConnected(TIMEOUT_MS):
        return False
    socket.write(json.dumps({"paths": paths}).encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(TIMEOUT_MS)
    socket.disconnectFromServer()
    return True


class InstanceServer(QObject):
    """Recebe pedidos de outras aberturas do aplicativo."""

    files_received = Signal(list)

    def __init__(self, name: str | None = None, parent=None):
        super().__init__(parent)
        self.name = name or server_name()
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_connection)
        if not self.server.listen(self.name):
            # Sobra de uma execução que caiu: remove e tenta de novo.
            QLocalServer.removeServer(self.name)
            self.server.listen(self.name)

    def _on_connection(self) -> None:
        socket = self.server.nextPendingConnection()
        if socket is None:
            return
        buffer = bytearray()
        done = False

        def read():
            buffer.extend(bytes(socket.readAll()))

        def finished():
            nonlocal done
            if done:
                return
            done = True
            read()
            try:
                paths = json.loads(bytes(buffer).decode("utf-8")).get("paths", [])
            except (ValueError, AttributeError):
                paths = []
            self.files_received.emit([str(p) for p in paths])
            socket.deleteLater()

        socket.readyRead.connect(read)
        socket.disconnected.connect(finished)
        # O cliente pode ter enviado e desconectado antes de os sinais serem ligados.
        read()
        if socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            finished()
