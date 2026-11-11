"""
Testes automatizados da Interface Gráfica (PySide6), Seletor de Pasta do Usuário
e Filtros da Central de Pendências.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PACKAGE_DIR = Path(__file__).resolve().parent.parent
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

from PySide6.QtWidgets import QApplication

from config import AppConfig
from database.database import DatabaseManager
from database.models import EventRecord, EventType
from interface.main_window import MainWindow
from monitor.network_scanner import HybridMonitorController
from notifications.windows_notifications import NotificationManager


def test_ui_filters_and_checklist(tmp_path):
    app = QApplication.instance() or QApplication([])

    db_path = tmp_path / "ui_test.db"
    monitored_dir = tmp_path / "PASTA_UI"
    monitored_dir.mkdir(parents=True, exist_ok=True)

    # Inicia sem pasta configurada e depois o usuário digita/escolhe a pasta na interface
    cfg = AppConfig(caminho_monitorado="")
    db = DatabaseManager(db_path=db_path)
    db.save_config(cfg)

    ev1 = EventRecord(
        id=None,
        caminho_completo=str(monitored_dir / "Janeiro" / "Documento_01.xlsx"),
        caminho_relativo="Janeiro/Documento_01.xlsx",
        nome_arquivo="Documento_01.xlsx",
        tipo_evento=EventType.NOVO_ARQUIVO.value,
        data_evento="2026-11-11 10:00:00",
        tamanho_arquivo=10240,
        identificador_do_evento="uid_1",
        hash="abc12345",
    )
    ev2 = EventRecord(
        id=None,
        caminho_completo=str(monitored_dir / "Fevereiro" / "Estoque.xlsx"),
        caminho_relativo="Fevereiro/Estoque.xlsx",
        nome_arquivo="Estoque.xlsx",
        tipo_evento=EventType.ARQUIVO_MODIFICADO.value,
        data_evento="2026-11-11 11:30:00",
        tamanho_arquivo=20480,
        identificador_do_evento="uid_2",
        hash="def67890",
    )
    ev3 = EventRecord(
        id=None,
        caminho_completo=str(monitored_dir / "Marco" / "NotaAntiga.pdf"),
        caminho_relativo="Marco/NotaAntiga.pdf",
        nome_arquivo="NotaAntiga.pdf",
        tipo_evento=EventType.ARQUIVO_EXCLUIDO.value,
        data_evento="2026-11-10 09:15:00",
        tamanho_arquivo=None,
        identificador_do_evento="uid_3",
        hash=None,
    )

    t1 = db.register_event_and_task(ev1)
    t2 = db.register_event_and_task(ev2)
    t3 = db.register_event_and_task(ev3)
    assert t1 and t2 and t3

    notifier = NotificationManager(config=cfg)
    controller = HybridMonitorController(db=db, config=cfg)
    window = MainWindow(
        db=db,
        config=cfg,
        controller=controller,
        notifier=notifier,
    )

    try:
        # Usuário coloca o local onde quer monitorar diretamente na barra da interface
        window.path_input.setText(str(monitored_dir))
        window._apply_quick_path_input()
        assert db.load_config().caminho_monitorado == str(monitored_dir)

        assert window.table.rowCount() == 3

        window._handle_toggle_task(t1.task_id, True)
        stats = db.get_indicators()
        assert stats["total"] == 3
        assert stats["concluidas"] == 1
        assert stats["pendentes"] == 2

        window._set_status_filter("PENDENTES")
        assert window.table.rowCount() == 2

        window._set_status_filter("CONCLUIDAS")
        assert window.table.rowCount() == 1

        window.clear_all_filters()
        assert window.table.rowCount() == 3
        window.search_input.setText("Estoque")
        assert window.table.rowCount() == 1

        window.clear_all_filters()
        db.mark_all_pending_completed()
        window.refresh_all_ui()
        stats_all = db.get_indicators()
        assert stats_all["pendentes"] == 0
        assert stats_all["concluidas"] == 3
    finally:
        window._force_quit = True
        window.close()
        controller.stop()
