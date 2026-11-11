"""
Gerenciamento de inicialização automática do aplicativo no logon do usuário atual
no Windows (sem necessidade de privilégios administrativos).
Utiliza a chave HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Tuple

from config import APP_SLUG, BASE_DIR, DATA_DIR

logger = logging.getLogger(__name__)

RUN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_VALUE_NAME = APP_SLUG


class WindowsStartupManager:
    """
    Habilita, desabilita e consulta a inicialização automática do aplicativo
    junto com o Windows no escopo do usuário atual (HKCU).
    """

    @staticmethod
    def get_startup_command() -> str:
        if getattr(sys, "frozen", False):
            exe_path = Path(sys.executable).resolve()
            return f'"{exe_path}" --startup'

        candidates = [
            DATA_DIR / "dist" / f"{APP_SLUG}.exe",
            DATA_DIR / f"{APP_SLUG}.exe",
            BASE_DIR / "dist" / f"{APP_SLUG}.exe",
            BASE_DIR / f"{APP_SLUG}.exe",
            BASE_DIR.parent / f"{APP_SLUG}.exe",
        ]
        for cand in candidates:
            if cand.exists():
                return f'"{cand.resolve()}" --startup'

        py_exe = Path(sys.executable).resolve()
        pythonw = py_exe.with_name("pythonw.exe")
        runner = pythonw if pythonw.exists() else py_exe
        main_script = (BASE_DIR / "main.py").resolve()
        return f'"{runner}" "{main_script}" --startup'

    @classmethod
    def is_enabled(cls) -> bool:
        if os.name != "nt":
            return False
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                RUN_REG_PATH,
                0,
                winreg.KEY_READ,
            ) as key:
                val, _ = winreg.QueryValueEx(key, REG_VALUE_NAME)
                return bool(val)
        except FileNotFoundError:
            return False
        except Exception as exc:
            logger.debug("Erro ao consultar registro de inicialização: %s", exc)
            return False

    @classmethod
    def set_enabled(cls, enabled: bool) -> Tuple[bool, str]:
        if os.name != "nt":
            return False, "Inicialização automática suportada apenas no Windows."
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                RUN_REG_PATH,
                0,
                winreg.KEY_SET_VALUE | winreg.KEY_READ,
            ) as key:
                if enabled:
                    cmd = cls.get_startup_command()
                    winreg.SetValueEx(
                        key, REG_VALUE_NAME, 0, winreg.REG_SZ, cmd
                    )
                    logger.info(
                        "Inicialização automática habilitada no Windows: %s",
                        cmd,
                    )
                    return True, f"Inicialização automática habilitada ({cmd})."
                else:
                    try:
                        winreg.DeleteValue(key, REG_VALUE_NAME)
                        logger.info(
                            "Inicialização automática removida do Registro do Windows."
                        )
                    except FileNotFoundError:
                        pass
                    return True, "Inicialização automática desabilitada."
        except Exception as exc:
            logger.error(
                "Falha ao configurar inicialização automática no Windows: %s",
                exc,
            )
            return False, f"Erro ao atualizar inicialização automática: {exc}"
