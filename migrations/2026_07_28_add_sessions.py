#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性迁移脚本：新增 recording_sessions 表 + audio_files.session_id/segment_index 两列。

设计依据：docs/specs/2026-07-28-async-segmented-analysis-design.md 第 4.1 / 第 6 节。

**幂等可重跑**：
- 建表用 `CREATE TABLE IF NOT EXISTS`
- 加列前先查 `PRAGMA table_info(audio_files)`，列已存在就跳过
- 每一步都打印做了什么 / 跳过了什么，不抛异常

用法：
    python migrations/2026_07_28_add_sessions.py
    DATABASE_URL=sqlite:////path/to/some.db python migrations/2026_07_28_add_sessions.py
"""

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

BASE_DIR = Path(__file__).resolve().parent.parent

# 允许通过环境变量指定目标库（用于对副本演练迁移），默认与 models.py 保持一致
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR}/data/echodmind.db")


CREATE_RECORDING_SESSIONS_SQL = """
CREATE TABLE IF NOT EXISTS recording_sessions (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    session_id VARCHAR(36) NOT NULL,
    user_id INTEGER NOT NULL,
    title VARCHAR(255),
    status VARCHAR(20) DEFAULT 'recording',
    total_segments INTEGER,
    task_types JSON,
    supplementary_text TEXT,
    merged_file_id INTEGER,
    error_message TEXT,
    created_at DATETIME,
    updated_at DATETIME,
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY(merged_file_id) REFERENCES audio_files (id) ON DELETE SET NULL
)
"""

CREATE_RECORDING_SESSIONS_UNIQUE_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_recording_sessions_session_id "
    "ON recording_sessions (session_id)"
)

CREATE_RECORDING_SESSIONS_STATUS_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS ix_recording_sessions_status "
    "ON recording_sessions (status)"
)

ADD_AUDIO_FILES_SESSION_ID_SQL = (
    "ALTER TABLE audio_files ADD COLUMN session_id VARCHAR(36)"
)

ADD_AUDIO_FILES_SEGMENT_INDEX_SQL = (
    "ALTER TABLE audio_files ADD COLUMN segment_index INTEGER"
)

CREATE_AUDIO_FILES_SESSION_ID_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS ix_audio_files_session_id "
    "ON audio_files (session_id)"
)


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name},
    ).fetchone()
    return row is not None


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    existing_columns = {row[1] for row in rows}  # row[1] = column name
    return column_name in existing_columns


def _index_exists(conn, index_name: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='index' AND name=:name"),
        {"name": index_name},
    ).fetchone()
    return row is not None


def _ensure_index(conn, index_name: str, create_sql: str, label: str):
    if _index_exists(conn, index_name):
        print(f"[跳过] 索引 {index_name} 已存在")
    else:
        conn.execute(text(create_sql))
        print(f"[完成] 建索引 {index_name}（{label}）")


def migrate():
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

    with engine.begin() as conn:
        # ---- 1. recording_sessions 表 ----
        if _table_exists(conn, "recording_sessions"):
            print("[跳过] 表 recording_sessions 已存在")
        else:
            conn.execute(text(CREATE_RECORDING_SESSIONS_SQL))
            print("[完成] 建表 recording_sessions")

        _ensure_index(
            conn,
            "ix_recording_sessions_session_id",
            CREATE_RECORDING_SESSIONS_UNIQUE_INDEX_SQL,
            "recording_sessions.session_id 唯一索引",
        )
        _ensure_index(
            conn,
            "ix_recording_sessions_status",
            CREATE_RECORDING_SESSIONS_STATUS_INDEX_SQL,
            "recording_sessions.status 索引",
        )

        # ---- 2. audio_files.session_id ----
        if _column_exists(conn, "audio_files", "session_id"):
            print("[跳过] 列 audio_files.session_id 已存在")
        else:
            conn.execute(text(ADD_AUDIO_FILES_SESSION_ID_SQL))
            print("[完成] 加列 audio_files.session_id")

        # ---- 3. audio_files.segment_index ----
        if _column_exists(conn, "audio_files", "segment_index"):
            print("[跳过] 列 audio_files.segment_index 已存在")
        else:
            conn.execute(text(ADD_AUDIO_FILES_SEGMENT_INDEX_SQL))
            print("[完成] 加列 audio_files.segment_index")

        _ensure_index(
            conn,
            "ix_audio_files_session_id",
            CREATE_AUDIO_FILES_SESSION_ID_INDEX_SQL,
            "audio_files.session_id 索引",
        )

    engine.dispose()
    print(f"迁移完成，目标库: {DATABASE_URL}")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as exc:  # noqa: BLE001
        print(f"[失败] 迁移出错: {exc}", file=sys.stderr)
        sys.exit(1)
