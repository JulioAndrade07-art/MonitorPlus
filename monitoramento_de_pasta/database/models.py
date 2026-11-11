"""
Modelos de dados para eventos de sistema de arquivos, tarefas (checklist),
snapshots de arquivos e histórico de conexão.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class EventType(str, Enum):
    """Tipos de eventos detectados no monitoramento."""

    NOVO_ARQUIVO = "Novo arquivo"
    ARQUIVO_MODIFICADO = "Arquivo modificado"
    ARQUIVO_EXCLUIDO = "Arquivo excluído"
    ARQUIVO_RENOMEADO = "Arquivo renomeado"
    NOVA_PASTA = "Nova pasta"
    PASTA_MODIFICADA = "Pasta modificada"
    PASTA_EXCLUIDA = "Pasta excluída"
    PASTA_RENOMEADA = "Pasta renomeada"

    @classmethod
    def all_values(cls) -> list[str]:
        return [item.value for item in cls]


class TaskStatus(str, Enum):
    """Status de uma pendência na lista de checklist."""

    PENDENTE = "PENDENTE"
    CONCLUIDO = "CONCLUIDO"


@dataclass
class EventRecord:
    """Representa um registro na tabela `eventos`."""

    id: Optional[int]
    caminho_completo: str
    caminho_relativo: str
    nome_arquivo: str
    tipo_evento: str
    data_evento: str  # Formato ISO: YYYY-MM-DD HH:MM:SS
    tamanho_arquivo: Optional[int] = None
    identificador_do_evento: str = ""
    hash: Optional[str] = None
    eh_pasta: bool = False
    caminho_antigo: Optional[str] = None
    detalhes: Optional[str] = None


@dataclass
class TaskItem:
    """
    Representa a combinação de uma Tarefa (`tarefas`) com seu Evento (`eventos`)
    para exibição na interface principal (Central de Pendências).
    """

    task_id: int
    event_id: int
    status: str  # 'PENDENTE' ou 'CONCLUIDO'
    data_conclusao: Optional[str]
    observacao: str
    caminho_completo: str
    caminho_relativo: str
    nome_arquivo: str
    tipo_evento: str
    data_evento: str
    tamanho_arquivo: Optional[int]
    identificador_do_evento: str
    hash: Optional[str]
    eh_pasta: bool = False
    caminho_antigo: Optional[str] = None
    detalhes: Optional[str] = None

    @property
    def concluido(self) -> bool:
        return self.status == TaskStatus.CONCLUIDO.value

    @property
    def data_formatada(self) -> str:
        """Retorna a data e hora no formato DD/MM/YYYY HH:MM:SS."""
        try:
            dt = datetime.fromisoformat(self.data_evento)
            return dt.strftime("%d/%m/%Y %H:%M:%S")
        except Exception:
            return self.data_evento

    @property
    def horario_curto(self) -> str:
        """Retorna apenas o horário HH:MM."""
        try:
            dt = datetime.fromisoformat(self.data_evento)
            return dt.strftime("%H:%M")
        except Exception:
            return self.data_evento

    @property
    def data_conclusao_formatada(self) -> str:
        if not self.data_conclusao:
            return "-"
        try:
            dt = datetime.fromisoformat(self.data_conclusao)
            return dt.strftime("%d/%m/%Y %H:%M:%S")
        except Exception:
            return self.data_conclusao

    @property
    def tamanho_formatado(self) -> str:
        if self.eh_pasta or self.tamanho_arquivo is None:
            return "-"
        size = float(self.tamanho_arquivo)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024.0 or unit == "TB":
                if unit == "B":
                    return f"{int(size)} B"
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return "-"


@dataclass
class FileSnapshot:
    """Representa os metadados conhecidos de um arquivo/pasta para detecção híbrida."""

    caminho_completo: str
    caminho_monitorado: str
    caminho_relativo: str
    nome_arquivo: str
    eh_pasta: bool
    tamanho: int
    mtime_ns: int
    ctime_ns: int = 0
    file_index: Optional[str] = None
    hash_arquivo: Optional[str] = None
    ultima_verificacao: str = ""


@dataclass
class ConnectionLog:
    """Registro de disponibilidade/desconexão do diretório monitorado."""

    id: Optional[int]
    status: str  # 'CONECTADO', 'DESCONECTADO', 'ERRO'
    caminho: str
    data_registro: str
    mensagem: str = ""
