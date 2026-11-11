"""
Gerenciador de persistência SQLite para eventos, tarefas (checklist),
configurações, snapshots de arquivos e histórico de conexões.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from config import CONFIG_FILE_PATH, DB_PATH, AppConfig
from database.models import (
    ConnectionLog,
    EventRecord,
    FileSnapshot,
    TaskItem,
    TaskStatus,
)

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Gerencia todas as operações de banco de dados SQLite com segurança entre threads,
    modo WAL ativado e tratamento resiliente de falhas.
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=15.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _execute_with_retry(self, func, *args, **kwargs):
        """Executa uma operação de banco de dados com retentativa em caso de bloqueio."""
        last_exc = None
        for attempt in range(4):
            try:
                with self._lock:
                    return func(*args, **kwargs)
            except sqlite3.OperationalError as exc:
                last_exc = exc
                logger.warning(
                    "SQLite ocupado/erro operacional (tentativa %d/4): %s",
                    attempt + 1,
                    exc,
                )
                time.sleep(0.15 * (attempt + 1))
            except sqlite3.DatabaseError as exc:
                logger.error("Erro no banco SQLite: %s", exc)
                raise
        if last_exc:
            raise last_exc

    def _init_database(self) -> None:
        """Inicializa todas as tabelas e índices necessários se não existirem."""

        def _create():
            with self._get_connection() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS eventos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        caminho_completo TEXT NOT NULL,
                        caminho_relativo TEXT NOT NULL,
                        nome_arquivo TEXT NOT NULL,
                        tipo_evento TEXT NOT NULL,
                        data_evento TEXT NOT NULL,
                        tamanho_arquivo INTEGER,
                        identificador_do_evento TEXT NOT NULL,
                        hash TEXT,
                        eh_pasta INTEGER NOT NULL DEFAULT 0,
                        caminho_antigo TEXT,
                        detalhes TEXT
                    );

                    CREATE INDEX IF NOT EXISTS idx_eventos_data
                        ON eventos(data_evento DESC);
                    CREATE INDEX IF NOT EXISTS idx_eventos_caminho
                        ON eventos(caminho_completo);
                    CREATE INDEX IF NOT EXISTS idx_eventos_identificador
                        ON eventos(identificador_do_evento);
                    CREATE INDEX IF NOT EXISTS idx_eventos_tipo
                        ON eventos(tipo_evento);

                    CREATE TABLE IF NOT EXISTS tarefas (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        id_evento INTEGER NOT NULL UNIQUE,
                        status TEXT NOT NULL DEFAULT 'PENDENTE',
                        data_conclusao TEXT,
                        observacao TEXT DEFAULT '',
                        FOREIGN KEY (id_evento) REFERENCES eventos(id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_tarefas_status
                        ON tarefas(status);
                    CREATE INDEX IF NOT EXISTS idx_tarefas_evento
                        ON tarefas(id_evento);

                    CREATE TABLE IF NOT EXISTS configuracoes (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        caminho_monitorado TEXT NOT NULL,
                        intervalo_de_verificacao INTEGER NOT NULL DEFAULT 15,
                        iniciar_com_windows INTEGER NOT NULL DEFAULT 1,
                        abrir_ao_iniciar INTEGER NOT NULL DEFAULT 0,
                        notificacoes_ativas INTEGER NOT NULL DEFAULT 1,
                        notificar_exclusao INTEGER NOT NULL DEFAULT 1,
                        notificar_modificacao INTEGER NOT NULL DEFAULT 1,
                        notificar_criacao INTEGER NOT NULL DEFAULT 1,
                        notificar_renomeacao INTEGER NOT NULL DEFAULT 1,
                        notificar_desconexao INTEGER NOT NULL DEFAULT 1,
                        limite_historico INTEGER NOT NULL DEFAULT 10000,
                        debounce_segundos REAL NOT NULL DEFAULT 2.0,
                        calcular_hash_ate_mb INTEGER NOT NULL DEFAULT 25,
                        preferencias_de_interface TEXT NOT NULL DEFAULT '{}'
                    );

                    CREATE TABLE IF NOT EXISTS snapshot_arquivos (
                        caminho_completo TEXT PRIMARY KEY,
                        caminho_monitorado TEXT NOT NULL,
                        caminho_relativo TEXT NOT NULL,
                        nome_arquivo TEXT NOT NULL,
                        eh_pasta INTEGER NOT NULL DEFAULT 0,
                        tamanho INTEGER NOT NULL DEFAULT 0,
                        mtime_ns INTEGER NOT NULL DEFAULT 0,
                        ctime_ns INTEGER NOT NULL DEFAULT 0,
                        file_index TEXT,
                        hash_arquivo TEXT,
                        ultima_verificacao TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_snapshot_monitorado
                        ON snapshot_arquivos(caminho_monitorado);

                    CREATE TABLE IF NOT EXISTS historico_conexao (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        status TEXT NOT NULL,
                        caminho TEXT NOT NULL,
                        data_registro TEXT NOT NULL,
                        mensagem TEXT DEFAULT ''
                    );
                    """
                )
                row = conn.execute(
                    "SELECT id FROM configuracoes WHERE id = 1"
                ).fetchone()
                if not row:
                    default_cfg = AppConfig.load_from_file(CONFIG_FILE_PATH)
                    self._upsert_config_in_conn(conn, default_cfg)
                conn.commit()

        self._execute_with_retry(_create)

    def _upsert_config_in_conn(
        self, conn: sqlite3.Connection, cfg: AppConfig
    ) -> None:
        prefs_json = json.dumps(
            cfg.preferencias_de_interface, ensure_ascii=False
        )
        conn.execute(
            """
            INSERT INTO configuracoes (
                id, caminho_monitorado, intervalo_de_verificacao,
                iniciar_com_windows, abrir_ao_iniciar, notificacoes_ativas,
                notificar_exclusao, notificar_modificacao, notificar_criacao,
                notificar_renomeacao, notificar_desconexao, limite_historico,
                debounce_segundos, calcular_hash_ate_mb, preferencias_de_interface
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                caminho_monitorado = excluded.caminho_monitorado,
                intervalo_de_verificacao = excluded.intervalo_de_verificacao,
                iniciar_com_windows = excluded.iniciar_com_windows,
                abrir_ao_iniciar = excluded.abrir_ao_iniciar,
                notificacoes_ativas = excluded.notificacoes_ativas,
                notificar_exclusao = excluded.notificar_exclusao,
                notificar_modificacao = excluded.notificar_modificacao,
                notificar_criacao = excluded.notificar_criacao,
                notificar_renomeacao = excluded.notificar_renomeacao,
                notificar_desconexao = excluded.notificar_desconexao,
                limite_historico = excluded.limite_historico,
                debounce_segundos = excluded.debounce_segundos,
                calcular_hash_ate_mb = excluded.calcular_hash_ate_mb,
                preferencias_de_interface = excluded.preferencias_de_interface
            """,
            (
                cfg.caminho_monitorado,
                int(cfg.intervalo_de_verificacao),
                int(bool(cfg.iniciar_com_windows)),
                int(bool(cfg.abrir_ao_iniciar)),
                int(bool(cfg.notificacoes_ativas)),
                int(bool(cfg.notificar_exclusao)),
                int(bool(cfg.notificar_modificacao)),
                int(bool(cfg.notificar_criacao)),
                int(bool(cfg.notificar_renomeacao)),
                int(bool(cfg.notificar_desconexao)),
                int(cfg.limite_historico),
                float(cfg.debounce_segundos),
                int(cfg.calcular_hash_ate_mb),
                prefs_json,
            ),
        )

    def save_config(self, cfg: AppConfig) -> None:
        def _save():
            with self._get_connection() as conn:
                self._upsert_config_in_conn(conn, cfg)
                conn.commit()

        self._execute_with_retry(_save)
        cfg.save_to_file(CONFIG_FILE_PATH)

    def load_config(self) -> AppConfig:
        def _load() -> AppConfig:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM configuracoes WHERE id = 1"
                ).fetchone()
                if not row:
                    cfg = AppConfig.load_from_file(CONFIG_FILE_PATH)
                    self._upsert_config_in_conn(conn, cfg)
                    conn.commit()
                    return cfg
                data = dict(row)
                for bool_field in (
                    "iniciar_com_windows",
                    "abrir_ao_iniciar",
                    "notificacoes_ativas",
                    "notificar_exclusao",
                    "notificar_modificacao",
                    "notificar_criacao",
                    "notificar_renomeacao",
                    "notificar_desconexao",
                ):
                    if bool_field in data:
                        data[bool_field] = bool(data[bool_field])
                return AppConfig.from_dict(data)

        return self._execute_with_retry(_load)

    def register_event_and_task(
        self,
        event: EventRecord,
        dedup_window_seconds: float = 3.0,
    ) -> Optional[TaskItem]:
        def _insert() -> Optional[TaskItem]:
            with self._get_connection() as conn:
                if event.identificador_do_evento:
                    existing = conn.execute(
                        "SELECT id FROM eventos WHERE identificador_do_evento = ?",
                        (event.identificador_do_evento,),
                    ).fetchone()
                    if existing:
                        return None

                if dedup_window_seconds > 0:
                    try:
                        event_dt = datetime.fromisoformat(event.data_evento)
                        threshold_dt = event_dt - timedelta(
                            seconds=dedup_window_seconds
                        )
                        threshold_str = threshold_dt.strftime("%Y-%m-%d %H:%M:%S")
                        recent = conn.execute(
                            """
                            SELECT id, hash, tamanho_arquivo FROM eventos
                            WHERE caminho_completo = ?
                              AND tipo_evento = ?
                              AND data_evento >= ?
                            ORDER BY id DESC LIMIT 1
                            """,
                            (
                                event.caminho_completo,
                                event.tipo_evento,
                                threshold_str,
                            ),
                        ).fetchone()
                        if recent:
                            if (
                                not event.hash
                                or not recent["hash"]
                                or event.hash == recent["hash"]
                            ):
                                conn.execute(
                                    """
                                    UPDATE eventos
                                    SET data_evento = ?,
                                        tamanho_arquivo = COALESCE(?, tamanho_arquivo),
                                        hash = COALESCE(?, hash),
                                        detalhes = COALESCE(?, detalhes)
                                    WHERE id = ?
                                    """,
                                    (
                                        event.data_evento,
                                        event.tamanho_arquivo,
                                        event.hash,
                                        event.detalhes,
                                        recent["id"],
                                    ),
                                )
                                conn.commit()
                                return None
                    except Exception as exc:
                        logger.debug("Erro ao checar janela de deduplicação: %s", exc)

                cursor = conn.execute(
                    """
                    INSERT INTO eventos (
                        caminho_completo,
                        caminho_relativo,
                        nome_arquivo,
                        tipo_evento,
                        data_evento,
                        tamanho_arquivo,
                        identificador_do_evento,
                        hash,
                        eh_pasta,
                        caminho_antigo,
                        detalhes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.caminho_completo,
                        event.caminho_relativo,
                        event.nome_arquivo,
                        event.tipo_evento,
                        event.data_evento,
                        event.tamanho_arquivo,
                        event.identificador_do_evento,
                        event.hash,
                        int(bool(event.eh_pasta)),
                        event.caminho_antigo,
                        event.detalhes,
                    ),
                )
                event_id = cursor.lastrowid
                task_cursor = conn.execute(
                    """
                    INSERT INTO tarefas (id_evento, status, data_conclusao, observacao)
                    VALUES (?, ?, NULL, '')
                    """,
                    (event_id, TaskStatus.PENDENTE.value),
                )
                task_id = task_cursor.lastrowid
                conn.commit()

                row = conn.execute(
                    self._base_task_query() + " WHERE t.id = ?",
                    (task_id,),
                ).fetchone()
                return self._row_to_task_item(row) if row else None

        return self._execute_with_retry(_insert)

    @staticmethod
    def _base_task_query() -> str:
        return """
            SELECT
                t.id AS task_id,
                t.id_evento AS event_id,
                t.status AS status,
                t.data_conclusao AS data_conclusao,
                COALESCE(t.observacao, '') AS observacao,
                e.caminho_completo AS caminho_completo,
                e.caminho_relativo AS caminho_relativo,
                e.nome_arquivo AS nome_arquivo,
                e.tipo_evento AS tipo_evento,
                e.data_evento AS data_evento,
                e.tamanho_arquivo AS tamanho_arquivo,
                e.identificador_do_evento AS identificador_do_evento,
                e.hash AS hash,
                e.eh_pasta AS eh_pasta,
                e.caminho_antigo AS caminho_antigo,
                e.detalhes AS detalhes
            FROM tarefas t
            INNER JOIN eventos e ON e.id = t.id_evento
        """

    @staticmethod
    def _row_to_task_item(row: sqlite3.Row) -> TaskItem:
        return TaskItem(
            task_id=row["task_id"],
            event_id=row["event_id"],
            status=row["status"],
            data_conclusao=row["data_conclusao"],
            observacao=row["observacao"] or "",
            caminho_completo=row["caminho_completo"],
            caminho_relativo=row["caminho_relativo"],
            nome_arquivo=row["nome_arquivo"],
            tipo_evento=row["tipo_evento"],
            data_evento=row["data_evento"],
            tamanho_arquivo=row["tamanho_arquivo"],
            identificador_do_evento=row["identificador_do_evento"],
            hash=row["hash"],
            eh_pasta=bool(row["eh_pasta"]),
            caminho_antigo=row["caminho_antigo"],
            detalhes=row["detalhes"],
        )

    def get_task_by_id(self, task_id: int) -> Optional[TaskItem]:
        def _get() -> Optional[TaskItem]:
            with self._get_connection() as conn:
                row = conn.execute(
                    self._base_task_query() + " WHERE t.id = ?",
                    (task_id,),
                ).fetchone()
                return self._row_to_task_item(row) if row else None

        return self._execute_with_retry(_get)

    def query_tasks(
        self,
        status_filter: str = "TODAS",
        period_filter: str = "TODOS",
        event_type_filter: str = "TODOS",
        search_query: str = "",
        sort_desc: bool = True,
        limit: int = 5000,
    ) -> List[TaskItem]:
        def _query() -> List[TaskItem]:
            clauses: List[str] = []
            params: List[Any] = []

            status_upper = (status_filter or "TODAS").upper()
            if status_upper in ("PENDENTES", "PENDENTE"):
                clauses.append("t.status = ?")
                params.append(TaskStatus.PENDENTE.value)
            elif status_upper in ("CONCLUIDAS", "CONCLUÍDAS", "CONCLUIDO"):
                clauses.append("t.status = ?")
                params.append(TaskStatus.CONCLUIDO.value)

            now = datetime.now()
            period_upper = (period_filter or "TODOS").upper()
            if period_upper == "HOJE":
                start_today = now.replace(
                    hour=0, minute=0, second=0, microsecond=0
                ).strftime("%Y-%m-%d %H:%M:%S")
                clauses.append("e.data_evento >= ?")
                params.append(start_today)
            elif period_upper in ("7_DIAS", "ULTIMOS_7_DIAS", "ÚLTIMOS 7 DIAS"):
                start_7d = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
                clauses.append("e.data_evento >= ?")
                params.append(start_7d)
            elif period_upper in ("30_DIAS", "ULTIMOS_30_DIAS", "ÚLTIMOS 30 DIAS"):
                start_30d = (now - timedelta(days=30)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                clauses.append("e.data_evento >= ?")
                params.append(start_30d)

            if event_type_filter and event_type_filter.upper() != "TODOS":
                clauses.append("e.tipo_evento = ?")
                params.append(event_type_filter)

            if search_query and search_query.strip():
                term = f"%{search_query.strip()}%"
                clauses.append(
                    "(e.nome_arquivo LIKE ? OR e.caminho_relativo LIKE ? OR COALESCE(e.detalhes, '') LIKE ? OR COALESCE(t.observacao, '') LIKE ?)"
                )
                params.extend([term, term, term, term])

            sql = self._base_task_query()
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)

            order_dir = "DESC" if sort_desc else "ASC"
            sql += f" ORDER BY e.data_evento {order_dir}, t.id {order_dir}"
            if limit and limit > 0:
                sql += f" LIMIT {int(limit)}"

            with self._get_connection() as conn:
                rows = conn.execute(sql, params).fetchall()
                return [self._row_to_task_item(r) for r in rows]

        return self._execute_with_retry(_query)

    def set_task_completed(
        self,
        task_id: int,
        completed: bool,
        observacao: Optional[str] = None,
    ) -> Optional[TaskItem]:
        def _update() -> Optional[TaskItem]:
            new_status = (
                TaskStatus.CONCLUIDO.value
                if completed
                else TaskStatus.PENDENTE.value
            )
            conclusion_dt = (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if completed
                else None
            )
            with self._get_connection() as conn:
                if observacao is not None:
                    conn.execute(
                        """
                        UPDATE tarefas
                        SET status = ?, data_conclusao = ?, observacao = ?
                        WHERE id = ?
                        """,
                        (new_status, conclusion_dt, observacao, task_id),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE tarefas
                        SET status = ?, data_conclusao = ?
                        WHERE id = ?
                        """,
                        (new_status, conclusion_dt, task_id),
                    )
                conn.commit()
                row = conn.execute(
                    self._base_task_query() + " WHERE t.id = ?",
                    (task_id,),
                ).fetchone()
                return self._row_to_task_item(row) if row else None

        return self._execute_with_retry(_update)

    def update_task_observation(self, task_id: int, observacao: str) -> None:
        def _update():
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE tarefas SET observacao = ? WHERE id = ?",
                    (observacao, task_id),
                )
                conn.commit()

        self._execute_with_retry(_update)

    def mark_all_pending_completed(
        self, task_ids: Optional[Iterable[int]] = None
    ) -> int:
        def _mark_all() -> int:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self._get_connection() as conn:
                if task_ids is not None:
                    ids_list = [int(i) for i in task_ids]
                    if not ids_list:
                        return 0
                    placeholders = ",".join("?" for _ in ids_list)
                    cursor = conn.execute(
                        f"""
                        UPDATE tarefas
                        SET status = ?, data_conclusao = ?
                        WHERE status = ? AND id IN ({placeholders})
                        """,
                        [
                            TaskStatus.CONCLUIDO.value,
                            now_str,
                            TaskStatus.PENDENTE.value,
                            *ids_list,
                        ],
                    )
                else:
                    cursor = conn.execute(
                        """
                        UPDATE tarefas
                        SET status = ?, data_conclusao = ?
                        WHERE status = ?
                        """,
                        (
                            TaskStatus.CONCLUIDO.value,
                            now_str,
                            TaskStatus.PENDENTE.value,
                        ),
                    )
                conn.commit()
                return cursor.rowcount

        return self._execute_with_retry(_mark_all)

    def delete_tasks_explicit(self, task_ids: Iterable[int]) -> int:
        def _delete() -> int:
            ids_list = [int(i) for i in task_ids]
            if not ids_list:
                return 0
            placeholders = ",".join("?" for _ in ids_list)
            with self._get_connection() as conn:
                rows = conn.execute(
                    f"SELECT id_evento FROM tarefas WHERE id IN ({placeholders})",
                    ids_list,
                ).fetchall()
                event_ids = [r["id_evento"] for r in rows]
                if not event_ids:
                    return 0
                ev_placeholders = ",".join("?" for _ in event_ids)
                cursor = conn.execute(
                    f"DELETE FROM eventos WHERE id IN ({ev_placeholders})",
                    event_ids,
                )
                conn.commit()
                return cursor.rowcount

        return self._execute_with_retry(_delete)

    def get_indicators(self) -> Dict[str, Any]:
        def _stats() -> Dict[str, Any]:
            start_today = (
                datetime.now()
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .strftime("%Y-%m-%d %H:%M:%S")
            )
            with self._get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN t.status = 'PENDENTE' THEN 1 ELSE 0 END) AS pendentes,
                        SUM(CASE WHEN t.status = 'CONCLUIDO' THEN 1 ELSE 0 END) AS concluidas,
                        SUM(CASE WHEN e.data_evento >= ? THEN 1 ELSE 0 END) AS hoje,
                        MAX(e.data_evento) AS ultima_alteracao
                    FROM tarefas t
                    INNER JOIN eventos e ON e.id = t.id_evento
                    """,
                    (start_today,),
                ).fetchone()
                return {
                    "total": int(row["total"] or 0),
                    "pendentes": int(row["pendentes"] or 0),
                    "concluidas": int(row["concluidas"] or 0),
                    "hoje": int(row["hoje"] or 0),
                    "ultima_alteracao": row["ultima_alteracao"],
                }

        return self._execute_with_retry(_stats)

    def has_baseline_for_path(self, monitored_path: str) -> bool:
        def _check() -> bool:
            if not monitored_path or not monitored_path.strip():
                return False
            norm_path = str(Path(monitored_path))
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT 1 FROM snapshot_arquivos WHERE caminho_monitorado = ? LIMIT 1",
                    (norm_path,),
                ).fetchone()
                return row is not None

        return self._execute_with_retry(_check)

    def get_snapshots_for_path(
        self, monitored_path: str
    ) -> Dict[str, FileSnapshot]:
        def _load() -> Dict[str, FileSnapshot]:
            if not monitored_path or not monitored_path.strip():
                return {}
            norm_path = str(Path(monitored_path))
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM snapshot_arquivos
                    WHERE caminho_monitorado = ?
                    """,
                    (norm_path,),
                ).fetchall()
                result: Dict[str, FileSnapshot] = {}
                for r in rows:
                    snap = FileSnapshot(
                        caminho_completo=r["caminho_completo"],
                        caminho_monitorado=r["caminho_monitorado"],
                        caminho_relativo=r["caminho_relativo"],
                        nome_arquivo=r["nome_arquivo"],
                        eh_pasta=bool(r["eh_pasta"]),
                        tamanho=int(r["tamanho"] or 0),
                        mtime_ns=int(r["mtime_ns"] or 0),
                        ctime_ns=int(r["ctime_ns"] or 0),
                        file_index=r["file_index"],
                        hash_arquivo=r["hash_arquivo"],
                        ultima_verificacao=r["ultima_verificacao"],
                    )
                    result[snap.caminho_completo] = snap
                return result

        return self._execute_with_retry(_load)

    def save_snapshots_delta(
        self,
        upserts: Iterable[FileSnapshot],
        deleted_paths: Iterable[str],
    ) -> None:
        def _save():
            upsert_list = list(upserts)
            delete_list = list(deleted_paths)
            if not upsert_list and not delete_list:
                return
            with self._get_connection() as conn:
                if upsert_list:
                    conn.executemany(
                        """
                        INSERT INTO snapshot_arquivos (
                            caminho_completo, caminho_monitorado, caminho_relativo,
                            nome_arquivo, eh_pasta, tamanho, mtime_ns, ctime_ns,
                            file_index, hash_arquivo, ultima_verificacao
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(caminho_completo) DO UPDATE SET
                            caminho_monitorado = excluded.caminho_monitorado,
                            caminho_relativo = excluded.caminho_relativo,
                            nome_arquivo = excluded.nome_arquivo,
                            eh_pasta = excluded.eh_pasta,
                            tamanho = excluded.tamanho,
                            mtime_ns = excluded.mtime_ns,
                            ctime_ns = excluded.ctime_ns,
                            file_index = COALESCE(excluded.file_index, snapshot_arquivos.file_index),
                            hash_arquivo = COALESCE(excluded.hash_arquivo, snapshot_arquivos.hash_arquivo),
                            ultima_verificacao = excluded.ultima_verificacao
                        """,
                        [
                            (
                                s.caminho_completo,
                                s.caminho_monitorado,
                                s.caminho_relativo,
                                s.nome_arquivo,
                                int(bool(s.eh_pasta)),
                                int(s.tamanho),
                                int(s.mtime_ns),
                                int(s.ctime_ns),
                                s.file_index,
                                s.hash_arquivo,
                                s.ultima_verificacao
                                or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            )
                            for s in upsert_list
                        ],
                    )
                if delete_list:
                    conn.executemany(
                        "DELETE FROM snapshot_arquivos WHERE caminho_completo = ?",
                        [(p,) for p in delete_list],
                    )
                conn.commit()

        self._execute_with_retry(_save)

    def clear_snapshots_for_path(self, monitored_path: str) -> None:
        def _clear():
            norm_path = str(Path(monitored_path))
            with self._get_connection() as conn:
                conn.execute(
                    "DELETE FROM snapshot_arquivos WHERE caminho_monitorado = ?",
                    (norm_path,),
                )
                conn.commit()

        self._execute_with_retry(_clear)

    def log_connection_event(
        self, status: str, caminho: str, mensagem: str = ""
    ) -> None:
        def _log():
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO historico_conexao (status, caminho, data_registro, mensagem)
                    VALUES (?, ?, ?, ?)
                    """,
                    (status, caminho, now_str, mensagem),
                )
                conn.commit()

        self._execute_with_retry(_log)

    def get_recent_connection_logs(self, limit: int = 50) -> List[ConnectionLog]:
        def _get() -> List[ConnectionLog]:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM historico_conexao
                    ORDER BY id DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                return [
                    ConnectionLog(
                        id=r["id"],
                        status=r["status"],
                        caminho=r["caminho"],
                        data_registro=r["data_registro"],
                        mensagem=r["mensagem"] or "",
                    )
                    for r in rows
                ]

        return self._execute_with_retry(_get)
