"""
Wrapper de execução na raiz do projeto que delega para `monitoramento_de_pasta/main.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent / "monitoramento_de_pasta"
if str(PKG_DIR) not in sys.path:
    sys.path.insert(0, str(PKG_DIR))

from main import main

if __name__ == "__main__":
    sys.exit(main())
