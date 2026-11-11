"""
Configurações globais e gerenciamento de estado persistente do aplicativo
Monitoramento de Pasta (MonitorPlus).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict

APP_NAME = "Monitoramento de Pasta"
APP_SLUG = "MonitoramentoDePasta"
APP_VERSION = "1.0.0"
# Caminho inicial vazio para que o próprio usuário escolha a pasta local ou de rede no aplicativo
DEFAULT_MONITORED_PATH = ""
DEFAULT_UNC_PATH = DEFAULT_MONITORED_PATH


def get_base_dir() -> Path:
    """Retorna o diretório base onde o executável ou script principal está localizado."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_data_dir() -> Path:
    """
    Retorna o diretório de dados persistentes da aplicação.
    Prioriza a pasta local do aplicativo se tiver permissão de escrita,
    com fallback seguro para %LOCALAPPDATA%\\MonitoramentoDePasta.
    """
    env_override = os.environ.get("MONITOR_PASTA_DATA_DIR")
    if env_override:
        p = Path(env_override)
        p.mkdir(parents=True, exist_ok=True)
        return p

    base_dir = get_base_dir()
    try:
        test_dir = base_dir / "data"
        test_dir.mkdir(parents=True, exist_ok=True)
        test_file = test_dir / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return base_dir
    except Exception:
        local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        fallback = Path(local_app_data) / APP_SLUG
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


BASE_DIR = get_base_dir()
DATA_DIR = get_data_dir()
LOGS_DIR = DATA_DIR / "logs"
ASSETS_DIR = BASE_DIR / "assets"
DB_PATH = DATA_DIR / "database_monitor.db"
CONFIG_FILE_PATH = DATA_DIR / "config.json"

# Padrões de arquivos temporários de editores (Excel, Word, LibreOffice, Windows, etc.)
# que devem ser ignorados quando seguro para não poluir notificações.
TEMP_FILE_PREFIXES = (
    "~$",          # Office (Word, Excel, PowerPoint) lock files
    ".~lock.",     # LibreOffice lock files
    "~WRL",        # Word temporary save files
    "~WRD",        # Word temporary files
)

TEMP_FILE_SUFFIXES = (
    ".tmp",
    ".temp",
    ".crdownload",
    ".part",
    ".partial",
    ".bak~",
    ".swp",
    ".swo",
    ".dwl",
    ".dwl2",
)

TEMP_EXACT_NAMES = {
    "thumbs.db",
    "desktop.ini",
    ".ds_store",
}


def is_temporary_or_system_file(filename: str) -> bool:
    """
    Identifica de forma segura se um nome de arquivo pertence a um arquivo
    temporário de salvamento (ex.: Office ~$Arquivo.xlsx, .tmp, ~WRL0001.tmp)
    ou arquivo oculto de metadados do sistema operacional.
    """
    if not filename:
        return True
    name_lower = filename.lower()
    if name_lower in TEMP_EXACT_NAMES:
        return True
    for prefix in TEMP_FILE_PREFIXES:
        if name_lower.startswith(prefix.lower()):
            return True
    for suffix in TEMP_FILE_SUFFIXES:
        if name_lower.endswith(suffix.lower()):
            return True
    if len(filename) == 8 and "." not in filename:
        try:
            int(filename, 16)
            if filename.isupper() or filename.isdigit():
                return True
        except ValueError:
            pass
    return False


@dataclass
class AppConfig:
    """Representa as configurações persistentes do aplicativo."""

    caminho_monitorado: str = DEFAULT_MONITORED_PATH
    intervalo_de_verificacao: int = 15  # segundos para varredura híbrida
    iniciar_com_windows: bool = True
    abrir_ao_iniciar: bool = False  # False = inicia minimizado na bandeja
    notificacoes_ativas: bool = True
    notificar_exclusao: bool = True
    notificar_modificacao: bool = True
    notificar_criacao: bool = True
    notificar_renomeacao: bool = True
    notificar_desconexao: bool = True
    limite_historico: int = 10000
    debounce_segundos: float = 2.0
    calcular_hash_ate_mb: int = 25
    preferencias_de_interface: Dict[str, Any] = field(
        default_factory=lambda: {
            "tema": "escuro",
            "filtro_padrao": "TODAS",
            "ordenacao_desc": True,
            "largura_janela": 1120,
            "altura_janela": 740,
        }
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        if isinstance(filtered.get("preferencias_de_interface"), str):
            try:
                filtered["preferencias_de_interface"] = json.loads(
                    filtered["preferencias_de_interface"]
                )
            except Exception:
                filtered["preferencias_de_interface"] = {}
        return cls(**filtered)

    def save_to_file(self, path: Path = CONFIG_FILE_PATH) -> None:
        """Salva uma cópia das configurações em arquivo JSON local."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=4)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Não foi possível salvar config.json: %s", exc
            )

    @classmethod
    def load_from_file(cls, path: Path = CONFIG_FILE_PATH) -> "AppConfig":
        """Carrega as configurações do arquivo JSON local, ou retorna o padrão."""
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return cls.from_dict(data)
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "Falha ao ler config.json, usando padrão: %s", exc
                )
        cfg = cls()
        cfg.save_to_file(path)
        return cfg


def setup_logging(log_dir: Path = LOGS_DIR) -> Path:
    """Configura o sistema de logs rotativos do aplicativo."""
    from logging.handlers import RotatingFileHandler

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "monitoramento_pasta.log"

    root_logger = logging.getLogger()
    if root_logger.handlers:
        return log_file

    root_logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    return log_file
