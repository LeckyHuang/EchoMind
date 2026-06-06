"""
SQLite 写入层
- WAL 模式：支持 api-gateway / wiki-app / wiki-app-hub 三进程并发写入
- obs.db 存放在 llm-wiki-kit 根目录
"""

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

# llm-wiki-kit 根目录（obs/ 的上层）
_ROOT = Path(__file__).parent.parent
DB_PATH = _ROOT / "obs.db"

_local = threading.local()


def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return _local.conn


def setup_db() -> None:
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spans (
            id         TEXT PRIMARY KEY,
            trace_id   TEXT NOT NULL,
            service    TEXT NOT NULL,
            operation  TEXT NOT NULL,
            provider   TEXT,
            start_ts   REAL NOT NULL,
            end_ts     REAL,
            latency_ms INTEGER,
            status     TEXT NOT NULL DEFAULT 'ok',
            error_msg  TEXT,
            metadata   TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_spans_ts    ON spans(start_ts)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_calls (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ts           REAL    NOT NULL,
            project      TEXT    NOT NULL,
            operation    TEXT,
            provider     TEXT,
            model        TEXT,
            input_tokens  INTEGER,
            output_tokens INTEGER,
            total_tokens  INTEGER,
            latency_ms   INTEGER,
            cost_cny     REAL,
            status       TEXT    NOT NULL DEFAULT 'ok',
            error_msg    TEXT,
            error_type   TEXT,
            trace_id     TEXT,
            parent_id    TEXT,
            session_id   TEXT,
            prompt_chars INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts      ON llm_calls(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project ON llm_calls(project)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status  ON llm_calls(status)")
    # 兼容已有数据库：ALTER 若列已存在会抛异常，用 try/except 保护
    for _col in ["ALTER TABLE llm_calls ADD COLUMN error_type TEXT",
                 "ALTER TABLE llm_calls ADD COLUMN prompt_chars INTEGER"]:
        try:
            conn.execute(_col)
        except Exception:
            pass
    conn.commit()


def write_call(
    project: str,
    operation: str,
    provider: str,
    model: str,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    latency_ms: int,
    cost_cny: Optional[float],
    status: str,
    error_msg: Optional[str] = None,
    error_type: Optional[str] = None,
    trace_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    session_id: Optional[str] = None,
    prompt_chars: Optional[int] = None,
) -> None:
    total = (
        (input_tokens or 0) + (output_tokens or 0)
        if input_tokens is not None or output_tokens is not None
        else None
    )
    try:
        conn = _conn()
        conn.execute(
            """
            INSERT INTO llm_calls
              (ts, project, operation, provider, model,
               input_tokens, output_tokens, total_tokens,
               latency_ms, cost_cny, status, error_msg, error_type,
               trace_id, parent_id, session_id, prompt_chars)
            VALUES (?,?,?,?,?, ?,?,?, ?,?,?,?,?, ?,?,?,?)
            """,
            (
                time.time(), project, operation, provider, model,
                input_tokens, output_tokens, total,
                latency_ms, cost_cny, status, error_msg, error_type,
                trace_id, parent_id, session_id, prompt_chars,
            ),
        )
        conn.commit()
    except Exception:
        pass  # 可观测性层故障不应影响业务


def write_span(
    span_id: str,
    trace_id: str,
    service: str,
    operation: str,
    start_ts: float,
    end_ts: float,
    status: str,
    provider: Optional[str] = None,
    error_msg: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    try:
        conn = _conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO spans
              (id, trace_id, service, operation, provider,
               start_ts, end_ts, latency_ms, status, error_msg, metadata)
            VALUES (?,?,?,?,?, ?,?,?,?,?,?)
            """,
            (
                span_id, trace_id, service, operation, provider,
                start_ts, end_ts, int((end_ts - start_ts) * 1000),
                status, error_msg,
                json.dumps(metadata) if metadata else None,
            ),
        )
        conn.commit()
    except Exception:
        pass
