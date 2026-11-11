"""
Ponto de entrada principal do aplicativo Monitoramento de Pasta (MonitorPlus).
Inicializa banco SQLite, configurações, ícone, inicialização automática no Windows,
controlador de monitoramento híbrido e interface gráfica (Central de Pendências + Bandeja).
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from assets.icon_generator import ensure_icon_files
from config import (
    APP_NAME,
    APP_SLUG,
    ASSETS_DIR,
    DB_PATH,
    setup_logging,
)
from database.database import DatabaseManager
from monitor.network_scanner import HybridMonitorController, NetworkScanner
from notifications.windows_notifications import NotificationManager
from startup.windows_startup import WindowsStartupManager


def set_windows_app_id() -> None:
    """Define o AppUserModelID no Windows para integração de ícone na barra de tarefas e Toasts."""
    if os.name == "nt":
        try:
            app_id = f"MonitorPlus.{APP_SLUG}.1.0"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except Exception:
            pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument(
        "--startup",
        action="store_true",
        help="Indica que o aplicativo foi iniciado automaticamente junto com o Windows.",
    )
    parser.add_argument(
        "--minimized",
        action="store_true",
        help="Inicia o aplicativo minimizado na bandeja do sistema.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Executa diagnóstico rápido de banco, configuração e ambiente e encerra.",
    )
    return parser.parse_args(argv)


def run_self_test() -> int:
    """Executa autodiagnóstico rápido para validação do executável e ambiente."""
    log_file = setup_logging()
    logger = logging.getLogger("SelfTest")
    logger.info("Iniciando autodiagnóstico do %s...", APP_NAME)

    icon_path = ensure_icon_files(ASSETS_DIR)
    db = DatabaseManager(DB_PATH)
    cfg = db.load_config()
    cfg.save_to_file()

    ok, msg = NetworkScanner.check_share_available(cfg.caminho_monitorado)
    stats = db.get_indicators()
    print(f"APP: {APP_NAME}")
    print(f"DB_PATH: {DB_PATH}")
    print(f"ICON_PATH: {icon_path} (exists={icon_path.exists()})")
    print(f"MONITORED_PATH: {cfg.caminho_monitorado or '(não selecionado)'}")
    print(f"SHARE_AVAILABLE: {ok} ({msg})")
    print(f"INDICATORS: {stats}")
    print(f"LOG_FILE: {log_file}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return run_self_test()

    setup_logging()
    logger = logging.getLogger("Main")
    set_windows_app_id()

    try:
        icon_path = ensure_icon_files(ASSETS_DIR)
    except Exception as exc:
        logger.warning("Não foi possível gerar ícone dinâmico: %s", exc)
        icon_path = ASSETS_DIR / "icon.ico"

    db = DatabaseManager(DB_PATH)
    config = db.load_config()
    config.save_to_file()

    try:
        WindowsStartupManager.set_enabled(config.iniciar_com_windows)
    except Exception as exc:
        logger.warning("Aviso ao sincronizar inicialização automática: %s", exc)

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    notifier = NotificationManager(config=config)
    controller = HybridMonitorController(
        db=db,
        config=config,
    )

    from interface.main_window import MainWindow

    window = MainWindow(
        db=db,
        config=config,
        controller=controller,
        notifier=notifier,
        icon_path=icon_path,
    )

    controller.start()

    # Se ainda não houver pasta selecionada pelo usuário, abre a janela principal para que ele escolha
    has_path = bool(config.caminho_monitorado and config.caminho_monitorado.strip())
    start_minimized = has_path and (
        args.minimized or (args.startup and not config.abrir_ao_iniciar)
    )
    if start_minimized:
        logger.info(
            "Aplicativo iniciado minimizado na bandeja do sistema (monitoramento em segundo plano)."
        )
        window.hide()
    else:
        window.show()

    exit_code = app.exec()
    controller.stop()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
