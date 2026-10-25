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
