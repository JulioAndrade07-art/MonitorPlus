"""
Componente visual da Lista de Alterações e Sistema de Checklist,
incluindo diálogo de visualização de detalhes, anotação de observações e abertura
segura da localização do arquivo no Windows Explorer.
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database.models import EventType, TaskItem

logger = logging.getLogger(__name__)


def open_file_location_in_explorer(
    full_path: str, parent: Optional[QWidget] = None
) -> bool:
    """
    Abre a localização do arquivo ou pasta no Windows Explorer (selecionando o item
    sem executar/abrir o documento). Caso o arquivo tenha sido excluído, abre a
    pasta pai mais próxima se ainda existir.
    """
    if not full_path or not full_path.strip():
        if parent is not None:
            QMessageBox.information(
                parent,
                "Nenhuma pasta selecionada",
                "Selecione primeiro uma pasta para monitorar no topo da janela principal.",
            )
        return False

    norm_path = os.path.normpath(full_path)
    try:
        if os.path.exists(norm_path):
            if os.path.isfile(norm_path):
                subprocess.Popen(["explorer.exe", f"/select,{norm_path}"])
            else:
                subprocess.Popen(["explorer.exe", norm_path])
            return True

        parent_dir = os.path.dirname(norm_path)
        if parent_dir and os.path.isdir(parent_dir):
            if parent is not None:
                ans = QMessageBox.question(
                    parent,
                    "Item não encontrado",
                    f"O item '{os.path.basename(norm_path)}' não existe mais no local original.\n\n"
                    f"Deseja abrir a pasta onde ele estava localizado?\n{parent_dir}",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if ans == QMessageBox.StandardButton.Yes:
                    subprocess.Popen(["explorer.exe", parent_dir])
                    return True
            return False

        if parent is not None:
            QMessageBox.warning(
                parent,
                "Localização indisponível",
                f"O caminho não existe mais ou está inacessível no momento:\n\n{norm_path}",
            )
        return False
    except Exception as exc:
        logger.error("Erro ao abrir localização no Explorer (%s): %s", norm_path, exc)
        if parent is not None:
            QMessageBox.warning(
                parent,
                "Erro ao abrir Explorer",
                f"Não foi possível abrir o Windows Explorer:\n{exc}",
            )
        return False


def get_event_badge_style(event_type: str) -> tuple[str, str, str]:
    if event_type in (EventType.NOVO_ARQUIVO.value, EventType.NOVA_PASTA.value):
        return ("#38BDF8", "#0C4A6E", "✚")
    if event_type in (
        EventType.ARQUIVO_MODIFICADO.value,
        EventType.PASTA_MODIFICADA.value,
    ):
        return ("#FBBF24", "#78350F", "✎")
    if event_type in (
        EventType.ARQUIVO_EXCLUIDO.value,
        EventType.PASTA_EXCLUIDA.value,
    ):
        return ("#F87171", "#7F1D1D", "✖")
    if event_type in (
        EventType.ARQUIVO_RENOMEADO.value,
        EventType.PASTA_RENOMEADA.value,
    ):
        return ("#C084FC", "#4C1D95", "⇄")
    return ("#94A3B8", "#1E293B", "•")


class TaskDetailDialog(QDialog):
    def __init__(
        self,
        task: TaskItem,
        on_save_observation: Callable[[int, str], None],
        on_toggle_status: Callable[[int, bool], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.task = task
        self.on_save_observation = on_save_observation
        self.on_toggle_status = on_toggle_status

        self.setWindowTitle(
            f"Detalhes da Alteração #{task.task_id} — {task.nome_arquivo}"
        )
        self.setMinimumSize(620, 480)
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background-color: #0F172A;
                color: #F8FAFC;
            }
            QLabel {
                color: #E2E8F0;
                font-size: 13px;
            }
            QLabel#ValueLabel {
                color: #F8FAFC;
                font-weight: 600;
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 10px;
            }
            QPlainTextEdit {
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
            }
            QPushButton {
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #334155;
            }
            QPushButton#PrimaryBtn {
                background-color: #0284C7;
                border-color: #0369A1;
                color: #FFFFFF;
            }
            QPushButton#PrimaryBtn:hover {
                background-color: #0369A1;
            }
            QPushButton#SuccessBtn {
                background-color: #059669;
                border-color: #047857;
                color: #FFFFFF;
            }
            QPushButton#SuccessBtn:hover {
                background-color: #047857;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title_lbl = QLabel(
            f"{'📁 Pasta' if self.task.eh_pasta else '📄 Arquivo'}: {self.task.nome_arquivo}"
        )
        title_lbl.setStyleSheet(
            "font-size: 17px; font-weight: bold; color: #38BDF8;"
        )
        layout.addWidget(title_lbl)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        def _val_label(text: str) -> QLabel:
            lbl = QLabel(text or "-")
            lbl.setObjectName("ValueLabel")
            lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            lbl.setWordWrap(True)
            return lbl

        status_txt = (
            f"☑ CONCLUÍDA (em {self.task.data_conclusao_formatada})"
            if self.task.concluido
            else "☐ PENDENTE DE VERIFICAÇÃO"
        )
        status_lbl = _val_label(status_txt)
        if self.task.concluido:
            status_lbl.setStyleSheet(
                "color: #34D399; background-color: #064E3B; border: 1px solid #059669; border-radius: 6px; padding: 6px 10px; font-weight: bold;"
            )
        else:
            status_lbl.setStyleSheet(
                "color: #FBBF24; background-color: #78350F; border: 1px solid #D97706; border-radius: 6px; padding: 6px 10px; font-weight: bold;"
            )

        exists_now = os.path.exists(self.task.caminho_completo)
        exists_txt = (
            "Sim (Disponível no diretório)"
            if exists_now
            else "Não (Removido, renomeado ou inacessível)"
        )

        form.addRow("Status da Pendência:", status_lbl)
        form.addRow("Tipo de Evento:", _val_label(self.task.tipo_evento))
        form.addRow("Data e Horário:", _val_label(self.task.data_formatada))
        form.addRow("Caminho Relativo:", _val_label(self.task.caminho_relativo))
        form.addRow("Caminho Completo:", _val_label(self.task.caminho_completo))
        if self.task.caminho_antigo:
            form.addRow(
                "Caminho Anterior:", _val_label(self.task.caminho_antigo)
            )
        form.addRow("Tamanho:", _val_label(self.task.tamanho_formatado))
        form.addRow("Existe atualmente:", _val_label(exists_txt))
        form.addRow(
            "Hash SHA-256:", _val_label(self.task.hash or "Não aplicável")
        )
        if self.task.detalhes:
            form.addRow("Detalhes do Evento:", _val_label(self.task.detalhes))

        layout.addLayout(form)

        obs_title = QLabel("Observações / Anotações de Verificação:")
        obs_title.setStyleSheet("font-weight: 600; margin-top: 4px;")
        layout.addWidget(obs_title)

        self.obs_edit = QPlainTextEdit()
        self.obs_edit.setPlaceholderText(
            "Adicione uma observação sobre esta alteração (ex.: verificado, revisado, atualizado)..."
        )
        self.obs_edit.setPlainText(self.task.observacao or "")
        self.obs_edit.setMaximumHeight(90)
        layout.addWidget(self.obs_edit)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_open_loc = QPushButton("📂 Abrir Localização")
        btn_open_loc.clicked.connect(
            lambda: open_file_location_in_explorer(
                self.task.caminho_completo, self
            )
        )
        btn_row.addWidget(btn_open_loc)

        toggle_text = (
            "↩ Reabrir Pendência"
            if self.task.concluido
            else "✔ Marcar como Concluída"
        )
        self.btn_toggle = QPushButton(toggle_text)
        if not self.task.concluido:
            self.btn_toggle.setObjectName("SuccessBtn")
        self.btn_toggle.clicked.connect(self._handle_toggle_status)
        btn_row.addWidget(self.btn_toggle)

        btn_row.addStretch()

        btn_save = QPushButton("Salvar e Fechar")
        btn_save.setObjectName("PrimaryBtn")
        btn_save.clicked.connect(self._handle_save_and_close)
        btn_row.addWidget(btn_save)

        layout.addLayout(btn_row)

    def _handle_toggle_status(self) -> None:
        new_completed = not self.task.concluido
        self.on_save_observation(
            self.task.task_id, self.obs_edit.toPlainText().strip()
        )
        self.on_toggle_status(self.task.task_id, new_completed)
        self.accept()

    def _handle_save_and_close(self) -> None:
        self.on_save_observation(
            self.task.task_id, self.obs_edit.toPlainText().strip()
        )
        self.accept()


class TaskTableWidget(QTableWidget):
    COL_CHECK = 0
    COL_NAME = 1
    COL_EVENT = 2
    COL_REL_PATH = 3
    COL_DATE = 4
    COL_STATUS = 5
    COL_ACTIONS = 6

    def __init__(
        self,
        on_toggle_task: Callable[[int, bool], None],
        on_open_details: Callable[[TaskItem], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(0, 7, parent)
        self.on_toggle_task = on_toggle_task
        self.on_open_details = on_open_details
        self._tasks: List[TaskItem] = []

        self._setup_table()

    def _setup_table(self) -> None:
        self.setHorizontalHeaderLabels(
            [
                "Concluído",
                "Arquivo / Pasta",
                "Evento",
                "Caminho Relativo",
                "Data e Horário",
                "Status",
                "Ações",
            ]
        )

        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(self.COL_CHECK, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(self.COL_CHECK, 86)

        header.setSectionResizeMode(
            self.COL_NAME, QHeaderView.ResizeMode.Interactive
        )
        self.setColumnWidth(self.COL_NAME, 220)

        header.setSectionResizeMode(
            self.COL_EVENT, QHeaderView.ResizeMode.ResizeToContents
        )

        header.setSectionResizeMode(
            self.COL_REL_PATH, QHeaderView.ResizeMode.Stretch
        )

        header.setSectionResizeMode(
            self.COL_DATE, QHeaderView.ResizeMode.ResizeToContents
        )

        header.setSectionResizeMode(
            self.COL_STATUS, QHeaderView.ResizeMode.ResizeToContents
        )

        header.setSectionResizeMode(
            self.COL_ACTIONS, QHeaderView.ResizeMode.Fixed
        )
        self.setColumnWidth(self.COL_ACTIONS, 175)

        self.cellDoubleClicked.connect(self._on_row_double_clicked)

    def populate_tasks(self, tasks: List[TaskItem]) -> None:
        self.setUpdatesEnabled(False)
        try:
            self._tasks = list(tasks)
            self.setRowCount(len(self._tasks))

            for row_idx, task in enumerate(self._tasks):
                self.setRowHeight(row_idx, 44)
                self._populate_row(row_idx, task)
        finally:
            self.setUpdatesEnabled(True)

    def _populate_row(self, row: int, task: TaskItem) -> None:
        chk_container = QWidget()
        chk_layout = QHBoxLayout(chk_container)
        chk_layout.setContentsMargins(0, 0, 0, 0)
        chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        checkbox = QCheckBox()
        checkbox.setChecked(task.concluido)
        checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        checkbox.setToolTip(
            "Clique para desmarcar e reabrir pendência"
            if task.concluido
            else "Clique para marcar pendência como concluída"
        )
        checkbox.toggled.connect(
            lambda checked, tid=task.task_id: self.on_toggle_task(tid, checked)
        )
        chk_layout.addWidget(checkbox)
        self.setCellWidget(row, self.COL_CHECK, chk_container)

        icon_prefix = "📁 " if task.eh_pasta else "📄 "
        name_item = QTableWidgetItem(f"{icon_prefix}{task.nome_arquivo}")
        name_item.setData(Qt.ItemDataRole.UserRole, task.task_id)
        name_font = QFont()
        name_font.setBold(not task.concluido)
        if task.concluido:
            name_item.setForeground(QColor("#94A3B8"))
        else:
            name_item.setForeground(QColor("#F8FAFC"))
        name_item.setFont(name_font)
        name_item.setToolTip(task.caminho_completo)
        self.setItem(row, self.COL_NAME, name_item)

        fg_hex, bg_hex, sym = get_event_badge_style(task.tipo_evento)
        ev_container = QWidget()
        ev_layout = QHBoxLayout(ev_container)
        ev_layout.setContentsMargins(6, 4, 6, 4)
        ev_layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        ev_lbl = QLabel(f"{sym} {task.tipo_evento}")
        ev_lbl.setStyleSheet(
            f"""
            QLabel {{
                color: {fg_hex};
                background-color: {bg_hex};
                border-radius: 5px;
                padding: 3px 8px;
                font-size: 12px;
                font-weight: 600;
            }}
            """
        )
        ev_layout.addWidget(ev_lbl)
        self.setCellWidget(row, self.COL_EVENT, ev_container)

        rel_item = QTableWidgetItem(task.caminho_relativo)
        rel_item.setForeground(
            QColor("#64748B") if task.concluido else QColor("#CBD5E1")
        )
        rel_item.setToolTip(task.caminho_completo)
        self.setItem(row, self.COL_REL_PATH, rel_item)

        date_item = QTableWidgetItem(task.data_formatada)
        date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        date_item.setForeground(
            QColor("#64748B") if task.concluido else QColor("#E2E8F0")
        )
        self.setItem(row, self.COL_DATE, date_item)

        if task.concluido:
            status_str = f"✔ Concluído ({task.data_conclusao_formatada})"
            status_color = QColor("#10B981")
        else:
            status_str = "● Pendente"
            status_color = QColor("#F59E0B")
        status_item = QTableWidgetItem(status_str)
        status_item.setForeground(status_color)
        status_font = QFont()
        status_font.setBold(True)
        status_item.setFont(status_font)
        if task.observacao:
            status_item.setToolTip(f"Observação: {task.observacao}")
        self.setItem(row, self.COL_STATUS, status_item)

        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(4, 3, 4, 3)
        actions_layout.setSpacing(6)

        btn_loc = QPushButton("📂 Local")
        btn_loc.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_loc.setToolTip(
            f"Abrir localização no Windows Explorer:\n{task.caminho_completo}"
        )
        btn_loc.setStyleSheet(
            """
            QPushButton {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #475569;
            }
            """
        )
        btn_loc.clicked.connect(
            lambda _, p=task.caminho_completo: open_file_location_in_explorer(
                p, self
            )
        )

        btn_det = QPushButton("🔍 Detalhes")
        btn_det.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_det.setToolTip(
            "Visualizar metadados completos, hash e observações"
        )
        btn_det.setStyleSheet(
            """
            QPushButton {
                background-color: #0F172A;
                color: #38BDF8;
                border: 1px solid #0284C7;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #0284C7;
                color: #FFFFFF;
            }
            """
        )
        btn_det.clicked.connect(lambda _, t=task: self.on_open_details(t))

        actions_layout.addWidget(btn_loc)
        actions_layout.addWidget(btn_det)
        self.setCellWidget(row, self.COL_ACTIONS, actions_widget)

    def _on_row_double_clicked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._tasks):
            self.on_open_details(self._tasks[row])

    def get_selected_task_ids(self) -> List[int]:
        selected_rows = {idx.row() for idx in self.selectedIndexes()}
        ids: List[int] = []
        for r in sorted(selected_rows):
            if 0 <= r < len(self._tasks):
                ids.append(self._tasks[r].task_id)
        return ids

    def get_displayed_task_ids(self) -> List[int]:
        return [t.task_id for t in self._tasks]
