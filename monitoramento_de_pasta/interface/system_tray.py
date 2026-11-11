"""
Controlador do ícone na Bandeja do Sistema (System Tray) próximo ao relógio do Windows.
Permite que o aplicativo funcione continuamente em segundo plano, exiba notificações
discretas e abra a Central de Pendências ao clicar no ícone ou na notificação.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from PIL.ImageQt import ImageQt
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from assets.icon_generator import create_app_icon_image
from config import APP_NAME

logger = logging.getLogger(__name__)


class SystemTrayController:
    """
    Gerencia o QSystemTrayIcon, seu menu de contexto, mudança dinâmica de selo de status
    e emissão de notificações nativas.
    """

    def __init__(
        self,
        parent_widget: QWidget,
        on_open_main: Callable[[], None],
        on_sync_now: Callable[[], None],
        on_toggle_pause: Callable[[], None],
        on_open_settings: Callable[[], None],
        on_exit_app: Callable[[], None],
        icon_path: Optional[Path] = None,
    ) -> None:
        self.parent_widget = parent_widget
        self.on_open_main = on_open_main
        self.on_sync_now = on_sync_now
        self.on_toggle_pause = on_toggle_pause
        self.on_open_settings = on_open_settings
        self.on_exit_app = on_exit_app

        self._icon_connected = self._build_qicon((16, 185, 129, 255))     # Verde
        self._icon_pending = self._build_qicon((245, 158, 11, 255))       # Laranja
        self._icon_disconnected = self._build_qicon((239, 68, 68, 255))   # Vermelho

        if icon_path and icon_path.exists():
            default_icon = QIcon(str(icon_path))
        else:
            default_icon = self._icon_connected

        self.tray_icon = QSystemTrayIcon(default_icon, parent_widget)
        self.tray_icon.setToolTip(f"{APP_NAME} — Iniciando...")

        self._build_menu()
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.messageClicked.connect(self.on_open_main)
        self.tray_icon.show()

    @staticmethod
    def _build_qicon(badge_rgba: tuple[int, int, int, int]) -> QIcon:
        pil_img = create_app_icon_image(128, badge_color=badge_rgba)
        qim = ImageQt(pil_img)
        return QIcon(QPixmap.fromImage(qim))

    def _build_menu(self) -> None:
        self.menu = QMenu()
        self.menu.setStyleSheet(
            """
            QMenu {
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #334155;
                padding: 6px;
                font-size: 13px;
            }
            QMenu::item {
                padding: 7px 22px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #0284C7;
                color: #FFFFFF;
            }
            QMenu::separator {
                height: 1px;
                background: #334155;
                margin: 5px 4px;
            }
            """
        )

        self.action_status = QAction("Status: Aguardando pasta...", self.menu)
        self.action_status.setEnabled(False)
        self.menu.addAction(self.action_status)

        self.action_pending_count = QAction("Pendências em aberto: 0", self.menu)
        self.action_pending_count.setEnabled(False)
        self.menu.addAction(self.action_pending_count)

        self.menu.addSeparator()

        self.action_open = QAction("Abrir Central de Pendências", self.menu)
        self.action_open.triggered.connect(self.on_open_main)
        self.menu.addAction(self.action_open)

        self.action_sync = QAction("Sincronizar Agora", self.menu)
        self.action_sync.triggered.connect(self.on_sync_now)
        self.menu.addAction(self.action_sync)

        self.action_pause = QAction("Pausar Monitoramento", self.menu)
        self.action_pause.triggered.connect(self.on_toggle_pause)
        self.menu.addAction(self.action_pause)

        self.action_settings = QAction("Configurações...", self.menu)
        self.action_settings.triggered.connect(self.on_open_settings)
        self.menu.addAction(self.action_settings)

        self.menu.addSeparator()

        self.action_exit = QAction("Sair do Monitor", self.menu)
        self.action_exit.triggered.connect(self.on_exit_app)
        self.menu.addAction(self.action_exit)

        self.tray_icon.setContextMenu(self.menu)

    def _on_tray_activated(
        self, reason: QSystemTrayIcon.ActivationReason
    ) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.on_open_main()

    def update_status(
        self,
        connected: bool,
        paused: bool,
        pending_count: int,
        has_path: bool = True,
    ) -> None:
        if not has_path:
            status_text = "Aguardando seleção de pasta"
            self.action_pause.setText("Pausar Monitoramento")
            self.tray_icon.setIcon(self._icon_pending)
        elif paused:
            status_text = "Pausado"
            self.action_pause.setText("Retomar Monitoramento")
            self.tray_icon.setIcon(self._icon_pending)
        elif not connected:
            status_text = "Pasta Indisponível (Reconectando...)"
            self.action_pause.setText("Pausar Monitoramento")
            self.tray_icon.setIcon(self._icon_disconnected)
        else:
            status_text = "Conectado e Monitorando"
            self.action_pause.setText("Pausar Monitoramento")
            if pending_count > 0:
                self.tray_icon.setIcon(self._icon_pending)
            else:
                self.tray_icon.setIcon(self._icon_connected)

        self.action_status.setText(f"Status: {status_text}")
        self.action_pending_count.setText(
            f"Pendências em aberto: {pending_count}"
        )
        self.tray_icon.setToolTip(
            f"{APP_NAME}\n{status_text}\nPendências em aberto: {pending_count}"
        )

    def show_notification(
        self, title: str, message: str, level: str = "info"
    ) -> None:
        if not self.tray_icon.isSystemTrayAvailable():
            return
        icon_type = QSystemTrayIcon.MessageIcon.Information
        if level == "warning":
            icon_type = QSystemTrayIcon.MessageIcon.Warning
        elif level == "error":
            icon_type = QSystemTrayIcon.MessageIcon.Critical

        self.tray_icon.showMessage(title, message, icon_type, 7000)

    def hide(self) -> None:
        self.tray_icon.hide()
