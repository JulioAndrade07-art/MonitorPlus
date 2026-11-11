"""
Janela Principal — Central de Pendências do Monitoramento de Pasta.
Inclui seletor direto de pasta no cabeçalho para que o usuário escolha ou digite
facilmente qualquer diretório local ou de rede que deseje monitorar.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config import APP_NAME, AppConfig
from database.database import DatabaseManager
from database.models import EventType, TaskItem
from interface.settings_window import SettingsDialog
from interface.system_tray import SystemTrayController
from interface.task_list import (
    TaskDetailDialog,
    TaskTableWidget,
    open_file_location_in_explorer,
)
from monitor.network_scanner import HybridMonitorController
from notifications.windows_notifications import NotificationManager

logger = logging.getLogger(__name__)


class MonitorSignalBridge(QObject):
    """Ponte de sinais Qt para comunicação segura entre threads de monitoramento e a GUI."""

    new_task_signal = Signal(object)
    connection_changed_signal = Signal(bool, str)
    sync_completed_signal = Signal(str, bool, int)


class IndicatorCard(QFrame):
    """Card moderno de indicador numérico para o painel superior."""

    def __init__(
        self,
        title: str,
        accent_color: str,
        subtitle: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.accent_color = accent_color
        self.setObjectName("IndicatorCard")
        self.setStyleSheet(
            f"""
            QFrame#IndicatorCard {{
                background-color: #1E293B;
                border: 1px solid #334155;
                border-left: 4px solid {accent_color};
                border-radius: 8px;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(3)

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet(
            "color: #94A3B8; font-size: 12px; font-weight: 600;"
        )
        layout.addWidget(self.lbl_title)

        self.lbl_value = QLabel("0")
        self.lbl_value.setStyleSheet(
            f"color: {accent_color}; font-size: 24px; font-weight: bold;"
        )
        layout.addWidget(self.lbl_value)

        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setStyleSheet("color: #64748B; font-size: 11px;")
        layout.addWidget(self.lbl_sub)

    def set_value(self, value: str, subtitle: Optional[str] = None) -> None:
        self.lbl_value.setText(value)
        if subtitle is not None:
            self.lbl_sub.setText(subtitle)


class MainWindow(QMainWindow):
    """
    Interface Principal — Central de Pendências do Monitoramento de Pasta.
    """

    def __init__(
        self,
        db: DatabaseManager,
        config: AppConfig,
        controller: HybridMonitorController,
        notifier: NotificationManager,
        icon_path: Optional[Path] = None,
    ) -> None:
        super().__init__()
        self.db = db
        self.config = config
        self.controller = controller
        self.notifier = notifier
        self.icon_path = icon_path
        self._force_quit = False
        self._initial_connection_announced = False

        self._status_filter = "TODAS"
        self._period_filter = "TODOS"
        self._event_type_filter = "TODOS"
        self._search_query = ""
        self._sort_desc = True

        self.bridge = MonitorSignalBridge(self)
        self.bridge.new_task_signal.connect(self._on_new_task_ui)
        self.bridge.connection_changed_signal.connect(
            self._on_connection_changed_ui
        )
        self.bridge.sync_completed_signal.connect(self._on_sync_completed_ui)

        self.controller.processor.on_new_task_callback = (
            lambda task: self.bridge.new_task_signal.emit(task)
        )
        self.controller.on_connection_change = (
            lambda ok, msg: self.bridge.connection_changed_signal.emit(ok, msg)
        )
        self.controller.on_sync_completed = (
            lambda ts, ok, chg: self.bridge.sync_completed_signal.emit(
                ts, ok, chg
            )
        )

        self.setWindowTitle(f"{APP_NAME} — Central de Pendências")
        if icon_path and icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        w = int(self.config.preferencias_de_interface.get("largura_janela", 1120))
        h = int(self.config.preferencias_de_interface.get("altura_janela", 740))
        self.resize(max(940, w), max(620, h))

        self._setup_ui()

        self.tray = SystemTrayController(
            parent_widget=self,
            on_open_main=self.bring_to_front,
            on_sync_now=self.trigger_manual_sync,
            on_toggle_pause=self.toggle_pause_monitoring,
            on_open_settings=self.open_settings_dialog,
            on_exit_app=self.quit_application,
            icon_path=icon_path,
        )
        self.notifier.set_tray_notifier(self.tray.show_notification)

        self.refresh_all_ui()

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(10000)
        self._ui_timer.timeout.connect(self.refresh_indicators_and_tray)
        self._ui_timer.start()

    def _setup_ui(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget#CentralRoot {
                background-color: #0F172A;
                color: #F8FAFC;
                font-family: "Segoe UI", sans-serif;
            }
            QFrame#HeaderBanner {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 10px;
            }
            QFrame#FilterBar {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 8px;
            }
            QLineEdit, QComboBox {
                background-color: #0F172A;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #38BDF8;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background-color: #1E293B;
                color: #F8FAFC;
                selection-background-color: #0284C7;
                border: 1px solid #334155;
            }
            QPushButton {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 7px 13px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #475569;
            }
            QPushButton#PrimaryFolderBtn {
                background-color: #0284C7;
                color: #FFFFFF;
                border-color: #0369A1;
            }
            QPushButton#PrimaryFolderBtn:hover {
                background-color: #0369A1;
            }
            QPushButton#FilterPillActive {
                background-color: #0284C7;
                color: #FFFFFF;
                border-color: #0369A1;
            }
            QPushButton#ActionCompleteAll {
                background-color: #059669;
                color: #FFFFFF;
                border-color: #047857;
            }
            QPushButton#ActionCompleteAll:hover {
                background-color: #047857;
            }
            QPushButton#ActionDanger {
                background-color: #1E293B;
                color: #F87171;
                border-color: #7F1D1D;
            }
            QPushButton#ActionDanger:hover {
                background-color: #7F1D1D;
                color: #FFFFFF;
            }
            QTableWidget {
                background-color: #0F172A;
                alternate-background-color: #131D31;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 8px;
                font-size: 13px;
                selection-background-color: #1E3A5F;
            }
            QHeaderView::section {
                background-color: #1E293B;
                color: #94A3B8;
                font-weight: bold;
                font-size: 12px;
                padding: 9px 8px;
                border: none;
                border-bottom: 1px solid #334155;
            }
            """
        )

        central = QWidget()
        central.setObjectName("CentralRoot")
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(16, 14, 16, 14)
        root_layout.setSpacing(12)

        # --------------------------------------------------------------
        # 1. CABEÇALHO COM SELETOR DE PASTA INTERATIVO
        # --------------------------------------------------------------
        header_frame = QFrame()
        header_frame.setObjectName("HeaderBanner")
        header_outer = QVBoxLayout(header_frame)
        header_outer.setContentsMargins(16, 12, 16, 12)
        header_outer.setSpacing(10)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        lbl_app_name = QLabel(f"📁 {APP_NAME}")
        lbl_app_name.setStyleSheet(
            "font-size: 19px; font-weight: bold; color: #F8FAFC;"
        )
        top_bar.addWidget(lbl_app_name)

        self.lbl_monitor_state = QLabel("● Monitoramento Ativo")
        self.lbl_monitor_state.setStyleSheet(
            """
            color: #34D399;
            background-color: #064E3B;
            border: 1px solid #059669;
            border-radius: 10px;
            padding: 2px 10px;
            font-size: 12px;
            font-weight: bold;
            """
        )
        top_bar.addWidget(self.lbl_monitor_state)

        self.lbl_conn_badge = QLabel("📁 Aguardando seleção de pasta")
        self.lbl_conn_badge.setStyleSheet(
            """
            color: #38BDF8;
            background-color: #0C4A6E;
            border: 1px solid #0284C7;
            border-radius: 6px;
            padding: 4px 10px;
            font-size: 12px;
            font-weight: bold;
            """
        )
        top_bar.addWidget(self.lbl_conn_badge)

        top_bar.addStretch()

        self.lbl_last_sync = QLabel("Última sincronização: -")
        self.lbl_last_sync.setStyleSheet("color: #94A3B8; font-size: 12px;")
        top_bar.addWidget(self.lbl_last_sync)

        self.btn_pause_resume = QPushButton("⏸ Pausar")
        self.btn_pause_resume.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pause_resume.clicked.connect(self.toggle_pause_monitoring)
        top_bar.addWidget(self.btn_pause_resume)

        btn_settings = QPushButton("⚙ Configurações")
        btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_settings.clicked.connect(self.open_settings_dialog)
        top_bar.addWidget(btn_settings)

        header_outer.addLayout(top_bar)

        # Linha interativa para o usuário colocar ou escolher o local monitorado
        path_selector_row = QHBoxLayout()
        path_selector_row.setSpacing(8)

        lbl_path_prompt = QLabel("Local monitorado:")
        lbl_path_prompt.setStyleSheet(
            "color: #CBD5E1; font-size: 13px; font-weight: 600;"
        )
        path_selector_row.addWidget(lbl_path_prompt)

        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText(
            r"Digite ou selecione o local da pasta para monitorar (ex.: C:\Documentos ou \\SERVIDOR\Pasta)..."
        )
        self.path_input.setText(self.config.caminho_monitorado)
        self.path_input.returnPressed.connect(self._apply_quick_path_input)
        path_selector_row.addWidget(self.path_input, stretch=1)

        btn_choose_dir = QPushButton("📂 Selecionar Pasta...")
        btn_choose_dir.setObjectName("PrimaryFolderBtn")
        btn_choose_dir.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_choose_dir.setToolTip(
            "Escolher pasta local ou de rede pelo explorador do Windows"
        )
        btn_choose_dir.clicked.connect(self._browse_and_apply_folder)
        path_selector_row.addWidget(btn_choose_dir)

        btn_apply_path = QPushButton("✔ Monitorar Local")
        btn_apply_path.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_apply_path.setToolTip(
            "Aplicar o caminho digitado acima e iniciar o monitoramento"
        )
        btn_apply_path.clicked.connect(self._apply_quick_path_input)
        path_selector_row.addWidget(btn_apply_path)

        # Mantém compatibilidade com atributo lbl_monitored_path
        self.lbl_monitored_path = self.path_input

        header_outer.addLayout(path_selector_row)
        root_layout.addWidget(header_frame)

        # --------------------------------------------------------------
        # 2. INDICADORES
        # --------------------------------------------------------------
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)

        self.card_total = IndicatorCard(
            "TOTAL DE ALTERAÇÕES", "#38BDF8", "Histórico registrado"
        )
        self.card_pending = IndicatorCard(
            "PENDÊNCIAS EM ABERTO", "#F59E0B", "Aguardando verificação"
        )
        self.card_completed = IndicatorCard(
            "PENDÊNCIAS CONCLUÍDAS", "#10B981", "Já verificadas / resolvidas"
        )
        self.card_recent = IndicatorCard(
            "ÚLTIMAS ALTERAÇÕES (HOJE)", "#C084FC", "Nenhuma alteração hoje"
        )

        cards_row.addWidget(self.card_total)
        cards_row.addWidget(self.card_pending)
        cards_row.addWidget(self.card_completed)
        cards_row.addWidget(self.card_recent)
        root_layout.addLayout(cards_row)

        # --------------------------------------------------------------
        # 3. BARRA DE FILTROS E PESQUISA
        # --------------------------------------------------------------
        filter_frame = QFrame()
        filter_frame.setObjectName("FilterBar")
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(12, 8, 12, 8)
        filter_layout.setSpacing(8)

        self.btn_filter_all = QPushButton("Todas")
        self.btn_filter_pending = QPushButton("Pendentes")
        self.btn_filter_completed = QPushButton("Concluídas")

        for btn, st_val in (
            (self.btn_filter_all, "TODAS"),
            (self.btn_filter_pending, "PENDENTES"),
            (self.btn_filter_completed, "CONCLUIDAS"),
        ):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _, val=st_val: self._set_status_filter(val)
            )
            filter_layout.addWidget(btn)

        self.combo_period = QComboBox()
        self.combo_period.addItem("📅 Período: Todos", "TODOS")
        self.combo_period.addItem("📅 Hoje", "HOJE")
        self.combo_period.addItem("📅 Últimos 7 dias", "7_DIAS")
        self.combo_period.addItem("📅 Últimos 30 dias", "30_DIAS")
        self.combo_period.currentIndexChanged.connect(self._on_filters_changed)
        filter_layout.addWidget(self.combo_period)

        self.combo_event_type = QComboBox()
        self.combo_event_type.addItem("🏷 Evento: Todos", "TODOS")
        for ev_val in EventType.all_values():
            self.combo_event_type.addItem(ev_val, ev_val)
        self.combo_event_type.currentIndexChanged.connect(
            self._on_filters_changed
        )
        filter_layout.addWidget(self.combo_event_type)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "🔎 Pesquisar por nome de arquivo, subpasta ou observação..."
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_filters_changed)
        filter_layout.addWidget(self.search_input, stretch=1)

        self.combo_sort = QComboBox()
        self.combo_sort.addItem("⬇ Mais recentes", True)
        self.combo_sort.addItem("⬆ Mais antigos", False)
        self.combo_sort.currentIndexChanged.connect(self._on_filters_changed)
        filter_layout.addWidget(self.combo_sort)

        btn_clear_filters = QPushButton("Limpar Filtros")
        btn_clear_filters.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear_filters.clicked.connect(self.clear_all_filters)
        filter_layout.addWidget(btn_clear_filters)

        root_layout.addWidget(filter_frame)
        self._update_status_pill_styles()

        # --------------------------------------------------------------
        # 4. TABELA DE ALTERAÇÕES / CHECKLIST
        # --------------------------------------------------------------
        self.table = TaskTableWidget(
            on_toggle_task=self._handle_toggle_task,
            on_open_details=self._handle_open_task_details,
            parent=self,
        )
        root_layout.addWidget(self.table, stretch=1)

        # --------------------------------------------------------------
        # 5. BARRA INFERIOR DE AÇÕES DO CHECKLIST
        # --------------------------------------------------------------
        actions_row = QHBoxLayout()
        actions_row.setSpacing(10)

        self.btn_complete_all = QPushButton("✔ Marcar Todas como Concluídas")
        self.btn_complete_all.setObjectName("ActionCompleteAll")
        self.btn_complete_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_complete_all.clicked.connect(self.mark_all_displayed_completed)
        actions_row.addWidget(self.btn_complete_all)

        btn_sync_now = QPushButton("🔄 Sincronizar Agora")
        btn_sync_now.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_sync_now.clicked.connect(self.trigger_manual_sync)
        actions_row.addWidget(btn_sync_now)

        btn_open_root = QPushButton("📂 Abrir Pasta Monitorada")
        btn_open_root.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open_root.clicked.connect(
            lambda: open_file_location_in_explorer(
                self.config.caminho_monitorado, self
            )
        )
        actions_row.addWidget(btn_open_root)

        actions_row.addStretch()

        self.lbl_visible_count = QLabel("Exibindo 0 registros")
        self.lbl_visible_count.setStyleSheet("color: #94A3B8; font-size: 12px;")
        actions_row.addWidget(self.lbl_visible_count)

        btn_delete_explicit = QPushButton("🗑 Excluir Selecionadas")
        btn_delete_explicit.setObjectName("ActionDanger")
        btn_delete_explicit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_delete_explicit.setToolTip(
            "Exclui permanentemente os registros selecionados na tabela (ação explícita)."
        )
        btn_delete_explicit.clicked.connect(self.delete_selected_tasks_explicit)
        actions_row.addWidget(btn_delete_explicit)

        root_layout.addLayout(actions_row)

    # ------------------------------------------------------------------
    # Seleção Direta de Pasta pelo Usuário
    # ------------------------------------------------------------------

    def _browse_and_apply_folder(self) -> None:
        current = self.path_input.text().strip()
        selected = QFileDialog.getExistingDirectory(
            self,
            "Escolher Pasta para Monitorar",
            current or "",
        )
        if selected:
            norm = selected.replace("/", "\\")
            self.path_input.setText(norm)
            self._apply_quick_path_input()

    def _apply_quick_path_input(self) -> None:
        new_path = self.path_input.text().strip()
        self.config.caminho_monitorado = new_path
        self._apply_new_config(self.config)

    # ------------------------------------------------------------------
    # Lógica de Filtros e Checklist
    # ------------------------------------------------------------------

    def _set_status_filter(self, status_val: str) -> None:
        self._status_filter = status_val
        self._update_status_pill_styles()
        self.refresh_task_table()

    def _update_status_pill_styles(self) -> None:
        mapping = {
            "TODAS": self.btn_filter_all,
            "PENDENTES": self.btn_filter_pending,
            "CONCLUIDAS": self.btn_filter_completed,
        }
        for key, btn in mapping.items():
            btn.setObjectName(
                "FilterPillActive" if key == self._status_filter else ""
            )
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _on_filters_changed(self) -> None:
        self._period_filter = str(self.combo_period.currentData() or "TODOS")
        self._event_type_filter = str(
            self.combo_event_type.currentData() or "TODOS"
        )
        self._search_query = self.search_input.text().strip()
        self._sort_desc = bool(self.combo_sort.currentData())
        self.refresh_task_table()

    def clear_all_filters(self) -> None:
        self._status_filter = "TODAS"
        self._update_status_pill_styles()
        self.combo_period.blockSignals(True)
        self.combo_event_type.blockSignals(True)
        self.search_input.blockSignals(True)
        self.combo_sort.blockSignals(True)

        self.combo_period.setCurrentIndex(0)
        self.combo_event_type.setCurrentIndex(0)
        self.search_input.clear()
        self.combo_sort.setCurrentIndex(0)

        self.combo_period.blockSignals(False)
        self.combo_event_type.blockSignals(False)
        self.search_input.blockSignals(False)
        self.combo_sort.blockSignals(False)

        self._on_filters_changed()

    def refresh_all_ui(self) -> None:
        if not self.path_input.hasFocus():
            self.path_input.setText(self.config.caminho_monitorado)
        self.refresh_task_table()
        self.refresh_indicators_and_tray()

    def refresh_task_table(self) -> None:
        tasks = self.db.query_tasks(
            status_filter=self._status_filter,
            period_filter=self._period_filter,
            event_type_filter=self._event_type_filter,
            search_query=self._search_query,
            sort_desc=self._sort_desc,
            limit=self.config.limite_historico,
        )
        self.table.populate_tasks(tasks)
        self.lbl_visible_count.setText(f"Exibindo {len(tasks)} registro(s)")

    def refresh_indicators_and_tray(self) -> None:
        stats = self.db.get_indicators()
        total = stats["total"]
        pendentes = stats["pendentes"]
        concluidas = stats["concluidas"]
        hoje = stats["hoje"]
        ultima = stats["ultima_alteracao"]

        self.card_total.set_value(str(total), "Total no histórico")
        self.card_pending.set_value(
            str(pendentes),
            "Nenhuma pendência!" if pendentes == 0 else "Requerem atenção",
        )
        self.card_completed.set_value(
            str(concluidas), "Verificadas pelo usuário"
        )

        ultima_fmt = "Sem registros"
        if ultima:
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(ultima)
                ultima_fmt = f"Última: {dt.strftime('%d/%m %H:%M')}"
            except Exception:
                ultima_fmt = f"Última: {ultima}"
        self.card_recent.set_value(str(hoje), ultima_fmt)

        has_path = self.controller.has_configured_path
        connected = self.controller.is_connected
        paused = self.controller._is_paused
        self._update_connection_banner(connected, paused, has_path)
        self.tray.update_status(
            connected=connected,
            paused=paused,
            pending_count=pendentes,
            has_path=has_path,
        )

    def _update_connection_banner(
        self, connected: bool, paused: bool, has_path: bool
    ) -> None:
        if paused:
            self.lbl_monitor_state.setText("⏸ Monitoramento Pausado")
            self.lbl_monitor_state.setStyleSheet(
                """
                color: #FBBF24;
                background-color: #78350F;
                border: 1px solid #D97706;
                border-radius: 10px;
                padding: 2px 10px;
                font-size: 12px;
                font-weight: bold;
                """
            )
            self.btn_pause_resume.setText("▶ Retomar")
        else:
            self.lbl_monitor_state.setText("● Monitoramento Ativo")
            self.lbl_monitor_state.setStyleSheet(
                """
                color: #34D399;
                background-color: #064E3B;
                border: 1px solid #059669;
                border-radius: 10px;
                padding: 2px 10px;
                font-size: 12px;
                font-weight: bold;
                """
            )
            self.btn_pause_resume.setText("⏸ Pausar")

        if not has_path:
            self.lbl_conn_badge.setText("📁 Selecione uma pasta acima")
            self.lbl_conn_badge.setStyleSheet(
                """
                color: #38BDF8;
                background-color: #0C4A6E;
                border: 1px solid #0284C7;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: bold;
                """
            )
        elif connected:
            self.lbl_conn_badge.setText("✔ Pasta Conectada")
            self.lbl_conn_badge.setStyleSheet(
                """
                color: #34D399;
                background-color: #064E3B;
                border: 1px solid #059669;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: bold;
                """
            )
        else:
            self.lbl_conn_badge.setText("⚠ Pasta Indisponível — Reconectando...")
            self.lbl_conn_badge.setStyleSheet(
                """
                color: #FCA5A5;
                background-color: #7F1D1D;
                border: 1px solid #EF4444;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: bold;
                """
            )
        self.lbl_conn_badge.setToolTip(self.controller.last_status_message)

        if self.controller.last_sync_time:
            self.lbl_last_sync.setText(
                f"Última sincronização: {self.controller.last_sync_time}"
            )

    def _handle_toggle_task(self, task_id: int, completed: bool) -> None:
        self.db.set_task_completed(task_id, completed)
        self.refresh_all_ui()

    def _handle_open_task_details(self, task: TaskItem) -> None:
        fresh_task = self.db.get_task_by_id(task.task_id) or task
        dlg = TaskDetailDialog(
            task=fresh_task,
            on_save_observation=self._handle_save_observation,
            on_toggle_status=self._handle_toggle_task,
            parent=self,
        )
        dlg.exec()
        self.refresh_all_ui()

    def _handle_save_observation(self, task_id: int, obs: str) -> None:
        self.db.update_task_observation(task_id, obs)

    def mark_all_displayed_completed(self) -> None:
        ids = self.table.get_displayed_task_ids()
        if not ids:
            QMessageBox.information(
                self,
                "Nenhuma Tarefa",
                "Não há pendências listadas no filtro atual para concluir.",
            )
            return

        updated = self.db.mark_all_pending_completed(ids)
        self.refresh_all_ui()
        if updated > 0:
            QMessageBox.information(
                self,
                "Pendências Concluídas",
                f"{updated} pendência(s) foram marcadas como concluídas com sucesso.",
            )

    def delete_selected_tasks_explicit(self) -> None:
        selected_ids = self.table.get_selected_task_ids()
        if not selected_ids:
            QMessageBox.information(
                self,
                "Seleção Vazia",
                "Selecione uma ou mais linhas na tabela antes de clicar em Excluir.",
            )
            return

        ans = QMessageBox.warning(
            self,
            "Confirmar Exclusão Explícita de Histórico",
            f"Deseja excluir permanentemente {len(selected_ids)} registro(s) selecionado(s) do histórico?\n\n"
            "Nota: Os arquivos reais na pasta monitorada NÃO serão afetados.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.db.delete_tasks_explicit(selected_ids)
            self.refresh_all_ui()

    def _on_new_task_ui(self, task: TaskItem) -> None:
        self.refresh_all_ui()
        self.notifier.notify_task(task)

    def _on_connection_changed_ui(self, connected: bool, message: str) -> None:
        self.refresh_indicators_and_tray()
        if not self._initial_connection_announced:
            self._initial_connection_announced = True
            if not connected and self.controller.has_configured_path:
                self.notifier.notify_connection_status(
                    False, self.config.caminho_monitorado, message
                )
            return

        self.notifier.notify_connection_status(
            connected, self.config.caminho_monitorado, message
        )

    def _on_sync_completed_ui(
        self, timestamp_str: str, ok: bool, changes: int
    ) -> None:
        self.lbl_last_sync.setText(f"Última sincronização: {timestamp_str}")
        if changes > 0:
            self.refresh_all_ui()
        else:
            self.refresh_indicators_and_tray()

    def trigger_manual_sync(self) -> None:
        if not self.config.caminho_monitorado.strip():
            QMessageBox.information(
                self,
                "Selecione uma Pasta",
                "Escolha ou digite o caminho da pasta que deseja monitorar no topo da janela.",
            )
            return
        self.lbl_last_sync.setText("Sincronizando agora...")
        QApplication.processEvents()
        self.controller.force_sync_now()
        self.refresh_all_ui()

    def toggle_pause_monitoring(self) -> None:
        if self.controller._is_paused:
            self.controller.resume()
        else:
            self.controller.pause()
        self.refresh_indicators_and_tray()

    def open_settings_dialog(self) -> None:
        dlg = SettingsDialog(
            current_config=self.config,
            on_save_config=self._apply_new_config,
            on_test_notification=self.notifier.send_test_notification,
            parent=self,
        )
        dlg.exec()

    def _apply_new_config(self, new_cfg: AppConfig) -> None:
        self.config = new_cfg
        self.db.save_config(new_cfg)
        self.notifier.update_config(new_cfg)
        self.controller.update_config(new_cfg)
        self.refresh_all_ui()

    def bring_to_front(self) -> None:
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        self.refresh_all_ui()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._force_quit:
            event.accept()
            return

        event.ignore()
        self.hide()
        self.tray.show_notification(
            APP_NAME,
            "O Monitoramento de Pasta continua ativo em segundo plano próximo ao relógio do Windows.",
            "info",
        )

    def quit_application(self) -> None:
        self._force_quit = True
        self._ui_timer.stop()
        self.tray.hide()
        self.controller.stop()
        QApplication.quit()
