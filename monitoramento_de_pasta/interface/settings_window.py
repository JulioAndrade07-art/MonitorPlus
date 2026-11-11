"""
Janela de Configurações do Monitoramento de Pasta.
Permite configurar o caminho local ou de rede monitorado, intervalos de varredura e debounce,
preferências de notificações, inicialização automática no Windows e testes de diagnóstico.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config import APP_NAME, AppConfig
from monitor.network_scanner import NetworkScanner
from startup.windows_startup import WindowsStartupManager


class SettingsDialog(QDialog):
    """
    Diálogo modal de configurações com seleção de diretório,
    teste imediato de conexão e teste imediato de notificação.
    """

    def __init__(
        self,
        current_config: AppConfig,
        on_save_config: Callable[[AppConfig], None],
        on_test_notification: Callable[[], bool],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.config = AppConfig.from_dict(current_config.to_dict())
        self.on_save_config = on_save_config
        self.on_test_notification = on_test_notification

        self.setWindowTitle(f"Configurações — {APP_NAME}")
        self.setMinimumWidth(650)
        self._setup_ui()
        self._load_values()

    def _setup_ui(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background-color: #0F172A;
                color: #F8FAFC;
            }
            QGroupBox {
                font-weight: bold;
                color: #38BDF8;
                border: 1px solid #334155;
                border-radius: 8px;
                margin-top: 12px;
                padding: 14px 12px 12px 12px;
                background-color: #1E293B;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QLabel {
                color: #E2E8F0;
                font-size: 13px;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox {
                background-color: #0F172A;
                color: #F8FAFC;
                border: 1px solid #475569;
                border-radius: 5px;
                padding: 6px 10px;
                font-size: 13px;
            }
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                border-color: #38BDF8;
            }
            QCheckBox {
                color: #E2E8F0;
                font-size: 13px;
                spacing: 8px;
            }
            QPushButton {
                background-color: #0F172A;
                color: #F8FAFC;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 7px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #334155;
            }
            QPushButton#SaveBtn {
                background-color: #0284C7;
                border-color: #0369A1;
                color: #FFFFFF;
                padding: 8px 20px;
            }
            QPushButton#SaveBtn:hover {
                background-color: #0369A1;
            }
            """
        )

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(20, 18, 20, 18)
        root_layout.setSpacing(14)

        # 1. Grupo de Diretório e Varredura
        grp_path = QGroupBox("Diretório Monitorado e Varredura Híbrida")
        path_layout = QVBoxLayout(grp_path)
        path_layout.setSpacing(10)

        lbl_path = QLabel("Local que deseja monitorar (Pasta Local ou Caminho de Rede UNC):")
        path_layout.addWidget(lbl_path)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(
            r"Ex.: C:\Documentos\Projetos ou \\SERVIDOR\Compartilhamento\Pasta"
        )
        path_row.addWidget(self.path_edit, stretch=1)

        btn_browse = QPushButton("📂 Procurar Pasta...")
        btn_browse.clicked.connect(self._browse_folder)
        path_row.addWidget(btn_browse)

        btn_clear_path = QPushButton("✖ Limpar")
        btn_clear_path.setToolTip("Limpar o caminho configurado")
        btn_clear_path.clicked.connect(lambda: self.path_edit.clear())
        path_row.addWidget(btn_clear_path)
        path_layout.addLayout(path_row)

        form_scan = QFormLayout()
        form_scan.setSpacing(10)

        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(5, 3600)
        self.spin_interval.setSuffix(" segundos")
        self.spin_interval.setToolTip(
            "Intervalo da verificação periódica complementar de segurança."
        )
        form_scan.addRow("Intervalo da verificação periódica:", self.spin_interval)

        self.spin_debounce = QDoubleSpinBox()
        self.spin_debounce.setRange(0.5, 30.0)
        self.spin_debounce.setSingleStep(0.5)
        self.spin_debounce.setSuffix(" segundos")
        self.spin_debounce.setToolTip(
            "Consolida salvamentos repetidos de um mesmo arquivo dentro desta janela em uma única notificação."
        )
        form_scan.addRow("Janela de consolidação (Debounce):", self.spin_debounce)

        self.spin_history_limit = QSpinBox()
        self.spin_history_limit.setRange(100, 100000)
        self.spin_history_limit.setSingleStep(500)
        self.spin_history_limit.setSuffix(" registros")
        form_scan.addRow("Limite de exibição no histórico:", self.spin_history_limit)

        path_layout.addLayout(form_scan)
        root_layout.addWidget(grp_path)

        # 2. Grupo de Notificações
        grp_notif = QGroupBox("Notificações na Área de Trabalho")
        notif_layout = QVBoxLayout(grp_notif)
        notif_layout.setSpacing(8)

        self.chk_notif_active = QCheckBox(
            "Ativar notificações na área de trabalho do Windows"
        )
        self.chk_notif_create = QCheckBox(
            "Exibir notificações de novos arquivos e pastas"
        )
        self.chk_notif_modify = QCheckBox(
            "Exibir notificações de modificações em arquivos"
        )
        self.chk_notif_rename = QCheckBox(
            "Exibir notificações de arquivos e pastas renomeados"
        )
        self.chk_notif_delete = QCheckBox(
            "Exibir notificações de exclusão de arquivos e pastas"
        )
        self.chk_notif_disconnect = QCheckBox(
            "Exibir alerta quando a pasta ou servidor ficar indisponível"
        )

        self.chk_notif_active.toggled.connect(self._update_notif_subcontrols)

        notif_layout.addWidget(self.chk_notif_active)
        notif_layout.addWidget(self.chk_notif_create)
        notif_layout.addWidget(self.chk_notif_modify)
        notif_layout.addWidget(self.chk_notif_rename)
        notif_layout.addWidget(self.chk_notif_delete)
        notif_layout.addWidget(self.chk_notif_disconnect)
        root_layout.addWidget(grp_notif)

        # 3. Grupo de Inicialização com o Windows
        grp_startup = QGroupBox("Inicialização e Execução em Segundo Plano")
        startup_layout = QVBoxLayout(grp_startup)
        startup_layout.setSpacing(8)

        self.chk_start_windows = QCheckBox(
            "Iniciar aplicativo automaticamente junto com o Windows"
        )
        self.chk_open_on_start = QCheckBox(
            "Abrir janela principal ao iniciar o Windows (se desmarcado, inicia minimizado na bandeja)"
        )

        startup_layout.addWidget(self.chk_start_windows)
        startup_layout.addWidget(self.chk_open_on_start)
        root_layout.addWidget(grp_startup)

        # 4. Botões de Diagnóstico
        diag_row = QHBoxLayout()
        diag_row.setSpacing(10)

        btn_test_conn = QPushButton("🔌 Testar Acesso à Pasta")
        btn_test_conn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_test_conn.clicked.connect(self._handle_test_connection)
        diag_row.addWidget(btn_test_conn)

        btn_test_notif = QPushButton("🔔 Testar Notificação")
        btn_test_notif.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_test_notif.clicked.connect(self._handle_test_notification)
        diag_row.addWidget(btn_test_notif)

        diag_row.addStretch()
        root_layout.addLayout(diag_row)

        # 5. Rodapé Salvar / Cancelar
        footer_row = QHBoxLayout()
        footer_row.addStretch()

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)
        footer_row.addWidget(btn_cancel)

        btn_save = QPushButton("✔ Salvar Configurações")
        btn_save.setObjectName("SaveBtn")
        btn_save.clicked.connect(self._handle_save)
        footer_row.addWidget(btn_save)

        root_layout.addLayout(footer_row)

    def _load_values(self) -> None:
        self.path_edit.setText(self.config.caminho_monitorado)
        self.spin_interval.setValue(int(self.config.intervalo_de_verificacao))
        self.spin_debounce.setValue(float(self.config.debounce_segundos))
        self.spin_history_limit.setValue(int(self.config.limite_historico))

        self.chk_notif_active.setChecked(bool(self.config.notificacoes_ativas))
        self.chk_notif_create.setChecked(bool(self.config.notificar_criacao))
        self.chk_notif_modify.setChecked(bool(self.config.notificar_modificacao))
        self.chk_notif_rename.setChecked(bool(self.config.notificar_renomeacao))
        self.chk_notif_delete.setChecked(bool(self.config.notificar_exclusao))
        self.chk_notif_disconnect.setChecked(
            bool(self.config.notificar_desconexao)
        )
        self._update_notif_subcontrols(bool(self.config.notificacoes_ativas))

        self.chk_start_windows.setChecked(bool(self.config.iniciar_com_windows))
        self.chk_open_on_start.setChecked(bool(self.config.abrir_ao_iniciar))

    def _update_notif_subcontrols(self, active: bool) -> None:
        for chk in (
            self.chk_notif_create,
            self.chk_notif_modify,
            self.chk_notif_rename,
            self.chk_notif_delete,
            self.chk_notif_disconnect,
        ):
            chk.setEnabled(active)

    def _browse_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Selecionar Diretório para Monitoramento",
            self.path_edit.text().strip() or "",
        )
        if selected:
            self.path_edit.setText(selected.replace("/", "\\"))

    def _handle_test_connection(self) -> None:
        candidate = self.path_edit.text().strip()
        if not candidate:
            QMessageBox.information(
                self,
                "Caminho Vazio",
                "Digite ou selecione uma pasta antes de testar o acesso.",
            )
            return
        ok, msg = NetworkScanner.check_share_available(candidate)
        if ok:
            QMessageBox.information(
                self,
                "Pasta Acessível",
                f"O diretório está disponível e acessível para leitura!\n\n"
                f"Caminho: {candidate}\n"
                f"Status: {msg}",
            )
        else:
            QMessageBox.warning(
                self,
                "Falha no Acesso",
                f"Não foi possível acessar o diretório no momento:\n\n"
                f"Caminho: {candidate}\n"
                f"Detalhe: {msg}\n\n"
                f"Nota: Se você salvar este caminho, o aplicativo tentará se conectar automaticamente assim que a pasta ficar disponível.",
            )

    def _handle_test_notification(self) -> None:
        sent = self.on_test_notification()
        if sent:
            QMessageBox.information(
                self,
                "Notificação Enviada",
                "Uma notificação de teste foi enviada para a área de trabalho do Windows.",
            )
        else:
            QMessageBox.warning(
                self,
                "Falha ao Notificar",
                "Não foi possível exibir a notificação de teste. Verifique as permissões de notificação do Windows.",
            )

    def _handle_save(self) -> None:
        path_val = self.path_edit.text().strip()

        self.config.caminho_monitorado = path_val
        self.config.intervalo_de_verificacao = int(self.spin_interval.value())
        self.config.debounce_segundos = float(self.spin_debounce.value())
        self.config.limite_historico = int(self.spin_history_limit.value())

        self.config.notificacoes_ativas = self.chk_notif_active.isChecked()
        self.config.notificar_criacao = self.chk_notif_create.isChecked()
        self.config.notificar_modificacao = self.chk_notif_modify.isChecked()
        self.config.notificar_renomeacao = self.chk_notif_rename.isChecked()
        self.config.notificar_exclusao = self.chk_notif_delete.isChecked()
        self.config.notificar_desconexao = self.chk_notif_disconnect.isChecked()

        self.config.iniciar_com_windows = self.chk_start_windows.isChecked()
        self.config.abrir_ao_iniciar = self.chk_open_on_start.isChecked()

        WindowsStartupManager.set_enabled(self.config.iniciar_com_windows)

        self.on_save_config(self.config)
        self.accept()
