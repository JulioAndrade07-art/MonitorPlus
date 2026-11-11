"""
Utilitários de leitura segura de metadados e cálculo de impressão digital (hash)
de arquivos em diretórios locais e compartilhamentos de rede.
Operação estritamente de leitura (Read-Only).
"""

from __future__ import annotations

import hashlib
import logging
import os
import stat
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

CHUNK_SIZE = 65536  # 64 KB


def normalize_path(path_str: str) -> str:
    """Normaliza o caminho preservando prefixos UNC do Windows."""
    if not path_str or not path_str.strip():
        return ""
    return os.path.normpath(path_str.strip())


def get_relative_path(full_path: str, base_monitored_path: str) -> str:
    """
    Retorna o caminho relativo amigável a partir da pasta monitorada.
    Diferencia arquivos com o mesmo nome em subpastas distintas.
    """
    norm_full = normalize_path(full_path)
    norm_base = normalize_path(base_monitored_path)
    if not norm_base:
        return norm_full.replace("\\", "/")
    try:
        rel = os.path.relpath(norm_full, norm_base)
        if rel == ".":
            return os.path.basename(norm_base) or norm_base
        return rel.replace("\\", "/")
    except ValueError:
        return norm_full.replace("\\", "/")


def format_location_display(full_path: str, base_monitored_path: str) -> str:
    """
    Formata o local no padrão amigável exibido nas notificações:
    Ex.: 'MinhaPasta/Subpasta/' ou 'MinhaPasta/'
    """
    norm_base = normalize_path(base_monitored_path)
    root_name = os.path.basename(norm_base) or "Pasta Monitorada"
    rel = get_relative_path(full_path, norm_base)
    parent_rel = os.path.dirname(rel).replace("\\", "/")
    if not parent_rel or parent_rel == ".":
        return f"{root_name}/"
    return f"{root_name}/{parent_rel}/"


def inspect_path_metadata(
    full_path: str, retries: int = 2, retry_delay: float = 0.15
) -> Optional[Tuple[bool, int, int, int, Optional[str]]]:
    """
    Inspeciona metadados de um caminho de forma estritamente somente-leitura.
    Retorna `(eh_pasta, tamanho, mtime_ns, ctime_ns, file_index)` ou `None`
    se o arquivo não existir ou estiver inacessível.
    """
    for attempt in range(retries + 1):
        try:
            st = os.stat(full_path)
            is_dir = stat.S_ISDIR(st.st_mode)
            size = 0 if is_dir else int(st.st_size)
            mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
            ctime_ns = int(getattr(st, "st_ctime_ns", int(st.st_ctime * 1e9)))
            file_index = str(st.st_ino) if getattr(st, "st_ino", 0) else None
            return is_dir, size, mtime_ns, ctime_ns, file_index
        except FileNotFoundError:
            return None
        except PermissionError:
            if attempt < retries:
                time.sleep(retry_delay)
                continue
            logger.debug("Sem permissão ou arquivo bloqueado ao ler stat: %s", full_path)
            return None
        except OSError as exc:
            if attempt < retries:
                time.sleep(retry_delay)
                continue
            logger.debug("Erro de SO ao ler metadados de %s: %s", full_path, exc)
            return None
    return None


def compute_file_hash(
    full_path: str,
    max_full_hash_mb: int = 25,
    retries: int = 2,
    retry_delay: float = 0.2,
) -> Optional[str]:
    """
    Calcula o hash SHA-256 de um arquivo de forma segura e econômica.
    """
    max_bytes = max(1, max_full_hash_mb) * 1024 * 1024

    for attempt in range(retries + 1):
        try:
            if not os.path.isfile(full_path):
                return None

            file_size = os.path.getsize(full_path)
            hasher = hashlib.sha256()

            with open(full_path, "rb") as f:
                if file_size <= max_bytes:
                    while True:
                        chunk = f.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        hasher.update(chunk)
                else:
                    hasher.update(f"SIZE:{file_size}:".encode("utf-8"))
                    head = f.read(CHUNK_SIZE)
                    hasher.update(head)

                    mid_pos = max(0, (file_size // 2) - (CHUNK_SIZE // 2))
                    f.seek(mid_pos)
                    hasher.update(f.read(CHUNK_SIZE))

                    tail_pos = max(0, file_size - CHUNK_SIZE)
                    f.seek(tail_pos)
                    hasher.update(f.read(CHUNK_SIZE))

            return hasher.hexdigest()

        except FileNotFoundError:
            return None
        except (PermissionError, OSError) as exc:
            if attempt < retries:
                time.sleep(retry_delay * (attempt + 1))
                continue
            logger.debug(
                "Não foi possível calcular hash (arquivo em uso/bloqueado) %s: %s",
                full_path,
                exc,
            )
            return None
    return None
