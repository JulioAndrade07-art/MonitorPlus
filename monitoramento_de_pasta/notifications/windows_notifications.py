"""
Gerenciador de notificações nativas do Windows (Toast / Bandeja do Sistema).
Formata mensagens discretas e permite abrir a Central de Pendências ao clicar
na notificação, sem nunca abrir automaticamente o arquivo alterado.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Optional

from config import APP_NAME, AppConfig
from database.models import EventType, TaskItem
from monitor.file_fingerprint import format_location_display, normalize_path

logger = logging.getLogger(__name__)


@dataclass
class DispatchedNotification:
    """Registro de notificação enviada (útil para auditoria e testes)."""

    title: str
    body: str
    event_type: str
    timestamp: str
    task_id: Optional[int] = None


class NotificationManager:
    """
    Coordena o envio de notificações discretas na área de trabalho do Windows.
    """

    def __init__(
        self,
        config: AppConfig,
        tray_notifier: Optional[Callable[[str, str, str], None]] = None,
    ) -> None:
        self.config = config
        self._tray_notifier = tray_notifier
        self._lock = threading.RLock()
        self.history: List[DispatchedNotification] = []

    def set_tray_notifier(
        self, tray_notifier: Callable[[str, str, str], None]
    ) -> None:
        with self._lock:
            self._tray_notifier = tray_notifier

    def update_config(self, new_config: AppConfig) -> None:
        with self._lock:
            self.config = new_config

    def should_notify_event(self, event_type_str: str) -> bool:
        cfg = self.config
        if not cfg.notificacoes_ativas:
            return False

        if event_type_str in (
            EventType.NOVO_ARQUIVO.value,
            EventType.NOVA_PASTA.value,
        ):
            return bool(cfg.notificar_criacao)

        if event_type_str in (
            EventType.ARQUIVO_MODIFICADO.value,
            EventType.PASTA_MODIFICADA.value,
        ):
            return bool(cfg.notificar_modificacao)

        if event_type_str in (
            EventType.ARQUIVO_EXCLUIDO.value,
            EventType.PASTA_EXCLUIDA.value,
        ):
            return bool(cfg.notificar_exclusao)

        if event_type_str in (
            EventType.ARQUIVO_RENOMEADO.value,
            EventType.PASTA_RENOMEADA.value,
        ):
            return bool(cfg.notificar_renomeacao)

        return True

    def format_task_notification(self, task: TaskItem) -> tuple[str, str]:
        ev = task.tipo_evento
        norm_base = normalize_path(self.config.caminho_monitorado)
        root_name = os.path.basename(norm_base) or "monitorada"
        local_str = format_location_display(
            task.caminho_completo, self.config.caminho_monitorado
        )
        horario = task.horario_curto
        data_hora = task.data_formatada

        if ev == EventType.NOVO_ARQUIVO.value:
            title = "Novo arquivo identificado"
            header = f"Novo arquivo na pasta {root_name}."
        elif ev == EventType.ARQUIVO_MODIFICADO.value:
            title = "Arquivo modificado"
            header = "Um documento foi atualizado."
        elif ev == EventType.ARQUIVO_EXCLUIDO.value:
            title = "Arquivo excluído"
            header = "Um arquivo foi removido."
        elif ev == EventType.ARQUIVO_RENOMEADO.value:
            title = "Arquivo renomeado"
            header = "O nome de um arquivo foi alterado."
        elif ev == EventType.NOVA_PASTA.value:
            title = "Nova pasta identificada"
            header = "Uma nova subpasta foi criada."
        elif ev == EventType.PASTA_MODIFICADA.value:
            title = "Pasta modificada"
            header = "Alteração estrutural detectada."
        elif ev == EventType.PASTA_EXCLUIDA.value:
            title = "Pasta excluída"
            header = "Um diretório foi removido."
        elif ev == EventType.PASTA_RENOMEADA.value:
            title = "Pasta renomeada"
            header = "O nome de um diretório foi alterado."
        else:
            title = f"Alteração detectada: {ev}"
            header = "Alteração registrada no monitoramento."

        label_item = "Pasta" if task.eh_pasta else "Arquivo"
        body = (
            f"{header}\n"
            f"{label_item}: {task.nome_arquivo}\n"
            f"Local: {local_str}\n"
            f"Horário: {horario} ({data_hora})"
        )
        return title, body

    def notify_task(self, task: TaskItem) -> bool:
        if not self.should_notify_event(task.tipo_evento):
            return False

        title, body = self.format_task_notification(task)
        return self._dispatch(
            title=title,
            body=body,
            level="info",
            event_type=task.tipo_evento,
            task_id=task.task_id,
        )

    def notify_connection_status(
        self, connected: bool, path: str, details: str = ""
    ) -> bool:
        if (
            not self.config.notificacoes_ativas
            or not self.config.notificar_desconexao
            or not path
        ):
            return False

        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        if connected:
            title = "Conexão com a pasta restabelecida"
            body = (
                f"O diretório monitorado voltou a ficar disponível.\n"
                f"Local: {path}\n"
                f"Horário: {now_str}"
            )
            level = "info"
        else:
            title = "Pasta monitorada indisponível"
            body = (
                f"Não foi possível acessar a pasta monitorada. Tentando reconectar automaticamente...\n"
                f"Local: {path}\n"
                f"Horário: {now_str}"
            )
            level = "warning"

        return self._dispatch(
            title=title,
            body=body,
            level=level,
            event_type="CONEXAO_REDE",
        )

    def send_test_notification(self) -> bool:
        now_hm = datetime.now().strftime("%H:%M")
        now_full = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        title = f"Teste de Notificação — {APP_NAME}"
        body = (
            "As notificações da área de trabalho estão funcionando corretamente.\n"
            "Arquivo: Documento_Exemplo.xlsx\n"
            "Local: PastaMonitorada/Subpasta/\n"
            f"Horário: {now_hm} ({now_full})"
        )
        return self._dispatch(
            title=title,
            body=body,
            level="info",
            event_type="TESTE",
        )

    def _dispatch(
        self,
        title: str,
        body: str,
        level: str = "info",
        event_type: str = "",
        task_id: Optional[int] = None,
    ) -> bool:
        with self._lock:
            record = DispatchedNotification(
                title=title,
                body=body,
                event_type=event_type,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                task_id=task_id,
            )
            self.history.append(record)
            if len(self.history) > 500:
                self.history = self.history[-500:]
            tray_fn = self._tray_notifier

        try:
            if tray_fn is not None:
                tray_fn(title, body, level)
                return True
            else:
                self._fallback_windows_toast(title, body)
                return True
        except Exception as exc:
            logger.warning(
                "Falha ao exibir notificação na área de trabalho: %s", exc
            )
            return False

    @staticmethod
    def _fallback_windows_toast(title: str, body: str) -> None:
        safe_title = (
            title.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("'", "&#39;")
            .replace('"', "&quot;")
        )
        safe_body = (
            body.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("'", "&#39;")
            .replace('"', "&quot;")
        )
        ps_script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null; "
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null; "
            f"$xml = New-Object Windows.Data.Xml.Dom.XmlDocument; "
            f'$xml.LoadXml(\'<toast><visual><binding template="ToastGeneric"><text>{safe_title}</text><text>{safe_body}</text></binding></visual></toast>\'); '
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); "
            f'[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{APP_NAME}").Show($toast);'
        )

        def _run_ps():
            try:
                creation_flags = getattr(
                    subprocess, "CREATE_NO_WINDOW", 0x08000000
                )
                subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-NonInteractive",
                        "-WindowStyle",
                        "Hidden",
                        "-Command",
                        ps_script,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    creationflags=creation_flags,
                )
            except Exception as exc:
                logger.debug("Fallback WinRT toast falhou: %s", exc)

        threading.Thread(target=_run_ps, daemon=True).start()
