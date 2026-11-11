"""
Monitoramento em tempo real baseado em eventos do sistema operacional (Watchdog).
Monitora recursivamente a pasta principal e todas as subpastas existentes ou criadas futuramente.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirModifiedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from config import is_temporary_or_system_file
from database.models import EventType
from monitor.event_processor import EventProcessor
from monitor.file_fingerprint import normalize_path

logger = logging.getLogger(__name__)


class FolderEventHandler(FileSystemEventHandler):
    """
    Manipulador de eventos do Watchdog que traduz eventos brutos do sistema operacional
    para o `EventProcessor` com debounce e filtragem de arquivos temporários.
    """

    def __init__(
        self,
        processor: EventProcessor,
        monitored_root: str,
    ) -> None:
        super().__init__()
        self.processor = processor
        self.monitored_root = normalize_path(monitored_root)

    def _is_root_dir(self, path_str: str) -> bool:
        return normalize_path(path_str).lower() == self.monitored_root.lower()

    def on_created(self, event: FileSystemEvent) -> None:
        src = normalize_path(os.fsdecode(event.src_path))
        if self._is_root_dir(src):
            return
        if is_temporary_or_system_file(os.path.basename(src)):
            return

        if isinstance(event, DirCreatedEvent) or event.is_directory:
            self.processor.submit_event(
                event_type=EventType.NOVA_PASTA,
                full_path=src,
                is_dir=True,
                details="Novo diretório criado",
            )
        elif isinstance(event, FileCreatedEvent) or not event.is_directory:
            self.processor.submit_event(
                event_type=EventType.NOVO_ARQUIVO,
                full_path=src,
                is_dir=False,
                details="Novo arquivo detectado em tempo real",
            )

    def on_modified(self, event: FileSystemEvent) -> None:
        src = normalize_path(os.fsdecode(event.src_path))
        if self._is_root_dir(src):
            return
        if is_temporary_or_system_file(os.path.basename(src)):
            return

        if isinstance(event, DirModifiedEvent) or event.is_directory:
            return

        if isinstance(event, FileModifiedEvent) or not event.is_directory:
            self.processor.submit_event(
                event_type=EventType.ARQUIVO_MODIFICADO,
                full_path=src,
                is_dir=False,
                details="Conteúdo do arquivo modificado",
            )

    def on_deleted(self, event: FileSystemEvent) -> None:
        src = normalize_path(os.fsdecode(event.src_path))
        if self._is_root_dir(src):
            return
        if is_temporary_or_system_file(os.path.basename(src)):
            return

        if isinstance(event, DirDeletedEvent) or event.is_directory:
            self.processor.submit_event(
                event_type=EventType.PASTA_EXCLUIDA,
                full_path=src,
                is_dir=True,
                details="Diretório removido",
            )
        elif isinstance(event, FileDeletedEvent) or not event.is_directory:
            self.processor.submit_event(
                event_type=EventType.ARQUIVO_EXCLUIDO,
                full_path=src,
                is_dir=False,
                details="Arquivo removido",
            )

    def on_moved(self, event: FileSystemEvent) -> None:
        src = normalize_path(os.fsdecode(event.src_path))
        dest = normalize_path(os.fsdecode(getattr(event, "dest_path", "")))
        if not dest:
            return

        old_name = os.path.basename(src)
        new_name = os.path.basename(dest)

        if isinstance(event, DirMovedEvent) or event.is_directory:
            if is_temporary_or_system_file(new_name):
                return
            self.processor.submit_event(
                event_type=EventType.PASTA_RENOMEADA,
                full_path=dest,
                is_dir=True,
                old_path=src,
                details=f"Pasta renomeada de '{old_name}' para '{new_name}'",
            )
        elif isinstance(event, FileMovedEvent) or not event.is_directory:
            self.processor.submit_event(
                event_type=EventType.ARQUIVO_RENOMEADO,
                full_path=dest,
                is_dir=False,
                old_path=src,
                details=f"Arquivo renomeado de '{old_name}' para '{new_name}'",
            )


class WatchdogMonitor:
    """
    Gerencia o ciclo de vida do Observer do Watchdog sobre o diretório monitorado.
    Suporta reconexão segura quando o diretório ou compartilhamento retorna.
    """

    def __init__(self, processor: EventProcessor) -> None:
        self.processor = processor
        self._observer: Optional[Observer] = None
        self._watched_path: Optional[str] = None
        self._lock = threading.RLock()
        self._using_polling_fallback = False

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._observer is not None and self._observer.is_alive()

    def start(self, path: str) -> bool:
        norm_path = normalize_path(path)
        with self._lock:
            self.stop()
            if not norm_path or not os.path.isdir(norm_path):
                logger.warning(
                    "Watchdog não pôde iniciar: caminho inacessível (%s)",
                    norm_path,
                )
                return False

            handler = FolderEventHandler(
                processor=self.processor,
                monitored_root=norm_path,
            )

            try:
                observer = Observer(timeout=0.15)
                observer.daemon = True
                observer.schedule(handler, norm_path, recursive=True)
                observer.start()
                self._observer = observer
                self._watched_path = norm_path
                self._using_polling_fallback = False
                logger.info(
                    "Watchdog Observer nativo iniciado recursivamente em: %s",
                    norm_path,
                )
                return True
            except Exception as exc:
                logger.warning(
                    "Observer nativo falhou em %s (%s). Ativando PollingObserver.",
                    norm_path,
                    exc,
                )
                try:
                    polling_obs = PollingObserver(timeout=10)
                    polling_obs.daemon = True
                    polling_obs.schedule(handler, norm_path, recursive=True)
                    polling_obs.start()
                    self._observer = polling_obs
                    self._watched_path = norm_path
                    self._using_polling_fallback = True
                    logger.info(
                        "Watchdog PollingObserver iniciado em: %s", norm_path
                    )
                    return True
                except Exception as poll_exc:
                    logger.error(
                        "Falha ao iniciar PollingObserver em %s: %s",
                        norm_path,
                        poll_exc,
                    )
                    self._observer = None
                    return False

    def stop(self) -> None:
        with self._lock:
            obs = self._observer
            self._observer = None
            self._watched_path = None
            if obs is not None:
                try:
                    obs.stop()
                    obs.join(timeout=2.0)
                except Exception as exc:
                    logger.debug("Aviso ao parar Watchdog Observer: %s", exc)
