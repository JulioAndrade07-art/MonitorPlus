"""
Varredura periódica inteligente de diretórios locais e de rede (NetworkScanner)
e controlador híbrido (HybridMonitorController) combinando eventos em tempo real
(Watchdog) com verificação periódica resiliente a quedas de conexão.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set, Tuple

from config import AppConfig, is_temporary_or_system_file
from database.database import DatabaseManager
from database.models import EventType, FileSnapshot
from monitor.event_processor import EventProcessor
from monitor.file_fingerprint import (
    compute_file_hash,
    get_relative_path,
    normalize_path,
)
from monitor.watchdog_monitor import WatchdogMonitor

logger = logging.getLogger(__name__)


class NetworkScanner:
    """
    Realiza varreduras recursivas otimizadas via `os.scandir` e compara com o
    snapshot persistido no SQLite para detectar criações, modificações,
    renomeações e exclusões.
    """

    def __init__(
        self,
        db: DatabaseManager,
        processor: EventProcessor,
        config: AppConfig,
    ) -> None:
        self.db = db
        self.processor = processor
        self.config = config
        self._scan_lock = threading.RLock()

    def update_config(self, new_config: AppConfig) -> None:
        self.config = new_config

    @staticmethod
    def check_share_available(path: str) -> Tuple[bool, str]:
        """
        Verifica se o caminho local ou de rede está acessível para leitura.
        Retorna `(disponivel: bool, mensagem: str)`.
        """
        norm_path = normalize_path(path)
        if not norm_path:
            return (
                False,
                "Nenhuma pasta selecionada. Escolha o diretório que deseja monitorar.",
            )
        try:
            if not os.path.exists(norm_path):
                return (
                    False,
                    f"Caminho indisponível ou inexistente: {norm_path}",
                )
            if not os.path.isdir(norm_path):
                return (
                    False,
                    f"O caminho informado não é um diretório: {norm_path}",
                )
            with os.scandir(norm_path) as it:
                next(it, None)
            return True, "Conectado e acessível para leitura."
        except PermissionError as exc:
            return False, f"Sem permissão de leitura no diretório: {exc}"
        except OSError as exc:
            return False, f"Diretório ou compartilhamento inacessível: {exc}"
        except Exception as exc:
            return False, f"Erro ao verificar diretório: {exc}"

    def collect_current_tree(
        self, root_path: str
    ) -> Optional[Dict[str, FileSnapshot]]:
        norm_root = normalize_path(root_path)
        available, _ = self.check_share_available(norm_root)
        if not available:
            return None

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_map: Dict[str, FileSnapshot] = {}

        def _walk_dir(current_dir: str) -> None:
            try:
                with os.scandir(current_dir) as entries:
                    for entry in entries:
                        try:
                            name = entry.name
                            if is_temporary_or_system_file(name):
                                continue
                            full_p = normalize_path(entry.path)
                            is_dir = entry.is_dir(follow_symlinks=False)
                            st = entry.stat(follow_symlinks=False)
                            size = 0 if is_dir else int(st.st_size)
                            mtime_ns = int(
                                getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
                            )
                            ctime_ns = int(
                                getattr(st, "st_ctime_ns", int(st.st_ctime * 1e9))
                            )
                            file_index = (
                                str(st.st_ino)
                                if getattr(st, "st_ino", 0)
                                else None
                            )
                            rel_p = get_relative_path(full_p, norm_root)

                            current_map[full_p] = FileSnapshot(
                                caminho_completo=full_p,
                                caminho_monitorado=norm_root,
                                caminho_relativo=rel_p,
                                nome_arquivo=name,
                                eh_pasta=is_dir,
                                tamanho=size,
                                mtime_ns=mtime_ns,
                                ctime_ns=ctime_ns,
                                file_index=file_index,
                                hash_arquivo=None,
                                ultima_verificacao=now_str,
                            )
                            if is_dir:
                                _walk_dir(full_p)
                        except (PermissionError, FileNotFoundError, OSError) as item_exc:
                            logger.debug(
                                "Item ignorado durante varredura (%s): %s",
                                entry.path,
                                item_exc,
                            )
            except (PermissionError, FileNotFoundError, OSError) as dir_exc:
                logger.debug(
                    "Subpasta inacessível durante varredura (%s): %s",
                    current_dir,
                    dir_exc,
                )

        _walk_dir(norm_root)
        return current_map

    def scan_and_reconcile(
        self,
        root_path: Optional[str] = None,
        force_baseline_only: bool = False,
    ) -> Tuple[bool, int]:
        target_root = normalize_path(
            root_path if root_path is not None else self.config.caminho_monitorado
        )
        if not target_root:
            return False, 0

        with self._scan_lock:
            self.processor.flush_all(force=False)

            current_tree = self.collect_current_tree(target_root)
            if current_tree is None:
                return False, 0

            has_baseline = self.db.has_baseline_for_path(target_root)
            if not has_baseline or force_baseline_only:
                root_marker = FileSnapshot(
                    caminho_completo=target_root,
                    caminho_monitorado=target_root,
                    caminho_relativo=".",
                    nome_arquivo=os.path.basename(target_root) or "RAIZ",
                    eh_pasta=True,
                    tamanho=0,
                    mtime_ns=0,
                    ctime_ns=0,
                    file_index="ROOT_BASELINE",
                    hash_arquivo=None,
                    ultima_verificacao=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
                all_snaps = [root_marker] + list(current_tree.values())
                self.db.save_snapshots_delta(all_snaps, [])
                logger.info(
                    "Baseline inicial registrado para '%s' (%d itens indexados).",
                    target_root,
                    len(current_tree),
                )
                return True, 0

            known_tree = self.db.get_snapshots_for_path(target_root)
            known_tree.pop(target_root, None)

            known_paths = set(known_tree.keys())
            current_paths = set(current_tree.keys())

            added_paths = current_paths - known_paths
            removed_paths = known_paths - current_paths
            common_paths = current_paths & known_paths

            changes_detected = 0
            upserts: List[FileSnapshot] = []
            deletes: List[str] = []

            matched_added: Set[str] = set()
            matched_removed: Set[str] = set()

            removed_files = [
                known_tree[p] for p in removed_paths if not known_tree[p].eh_pasta
            ]
            added_files = [
                current_tree[p] for p in added_paths if not current_tree[p].eh_pasta
            ]

            for rem in removed_files:
                best_match: Optional[FileSnapshot] = None
                for add in added_files:
                    if add.caminho_completo in matched_added:
                        continue
                    if (
                        rem.file_index
                        and add.file_index
                        and rem.file_index != "0"
                        and rem.file_index == add.file_index
                    ):
                        best_match = add
                        break
                    if (
                        os.path.dirname(rem.caminho_completo).lower()
                        == os.path.dirname(add.caminho_completo).lower()
                        and rem.tamanho == add.tamanho
                        and rem.mtime_ns == add.mtime_ns
                    ):
                        best_match = add
                        break

                if best_match is not None:
                    matched_removed.add(rem.caminho_completo)
                    matched_added.add(best_match.caminho_completo)
                    best_match.hash_arquivo = rem.hash_arquivo or compute_file_hash(
                        best_match.caminho_completo,
                        self.config.calcular_hash_ate_mb,
                    )
                    upserts.append(best_match)
                    deletes.append(rem.caminho_completo)
                    changes_detected += 1
                    self.processor.submit_event(
                        event_type=EventType.ARQUIVO_RENOMEADO,
                        full_path=best_match.caminho_completo,
                        is_dir=False,
                        old_path=rem.caminho_completo,
                        details=f"Arquivo renomeado de '{rem.nome_arquivo}' para '{best_match.nome_arquivo}'",
                    )

            removed_dirs = [
                known_tree[p] for p in removed_paths if known_tree[p].eh_pasta
            ]
            added_dirs = [
                current_tree[p] for p in added_paths if current_tree[p].eh_pasta
            ]
            for rem_d in removed_dirs:
                best_dir_match: Optional[FileSnapshot] = None
                for add_d in added_dirs:
                    if add_d.caminho_completo in matched_added:
                        continue
                    if (
                        rem_d.file_index
                        and add_d.file_index
                        and rem_d.file_index != "0"
                        and rem_d.file_index == add_d.file_index
                    ):
                        best_dir_match = add_d
                        break
                    if (
                        os.path.dirname(rem_d.caminho_completo).lower()
                        == os.path.dirname(add_d.caminho_completo).lower()
                        and rem_d.ctime_ns > 0
                        and rem_d.ctime_ns == add_d.ctime_ns
                    ):
                        best_dir_match = add_d
                        break

                if best_dir_match is not None:
                    matched_removed.add(rem_d.caminho_completo)
                    matched_added.add(best_dir_match.caminho_completo)
                    upserts.append(best_dir_match)
                    deletes.append(rem_d.caminho_completo)
                    changes_detected += 1
                    self.processor.submit_event(
                        event_type=EventType.PASTA_RENOMEADA,
                        full_path=best_dir_match.caminho_completo,
                        is_dir=True,
                        old_path=rem_d.caminho_completo,
                        details=f"Pasta renomeada de '{rem_d.nome_arquivo}' para '{best_dir_match.nome_arquivo}'",
                    )

            for add_path in sorted(added_paths - matched_added):
                snap = current_tree[add_path]
                if not snap.eh_pasta:
                    snap.hash_arquivo = compute_file_hash(
                        snap.caminho_completo,
                        self.config.calcular_hash_ate_mb,
                    )
                upserts.append(snap)
                changes_detected += 1
                ev_type = (
                    EventType.NOVA_PASTA
                    if snap.eh_pasta
                    else EventType.NOVO_ARQUIVO
                )
                self.processor.submit_event(
                    event_type=ev_type,
                    full_path=snap.caminho_completo,
                    is_dir=snap.eh_pasta,
                    details="Detectado pela verificação híbrida",
                )

            for rem_path in sorted(removed_paths - matched_removed):
                old_snap = known_tree[rem_path]
                deletes.append(rem_path)
                changes_detected += 1
                ev_type = (
                    EventType.PASTA_EXCLUIDA
                    if old_snap.eh_pasta
                    else EventType.ARQUIVO_EXCLUIDO
                )
                self.processor.submit_event(
                    event_type=ev_type,
                    full_path=old_snap.caminho_completo,
                    is_dir=old_snap.eh_pasta,
                    details="Remoção detectada pela verificação híbrida",
                )

            for com_path in common_paths:
                curr_snap = current_tree[com_path]
                old_snap = known_tree[com_path]
                if curr_snap.eh_pasta:
                    continue

                if (
                    curr_snap.tamanho != old_snap.tamanho
                    or curr_snap.mtime_ns != old_snap.mtime_ns
                ):
                    new_hash = compute_file_hash(
                        curr_snap.caminho_completo,
                        self.config.calcular_hash_ate_mb,
                    )
                    curr_snap.hash_arquivo = new_hash
                    upserts.append(curr_snap)

                    if (
                        old_snap.hash_arquivo
                        and new_hash
                        and old_snap.hash_arquivo == new_hash
                    ):
                        continue

                    changes_detected += 1
                    self.processor.submit_event(
                        event_type=EventType.ARQUIVO_MODIFICADO,
                        full_path=curr_snap.caminho_completo,
                        is_dir=False,
                        details="Modificação detectada pela verificação híbrida",
                    )

            if upserts or deletes:
                self.db.save_snapshots_delta(upserts, deletes)

            return True, changes_detected


class HybridMonitorController:
    """
    Coordena a estratégia híbrida de monitoramento:
    1. Watchdog em tempo real.
    2. NetworkScanner periódico como mecanismo complementar e de segurança.
    3. Monitoramento contínuo de disponibilidade da pasta local ou de rede.
    """

    def __init__(
        self,
        db: DatabaseManager,
        config: AppConfig,
        on_new_task: Optional[Callable] = None,
        on_connection_change: Optional[Callable[[bool, str], None]] = None,
        on_sync_completed: Optional[Callable[[str, bool, int], None]] = None,
    ) -> None:
        self.db = db
        self.config = config
        self.on_connection_change = on_connection_change
        self.on_sync_completed = on_sync_completed

        self.processor = EventProcessor(
            db=self.db,
            config=self.config,
            on_new_task_callback=on_new_task,
        )
        self.watchdog = WatchdogMonitor(processor=self.processor)
        self.scanner = NetworkScanner(
            db=self.db,
            processor=self.processor,
            config=self.config,
        )

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._is_connected: Optional[bool] = None
        self._is_paused: bool = False
        self._simulated_offline: bool = False
        self.last_sync_time: Optional[str] = None
        self.last_status_message: str = "Aguardando seleção de pasta..."

    @property
    def has_configured_path(self) -> bool:
        return bool(self.config.caminho_monitorado and self.config.caminho_monitorado.strip())

    @property
    def is_connected(self) -> bool:
        return bool(self._is_connected) and not self._simulated_offline and self.has_configured_path

    @property
    def is_running(self) -> bool:
        return (
            self._monitor_thread is not None
            and self._monitor_thread.is_alive()
            and not self._is_paused
        )

    def start(self) -> None:
        with self._lock:
            self._is_paused = False
            if self._monitor_thread and self._monitor_thread.is_alive():
                return
            self._stop_event.clear()
            self._monitor_thread = threading.Thread(
                target=self._run_loop,
                name="HybridMonitorControllerThread",
                daemon=True,
            )
            self._monitor_thread.start()
            logger.info(
                "Controlador de monitoramento híbrido iniciado (pasta: '%s')",
                self.config.caminho_monitorado or "não selecionada",
            )

    def stop(self) -> None:
        self._stop_event.set()
        self.watchdog.stop()
        self.processor.flush_all(force=True)
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=3.0)
        logger.info("Controlador de monitoramento híbrido encerrado.")

    def pause(self) -> None:
        with self._lock:
            self._is_paused = True
            self.watchdog.stop()
            self.last_status_message = "Monitoramento pausado pelo usuário."

    def resume(self) -> None:
        with self._lock:
            self._is_paused = False
            self.force_sync_now()

    def set_simulated_offline(self, offline: bool) -> None:
        self._simulated_offline = offline
        self._check_and_sync_cycle()

    def update_config(self, new_config: AppConfig) -> None:
        old_path = normalize_path(self.config.caminho_monitorado)
        new_path = normalize_path(new_config.caminho_monitorado)
        self.config = new_config
        self.processor.update_config(new_config)
        self.scanner.update_config(new_config)

        if old_path.lower() != new_path.lower():
            logger.info(
                "Caminho monitorado atualizado para '%s'. Reiniciando observadores...",
                new_path or "(vazio)",
            )
            self.watchdog.stop()
            self._is_connected = None
            threading.Thread(
                target=self._check_and_sync_cycle,
                daemon=True,
            ).start()

    def force_sync_now(self) -> Tuple[bool, int]:
        return self._check_and_sync_cycle()

    def _check_and_sync_cycle(self) -> Tuple[bool, int]:
        path = (self.config.caminho_monitorado or "").strip()
        if not path:
            self.watchdog.stop()
            self._is_connected = False
            self.last_status_message = (
                "Nenhuma pasta selecionada. Escolha o local que deseja monitorar."
            )
            return False, 0

        if self._simulated_offline:
            available, msg = (
                False,
                f"Diretório indisponível (desconexão): {path}",
            )
        else:
            available, msg = self.scanner.check_share_available(path)

        if self._is_connected is None or self._is_connected != available:
            self._is_connected = available
            status_label = "CONECTADO" if available else "DESCONECTADO"
            self.db.log_connection_event(status_label, path, msg)

            if available:
                logger.info("Conexão estabelecida com %s: %s", path, msg)
                if not self.db.has_baseline_for_path(path):
                    self.scanner.scan_and_reconcile(
                        path, force_baseline_only=True
                    )
                self.watchdog.start(path)
            else:
                logger.warning("Diretório indisponível (%s): %s", path, msg)
                self.watchdog.stop()

            if self.on_connection_change is not None:
                try:
                    self.on_connection_change(available, msg)
                except Exception as exc:
                    logger.error(
                        "Erro no callback de mudança de conexão: %s", exc
                    )

        self.last_status_message = msg
        if not available:
            return False, 0

        if not self.watchdog.is_running and not self._is_paused:
            self.watchdog.start(path)

        ok, changes = self.scanner.scan_and_reconcile(path)
        now_fmt = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.last_sync_time = now_fmt

        if self.on_sync_completed:
            try:
                self.on_sync_completed(now_fmt, ok, changes)
            except Exception as exc:
                logger.error("Erro no callback de sincronização: %s", exc)

        return ok, changes

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._is_paused:
                try:
                    self._check_and_sync_cycle()
                except Exception as exc:
                    logger.error(
                        "Erro inesperado no ciclo de monitoramento híbrido: %s",
                        exc,
                    )
            interval = max(3, int(self.config.intervalo_de_verificacao))
            wait_sec = min(interval, 10) if not self._is_connected else interval
            self._stop_event.wait(wait_sec)
