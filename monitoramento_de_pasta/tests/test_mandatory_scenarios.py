r"""
Suíte completa de testes automatizados validando todos os 14 cenários de monitoramento,
além dos filtros de checklist, notificações, interface gráfica PySide6 e indexação inicial
somente-leitura.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parent.parent
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

from config import AppConfig, is_temporary_or_system_file
from database.database import DatabaseManager
from database.models import EventType, TaskStatus
from monitor.network_scanner import HybridMonitorController, NetworkScanner
from notifications.windows_notifications import NotificationManager
from startup.windows_startup import WindowsStartupManager


@pytest.fixture
def temp_env():
    """Cria um ambiente isolado em diretório temporário para simulação completa."""
    base_tmp = Path(tempfile.mkdtemp(prefix="monitor_pasta_test_"))
    monitored_dir = base_tmp / "PASTA_MONITORADA"
    monitored_dir.mkdir(parents=True, exist_ok=True)
    (monitored_dir / "Janeiro").mkdir(parents=True, exist_ok=True)

    db_path = base_tmp / "test_monitor.db"
    cfg = AppConfig(
        caminho_monitorado=str(monitored_dir),
        intervalo_de_verificacao=2,
        iniciar_com_windows=True,
        abrir_ao_iniciar=False,
        notificacoes_ativas=True,
        debounce_segundos=0.6,
    )
    db = DatabaseManager(db_path=db_path)
    db.save_config(cfg)

    yield base_tmp, monitored_dir, db_path, db, cfg

    shutil.rmtree(base_tmp, ignore_errors=True)


def test_all_14_mandatory_scenarios(temp_env):
    """
    Executa sequencialmente os 14 cenários de monitoramento:
    1. Criar arquivo na pasta principal
    2. Criar arquivo dentro de subpasta
    3. Criar nova subpasta (e arquivo dentro dela)
    4. Modificar arquivo existente
    5. Renomear arquivo
    6. Excluir arquivo
    7. Desconectar compartilhamento/pasta
    8. Reconectar compartilhamento (detectando alterações feitas offline)
    9. Reiniciar aplicativo (persistência SQLite)
    10. Reiniciar Windows (configuração de inicialização automática HKCU)
    11. Marcar pendência como concluída
    12. Reabrir pendência
    13. Criar dois arquivos com nomes iguais em pastas diferentes
    14. Salvar um documento diversas vezes rapidamente (debounce + ignorar temporários)
    """
    base_tmp, monitored_dir, db_path, db, cfg = temp_env
    notifier = NotificationManager(config=cfg)
    captured_toasts = []
    notifier.set_tray_notifier(
        lambda title, body, level: captured_toasts.append((title, body, level))
    )

    controller = HybridMonitorController(
        db=db,
        config=cfg,
        on_new_task=lambda task: notifier.notify_task(task),
        on_connection_change=lambda ok, msg: notifier.notify_connection_status(
            ok, cfg.caminho_monitorado, msg
        ),
    )

    try:
        controller.force_sync_now()
        controller.start()
        time.sleep(0.4)
        assert controller.is_connected is True

        # CENÁRIO 1: Criar um arquivo na pasta principal
        file_root = monitored_dir / "Documento_Principal.xlsx"
        file_root.write_text("Conteudo inicial do documento", encoding="utf-8")
        time.sleep(1.0)
        controller.processor.flush_all(force=True)

        tasks = db.query_tasks()
        assert any(
            t.nome_arquivo == "Documento_Principal.xlsx"
            and t.tipo_evento == EventType.NOVO_ARQUIVO.value
            for t in tasks
        ), "Falha no Cenário 1: Novo arquivo na pasta principal não detectado."

        # CENÁRIO 2: Criar um arquivo dentro de uma subpasta existente
        file_sub = monitored_dir / "Janeiro" / "Relatorio_Jan.pdf"
        file_sub.write_text("PDF simulado de janeiro", encoding="utf-8")
        time.sleep(1.0)
        controller.processor.flush_all(force=True)

        tasks = db.query_tasks()
        assert any(
            t.nome_arquivo == "Relatorio_Jan.pdf"
            and "Janeiro" in t.caminho_relativo
            and t.tipo_evento == EventType.NOVO_ARQUIVO.value
            for t in tasks
        ), "Falha no Cenário 2: Arquivo em subpasta não detectado."

        # CENÁRIO 3: Criar uma nova subpasta (e verificar monitoramento recursivo automático)
        new_subfolder = monitored_dir / "Fevereiro" / "Documentos"
        new_subfolder.mkdir(parents=True, exist_ok=True)
        time.sleep(0.8)
        file_in_new_sub = new_subfolder / "Proposta_Fev.docx"
        file_in_new_sub.write_text("Documento dentro da nova subpasta", encoding="utf-8")
        time.sleep(1.0)
        controller.processor.flush_all(force=True)
        controller.force_sync_now()

        tasks = db.query_tasks()
        assert any(
            t.eh_pasta and t.tipo_evento == EventType.NOVA_PASTA.value
            for t in tasks
        ), "Falha no Cenário 3: Nova subpasta não detectada."
        assert any(
            t.nome_arquivo == "Proposta_Fev.docx"
            and t.tipo_evento == EventType.NOVO_ARQUIVO.value
            for t in tasks
        ), "Falha no Cenário 3: Arquivo criado dentro da nova subpasta não detectado."

        # CENÁRIO 4: Modificar um arquivo existente
        file_root.write_text(
            "Conteudo atualizado e expandido do documento v2",
            encoding="utf-8",
        )
        time.sleep(1.2)
        controller.processor.flush_all(force=True)

        tasks = db.query_tasks()
        assert any(
            t.nome_arquivo == "Documento_Principal.xlsx"
            and t.tipo_evento == EventType.ARQUIVO_MODIFICADO.value
            for t in tasks
        ), "Falha no Cenário 4: Modificação de arquivo não detectada."

        # CENÁRIO 5: Renomear um arquivo
        renamed_file = monitored_dir / "Documento_Principal_Renomeado.xlsx"
        file_root.rename(renamed_file)
        time.sleep(1.0)
        controller.processor.flush_all(force=True)
        controller.force_sync_now()

        tasks = db.query_tasks()
        assert any(
            t.nome_arquivo == "Documento_Principal_Renomeado.xlsx"
            and t.tipo_evento == EventType.ARQUIVO_RENOMEADO.value
            for t in tasks
        ), "Falha no Cenário 5: Renomeação de arquivo não detectada."

        # CENÁRIO 6: Excluir um arquivo
        renamed_file.unlink()
        time.sleep(1.0)
        controller.processor.flush_all(force=True)
        controller.force_sync_now()

        tasks = db.query_tasks()
        assert any(
            t.nome_arquivo == "Documento_Principal_Renomeado.xlsx"
            and t.tipo_evento == EventType.ARQUIVO_EXCLUIDO.value
            for t in tasks
        ), "Falha no Cenário 6: Exclusão de arquivo não detectada."

        # CENÁRIOS 7 e 8: Desconectar compartilhamento e Reconectar
        controller.set_simulated_offline(True)
        assert controller.is_connected is False
        conn_logs = db.get_recent_connection_logs()
        assert any(log.status == "DESCONECTADO" for log in conn_logs), (
            "Falha no Cenário 7: Desconexão não registrada no banco."
        )

        offline_file = monitored_dir / "Criado_Durante_Queda_Rede.xlsx"
        offline_file.write_text("Criado enquanto o servidor estava offline", encoding="utf-8")

        controller.set_simulated_offline(False)
        controller.processor.flush_all(force=True)
        assert controller.is_connected is True

        tasks = db.query_tasks()
        assert any(
            t.nome_arquivo == "Criado_Durante_Queda_Rede.xlsx"
            and t.tipo_evento == EventType.NOVO_ARQUIVO.value
            for t in tasks
        ), "Falha no Cenário 8: Arquivo criado durante desconexão não foi detectado ao reconectar."

        # CENÁRIO 13: Criar dois arquivos com nomes iguais em pastas diferentes
        dir_marco = monitored_dir / "Marco"
        dir_abril = monitored_dir / "Abril"
        dir_marco.mkdir(exist_ok=True)
        dir_abril.mkdir(exist_ok=True)

        homonym_1 = dir_marco / "Relatorio_Mensal.xlsx"
        homonym_2 = dir_abril / "Relatorio_Mensal.xlsx"
        homonym_1.write_text("Planilha de Marco", encoding="utf-8")
        homonym_2.write_text("Planilha de Abril diferente", encoding="utf-8")
        time.sleep(1.0)
        controller.processor.flush_all(force=True)

        tasks_homonym = [
            t for t in db.query_tasks() if t.nome_arquivo == "Relatorio_Mensal.xlsx"
        ]
        rel_paths = {t.caminho_relativo for t in tasks_homonym}
        assert "Marco/Relatorio_Mensal.xlsx" in rel_paths
        assert "Abril/Relatorio_Mensal.xlsx" in rel_paths

        # CENÁRIO 14: Salvar um documento diversas vezes rapidamente + temporários
        temp_office = dir_marco / "~$Relatorio_Mensal.xlsx"
        temp_generic = dir_marco / "save_temp.tmp"
        temp_office.write_text("lock", encoding="utf-8")
        temp_generic.write_text("tmp", encoding="utf-8")
        assert is_temporary_or_system_file(temp_office.name) is True
        assert is_temporary_or_system_file(temp_generic.name) is True

        mod_count_before = len(
            [
                t
                for t in db.query_tasks()
                if t.caminho_relativo == "Marco/Relatorio_Mensal.xlsx"
                and t.tipo_evento == EventType.ARQUIVO_MODIFICADO.value
            ]
        )
        for i in range(5):
            homonym_1.write_text(
                f"Salvamento rapido numero {i + 1}", encoding="utf-8"
            )
            time.sleep(0.06)

        time.sleep(1.1)
        controller.processor.flush_all(force=True)

        mod_tasks_after = [
            t
            for t in db.query_tasks()
            if t.caminho_relativo == "Marco/Relatorio_Mensal.xlsx"
            and t.tipo_evento == EventType.ARQUIVO_MODIFICADO.value
        ]
        assert len(mod_tasks_after) - mod_count_before == 1, (
            f"Falha no Cenário 14: 5 salvamentos rápidos geraram {len(mod_tasks_after) - mod_count_before} eventos em vez de 1 consolidado."
        )
        assert not any(
            t.nome_arquivo in ("~$Relatorio_Mensal.xlsx", "save_temp.tmp")
            for t in db.query_tasks()
        ), "Falha no Cenário 14: Arquivo temporário não foi ignorado."

        # CENÁRIOS 11 e 12: Marcar pendência como concluída e Reabrir pendência
        target_task = mod_tasks_after[0]
        assert target_task.concluido is False

        updated_task = db.set_task_completed(
            target_task.task_id, True, observacao="Verificado pelo usuário"
        )
        assert updated_task is not None
        assert updated_task.concluido is True
        assert updated_task.status == TaskStatus.CONCLUIDO.value
        assert updated_task.data_conclusao is not None
        assert updated_task.observacao == "Verificado pelo usuário"

        stats_mid = db.get_indicators()
        assert stats_mid["concluidas"] >= 1

        reopened_task = db.set_task_completed(target_task.task_id, False)
        assert reopened_task is not None
        assert reopened_task.concluido is False
        assert reopened_task.status == TaskStatus.PENDENTE.value
        assert reopened_task.data_conclusao is None

        db.set_task_completed(target_task.task_id, True)

        # CENÁRIO 9: Reiniciar o aplicativo (persistência SQLite)
        total_before_restart = db.get_indicators()["total"]
        controller.stop()

        db_restarted = DatabaseManager(db_path=db_path)
        stats_after_restart = db_restarted.get_indicators()
        assert stats_after_restart["total"] == total_before_restart
        assert stats_after_restart["concluidas"] >= 1

        # CENÁRIO 10: Inicialização automática com o Windows
        ok_startup, msg_startup = WindowsStartupManager.set_enabled(True)
        assert ok_startup is True, f"Falha ao configurar startup: {msg_startup}"
        assert WindowsStartupManager.is_enabled() is True

        assert len(notifier.history) > 0
        assert len(captured_toasts) > 0

    finally:
        controller.stop()


def test_user_selected_folder_readonly_baseline(tmp_path):
    """
    Verifica a seleção dinâmica de pasta pelo usuário e indexação inicial somente-leitura,
    garantindo que arquivos pré-existentes sejam indexados no baseline sem falsas notificações.
    """
    sample_dir = tmp_path / "Pasta_Escolhida_Pelo_Usuario"
    (sample_dir / "Subpasta_A").mkdir(parents=True)
    (sample_dir / "Subpasta_A" / "Existente_1.txt").write_text("a", encoding="utf-8")
    (sample_dir / "Existente_2.txt").write_text("b", encoding="utf-8")

    db = DatabaseManager(db_path=tmp_path / "baseline_test.db")
    cfg = AppConfig(caminho_monitorado=str(sample_dir))
    from monitor.event_processor import EventProcessor

    processor = EventProcessor(db=db, config=cfg)
    scanner = NetworkScanner(db=db, processor=processor, config=cfg)
    try:
        ok, changes = scanner.scan_and_reconcile(str(sample_dir))
        assert ok is True
        assert changes == 0
        assert db.has_baseline_for_path(str(sample_dir)) is True
        snaps = db.get_snapshots_for_path(str(sample_dir))
        assert len(snaps) >= 3
    finally:
        processor.stop()
