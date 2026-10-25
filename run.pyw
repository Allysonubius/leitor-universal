"""Inicializador sem console (duplo clique ou "Abrir com")."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from leitor_universal.app import main  # noqa: E402

sys.exit(main())
