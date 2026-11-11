"""
Processador central de eventos de sistema de arquivos com suporte a:
- Debounce e consolidação de eventos próximos (ex.: múltiplas gravações ao salvar).
- Filtragem segura de arquivos temporários (~$, .tmp, lock files).
- Deduplicação por caminho completo + tipo de evento + impressão digital (hash/mtime).
- Diferenciação de arquivos homônimos em subpastas distintas.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from config import AppConfig, is_temporary_or_system_file
from database.database import DatabaseManager
from database.models import EventRecord, EventType, FileSnapshot, TaskItem
from monitor.file_fingerprint import (
    compute_file_hash,
    get_relative_path,
    inspect_path_metadata,
    normalize_path,
)

logger = logging.getLogger(__name__)


@dataclass
class PendingRawEvent:
    """Representa um evento em janela de debounce aguardando consolidação."""

    full_path: str
    event_type: EventType
    is_dir: bool
    first_seen: float
    last_updated: float
    old_path: Optional[str] = None
    details: Optional[str] = None
    hit_count: int = 1
    initial_hash: Optional[str] = None
    initial_size: Optional[int] = None


class EventProcessor:
    """
    Recebe eventos brutos do Watchdog ou do NetworkScanner, aplica debounce,
    filtra arquivos temporários, calcula metadados/hash e registra no banco SQLite
    disparando callbacks para a interface e notificações.
    """

    def __init__(
        self,
        db: DatabaseManager,
        config: AppConfig,
        on_new_task_callback: Optional[Callable[[TaskItem], None]] = None,
    ) -> None:
        self.db = db
        self.config = config
        self.on_new_task_callback = on_new_task_callback

        self._lock = threading.RLock()
        self._pending: Dict[Tuple[str, str], PendingRawEvent] = {}
        self._recent_emitted: Dict[
            str, Tuple[str, Optional[int], Optional[int], Optional[str], float]
        ] = {}

        self._stop_event = threading.Event()
        self._worker_thread = threading.Thread(
            target=self._flush_loop,
            name="EventProcessorDebounceThread",
            daemon=True,
        )
        self._worker_thread.start()

    def update_config(self, new_config: AppConfig) -> None:
        with self._lock:
            self.config = new_config

    def stop(self) -> None:
        self._stop_event.set()
        self.flush_all(force=True)
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)

    @staticmethod
    def _should_ignore_path(full_path: str) -> bool:
        if not full_path:
            return True
        name = os.path.basename(normalize_path(full_path))
        return is_temporary_or_system_file(name)

    def submit_event(
        self,
        event_type: EventType,
        full_path: str,
        is_dir: bool = False,
        old_path: Optional[str] = None,
        details: Optional[str] = None,
        immediate: bool = False,
    ) -> Optional[TaskItem]:
        norm_full = normalize_path(full_path)
        norm_old = normalize_path(old_path) if old_path else None

        if event_type in (EventType.ARQUIVO_RENOMEADO, EventType.PASTA_RENOMEADA):
            old_is_temp = self._should_ignore_path(norm_old) if norm_old else False
            new_is_temp = self._should_ignore_path(norm_full)
            if new_is_temp:
                return None
            if old_is_temp and not new_is_temp:
                event_type = EventType.ARQUIVO_MODIFICADO
                norm_old = None
        else:
            if self._should_ignore_path(norm_full):
                return None

        now = time.monotonic()

        with self._lock:
            if immediate:
                raw = PendingRawEvent(
                    full_path=norm_full,
                    event_type=event_type,
                    is_dir=is_dir,
                    first_seen=now,
                    last_updated=now,
                    old_path=norm_old,
                    details=details,
                )
                return self._finalize_pending_event(raw)

            if norm_old and event_type in (
                EventType.ARQUIVO_RENOMEADO,
                EventType.PASTA_RENOMEADA,
            ):
                self._flush_path_locked(norm_old)

            self._coalesce_event_locked(
                norm_full=norm_full,
                event_type=event_type,
                is_dir=is_dir,
                norm_old=norm_old,
                details=details,
                now=now,
            )
        return None

    def _coalesce_event_locked(
        self,
        norm_full: str,
        event_type: EventType,
        is_dir: bool,
        norm_old: Optional[str],
        details: Optional[str],
        now: float,
    ) -> None:
        key_create = (norm_full, "CREATE")
        key_modify = (norm_full, "MODIFY")
        key_delete = (norm_full, "DELETE")
        key_rename = (norm_full, "RENAME")

        if event_type in (EventType.NOVO_ARQUIVO, EventType.NOVA_PASTA):
            if key_delete in self._pending:
                del self._pending[key_delete]
                mod_type = (
                    EventType.PASTA_MODIFICADA
                    if is_dir
                    else EventType.ARQUIVO_MODIFICADO
                )
                self._pending[key_modify] = PendingRawEvent(
                    full_path=norm_full,
                    event_type=mod_type,
                    is_dir=is_dir,
                    first_seen=now,
                    last_updated=now,
                    details="Arquivo recriado/atualizado durante salvamento",
                )
                return

            if key_create in self._pending:
                existing = self._pending[key_create]
                existing.last_updated = now
                existing.hit_count += 1
                return

            meta = inspect_path_metadata(norm_full, retries=1)
            init_size = meta[1] if meta else None
            init_hash = (
                compute_file_hash(
                    norm_full, self.config.calcular_hash_ate_mb, retries=1
                )
                if (meta and not is_dir)
                else None
            )
            self._pending[key_create] = PendingRawEvent(
                full_path=norm_full,
                event_type=event_type,
                is_dir=is_dir,
                first_seen=now,
                last_updated=now,
                details=details,
                initial_hash=init_hash,
                initial_size=init_size,
            )

        elif event_type in (
            EventType.ARQUIVO_MODIFICADO,
            EventType.PASTA_MODIFICADA,
        ):
            if key_create in self._pending:
                created_ev = self._pending[key_create]
                if (now - created_ev.first_seen) <= 0.30:
                    created_ev.last_updated = now
                    created_ev.hit_count += 1
                    return
                else:
                    curr_hash = (
                        compute_file_hash(
                            norm_full, self.config.calcular_hash_ate_mb, retries=1
                        )
                        if not is_dir
                        else None
                    )
                    if (
                        curr_hash
                        and created_ev.initial_hash
                        and curr_hash == created_ev.initial_hash
                    ):
                        created_ev.last_updated = now
                        return
                    del self._pending[key_create]
                    self._finalize_pending_event(created_ev)

            if key_modify in self._pending:
                existing = self._pending[key_modify]
                existing.last_updated = now
                existing.hit_count += 1
                if details:
                    existing.details = details
                return

            self._pending[key_modify] = PendingRawEvent(
                full_path=norm_full,
                event_type=event_type,
                is_dir=is_dir,
                first_seen=now,
                last_updated=now,
                details=details,
            )

        elif event_type in (
            EventType.ARQUIVO_EXCLUIDO,
            EventType.PASTA_EXCLUIDA,
        ):
            self._flush_path_locked(norm_full)
            self._pending[key_delete] = PendingRawEvent(
                full_path=norm_full,
                event_type=event_type,
                is_dir=is_dir,
                first_seen=now,
                last_updated=now,
                details=details,
            )

        elif event_type in (
            EventType.ARQUIVO_RENOMEADO,
            EventType.PASTA_RENOMEADA,
        ):
            self._flush_path_locked(norm_full)
            self._pending[key_rename] = PendingRawEvent(
                full_path=norm_full,
                event_type=event_type,
                is_dir=is_dir,
                first_seen=now,
                last_updated=now,
                old_path=norm_old,
                details=details,
            )

    def _flush_path_locked(self, norm_full: str) -> None:
        keys_to_flush = [k for k in self._pending if k[0] == norm_full]
        keys_to_flush.sort(key=lambda k: self._pending[k].first_seen)
        for k in keys_to_flush:
            ev = self._pending.pop(k)
            self._finalize_pending_event(ev)

    def flush_all(self, force: bool = False) -> List[TaskItem]:
        ready: List[PendingRawEvent] = []
        now = time.monotonic()
        debounce_sec = max(0.2, float(self.config.debounce_segundos))
        max_wait_sec = max(debounce_sec * 2.0, 3.5)

        with self._lock:
            for key, ev in list(self._pending.items()):
                idle_time = now - ev.last_updated
                total_wait = now - ev.first_seen
                effective_debounce = (
                    debounce_sec
                    if ev.event_type
                    in (EventType.ARQUIVO_MODIFICADO, EventType.PASTA_MODIFICADA)
                    else min(debounce_sec, 0.5)
                )
                if (
                    force
                    or idle_time >= effective_debounce
                    or total_wait >= max_wait_sec
                ):
                    ready.append(self._pending.pop(key))

        ready.sort(key=lambda e: e.first_seen)
        created_tasks: List[TaskItem] = []
        for ev in ready:
            task = self._finalize_pending_event(ev)
            if task:
                created_tasks.append(task)
        return created_tasks

    def _flush_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.flush_all(force=False)
            except Exception as exc:
                logger.error(
                    "Erro no loop de debounce do EventProcessor: %s", exc
                )
            self._stop_event.wait(0.25)

    def _finalize_pending_event(
        self, raw: PendingRawEvent
    ) -> Optional[TaskItem]:
        base_path = self.config.caminho_monitorado
        norm_full = normalize_path(raw.full_path)
        rel_path = get_relative_path(norm_full, base_path)
        filename = os.path.basename(norm_full) or norm_full
        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        now_mono = time.monotonic()

        size: Optional[int] = None
        mtime_ns: Optional[int] = None
        ctime_ns: Optional[int] = None
        file_index: Optional[str] = None
        file_hash: Optional[str] = None
        is_dir = raw.is_dir

        if raw.event_type not in (
            EventType.ARQUIVO_EXCLUIDO,
            EventType.PASTA_EXCLUIDA,
        ):
            meta = inspect_path_metadata(norm_full)
            if meta is not None:
                is_dir, size, mtime_ns, ctime_ns, file_index = meta
                if not is_dir:
                    file_hash = compute_file_hash(
                        norm_full,
                        max_full_hash_mb=self.config.calcular_hash_ate_mb,
                    )
            else:
                size = raw.initial_size
                file_hash = raw.initial_hash

        with self._lock:
            prev = self._recent_emitted.get(norm_full)
            dedup_window = max(2.0, float(self.config.debounce_segundos) * 1.5)
            if prev is not None:
                prev_type, prev_size, prev_mtime, prev_hash, prev_mono = prev
                if (
                    prev_type == raw.event_type.value
                    and (now_mono - prev_mono) < dedup_window
                ):
                    if file_hash and prev_hash and file_hash == prev_hash:
                        return None
                    if (
                        not file_hash
                        and mtime_ns is not None
                        and prev_mtime == mtime_ns
                        and prev_size == size
                    ):
                        return None

            self._recent_emitted[norm_full] = (
                raw.event_type.value,
                size,
                mtime_ns,
                file_hash,
                now_mono,
            )

        details_parts: List[str] = []
        if raw.details:
            details_parts.append(raw.details)
        if raw.old_path:
            old_rel = get_relative_path(raw.old_path, base_path)
            details_parts.append(f"Anterior: {old_rel}")
        if raw.hit_count > 1:
            details_parts.append(
                f"Consolidado ({raw.hit_count} gravações agrupadas)"
            )
        details_str = " | ".join(details_parts) if details_parts else None

        bucket = int(
            now_dt.timestamp() // max(1, int(self.config.debounce_segundos))
        )
        raw_id_source = f"{norm_full}|{raw.event_type.value}|{file_hash or mtime_ns or bucket}|{raw.old_path or ''}"
        event_uid = hashlib.sha256(raw_id_source.encode("utf-8")).hexdigest()[
            :32
        ]

        record = EventRecord(
            id=None,
            caminho_completo=norm_full,
            caminho_relativo=rel_path,
            nome_arquivo=filename,
            tipo_evento=raw.event_type.value,
            data_evento=now_str,
            tamanho_arquivo=size,
            identificador_do_evento=event_uid,
            hash=file_hash,
            eh_pasta=is_dir,
            caminho_antigo=raw.old_path,
            detalhes=details_str,
        )

        try:
            norm_base = normalize_path(base_path)
            if norm_base:
                if raw.event_type in (
                    EventType.ARQUIVO_EXCLUIDO,
                    EventType.PASTA_EXCLUIDA,
                ):
                    self.db.save_snapshots_delta([], [norm_full])
                else:
                    snap = FileSnapshot(
                        caminho_completo=norm_full,
                        caminho_monitorado=norm_base,
                        caminho_relativo=rel_path,
                        nome_arquivo=filename,
                        eh_pasta=is_dir,
                        tamanho=size or 0,
                        mtime_ns=mtime_ns or int(now_dt.timestamp() * 1e9),
                        ctime_ns=ctime_ns or int(now_dt.timestamp() * 1e9),
                        file_index=file_index,
                        hash_arquivo=file_hash,
                        ultima_verificacao=now_str,
                    )
                    deletes = (
                        [normalize_path(raw.old_path)] if raw.old_path else []
                    )
                    self.db.save_snapshots_delta([snap], deletes)
        except Exception as exc:
            logger.debug("Falha ao sincronizar snapshot após evento: %s", exc)

        task_item = self.db.register_event_and_task(
            record,
            dedup_window_seconds=float(self.config.debounce_segundos),
        )
        if task_item and self.on_new_task_callback:
            try:
                self.on_new_task_callback(task_item)
            except Exception as exc:
                logger.error("Erro no callback de nova tarefa: %s", exc)

        return task_item
