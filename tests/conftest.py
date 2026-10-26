import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from amostras import gerar  # noqa: E402


@pytest.fixture(scope="session")
def amostras(tmp_path_factory) -> Path:
    pasta = tmp_path_factory.mktemp("amostras")
    gerar(pasta)
    return pasta


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def fechar_janelas():
    """Fecha e destrói as janelas de cada teste; janelas vivas até o fim do processo
    fazem o Qt cair na finalização do Python (código de saída diferente de zero)."""
    yield
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
