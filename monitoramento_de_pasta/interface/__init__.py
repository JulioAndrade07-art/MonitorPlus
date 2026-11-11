"""Pacote de interface gráfica (PySide6) da Central de Pendências."""

from .main_window import MainWindow
from .settings_window import SettingsDialog
from .system_tray import SystemTrayController
from .task_list import TaskDetailDialog, TaskTableWidget

__all__ = [
    "MainWindow",
    "SettingsDialog",
    "SystemTrayController",
    "TaskTableWidget",
    "TaskDetailDialog",
]
