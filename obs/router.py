"""
FastAPI router: /obs/*
挂载到任意子项目后，面板即可读取统计数据
"""

import json
import os
import time
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional

from obs.db import _conn

router = APIRouter(prefix="/obs", tags=["observability"])

# ── Bearer Token 鉴权 ──────────────────────────────────────────
_OBS_TOKEN = os.getenv("OBS_TOKEN", "")


def _check_obs_auth(authorization: Optional[str] = Header(None)):
    if not _OBS_TOKEN:
        return  # 未配置 token 则不鉴权（向后兼容）
    if authorization != f"Bearer {_OBS_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _days_ago(days: int) -> float:
    return time.time() - days * 86400


@router.get("/stats")
def get_stats(days: int = Query(7, ge=1, le=90), _: None = Depends(_check_obs_auth)):
    since = _days_ago(days)
    conn = _conn()

    # ── 延迟分位数 ────────────────────────────────────────────────
    _lats = [r[0] for r in conn.execute(
        "SELECT latency_ms FROM llm_calls WHERE ts >= ? AND status='ok' AND latency_ms IS NOT NULL ORDER BY latency_ms",
        (since,)
    ).fetchall()]
    def _pct(data, p):
        if not data: return None
        return data[max(0, min(int(len(data) * p / 100), len(data) - 1))]
    latency_percentiles = {"p50": _pct(_lats, 50), "p95": _pct(_lats, 95), "p99": _pct(_lats, 99)}

    # ── 汇总指标 ─────────────────────────────────────────────────
    row = conn.execute("""
        SELECT
            COUNT(*)                                          AS total_calls,
            SUM(CASE WHEN status='error' THEN 1 ELSE 0 END)  AS error_count,
            AVG(CASE WHEN status='ok' THEN latency_ms END)   AS avg_latency_ms,
            SUM(cost_cny)                                     AS total_cost_cny,
            SUM(total_tokens)                                 AS total_tokens
        FROM llm_calls WHERE ts >= ?
    """, (since,)).fetchone()

    total = row["total_calls"] or 0
    errors = row["error_count"] or 0
    summary = {
        "total_calls":    total,
        "error_count":    errors,
        "error_rate":     round(errors / total, 4) if total else 0,
        "avg_latency_ms": round(row["avg_latency_ms"] or 0, 1),
        "total_cost_cny": round(row["total_cost_cny"] or 0, 4),
        "total_tokens":   row["total_tokens"] or 0,
        "period_days":    days,
    }

    # ── 按天聚合 ──────────────────────────────────────────────────
    by_day = conn.execute("""
        SELECT
            DATE(ts, 'unixepoch', 'localtime')                AS day,
            COUNT(*)                                           AS calls,
            SUM(cost_cny)                                      AS cost_cny,
            AVG(CASE WHEN status='ok' THEN latency_ms END)    AS avg_latency_ms,
            SUM(CASE WHEN status='error' THEN 1 ELSE 0 END)   AS errors
        FROM llm_calls WHERE ts >= ?
        GROUP BY day ORDER BY day
    """, (since,)).fetchall()

    # ── 按模型聚合 ────────────────────────────────────────────────
    by_model = conn.execute("""
        SELECT
            model,
            provider,
            COUNT(*)                AS calls,
            SUM(input_tokens)       AS input_tokens,
            SUM(output_tokens)      AS output_tokens,
            SUM(total_tokens)       AS total_tokens,
            SUM(cost_cny)           AS cost_cny,
            AVG(latency_ms)         AS avg_latency_ms
        FROM llm_calls WHERE ts >= ?
        GROUP BY model, provider ORDER BY calls DESC
    """, (since,)).fetchall()

    # ── 按项目聚合 ────────────────────────────────────────────────
    by_project = conn.execute("""
        SELECT
            project,
            COUNT(*)            AS calls,
            SUM(cost_cny)       AS cost_cny,
            AVG(latency_ms)     AS avg_latency_ms,
            SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors
        FROM llm_calls WHERE ts >= ?
        GROUP BY project ORDER BY calls DESC
    """, (since,)).fetchall()

    # ── 最近错误 ──────────────────────────────────────────────────
    recent_errors = conn.execute("""
        SELECT id, ts, project, operation, model, error_msg, error_type, latency_ms
        FROM llm_calls
        WHERE status='error' AND ts >= ?
        ORDER BY ts DESC LIMIT 20
    """, (since,)).fetchall()

    # ── 最近调用 ──────────────────────────────────────────────────
    recent_calls = conn.execute("""
        SELECT id, ts, project, operation, model, provider,
               input_tokens, output_tokens, latency_ms, cost_cny, status, prompt_chars
        FROM llm_calls WHERE ts >= ?
        ORDER BY ts DESC LIMIT 50
    """, (since,)).fetchall()

    # ── ASR 统计（从 spans 表全量聚合）────────────────────────────────
    try:
        asr_stats = conn.execute("""
            SELECT
                provider,
                COUNT(*)                                              AS calls,
                SUM(CAST(json_extract(metadata, '$.audio_duration_s') AS REAL)) AS total_duration_s
            FROM spans
            WHERE operation = 'asr' AND start_ts >= ?
              AND metadata IS NOT NULL
            GROUP BY provider
        """, (since,)).fetchall()
        asr_list = []
        for r in asr_stats:
            dur = r["total_duration_s"] or 0.0
            asr_list.append({
                "provider": r["provider"],
                "calls": r["calls"],
                "total_duration_s": round(dur, 1),
                "total_minutes": round(dur / 60, 3),
            })
    except Exception:
        asr_list = []

    # ── 错误类型分布（安全预警用）────────────────────────────────
    try:
        _eb_rows = conn.execute("""
            SELECT error_type, COUNT(*) AS cnt
            FROM llm_calls
            WHERE status='error' AND ts >= ? AND error_type IS NOT NULL
            GROUP BY error_type
        """, (since,)).fetchall()
        error_breakdown = {r["error_type"]: r["cnt"] for r in _eb_rows}
        _sec_rows = conn.execute("""
            SELECT operation, COUNT(*) AS cnt
            FROM spans
            WHERE operation IN ('security:rate_limit_hit','security:file_rejected')
              AND start_ts >= ?
            GROUP BY operation
        """, (since,)).fetchall()
        for r in _sec_rows:
            error_breakdown[r["operation"].replace("security:", "")] = r["cnt"]
    except Exception:
        error_breakdown = {}

    def rows_to_list(rows):
        return [dict(r) for r in rows]

    # ── 按操作聚合（LLM 调用 + SPAN）────────────────────────────
    try:
        _llm_ops = conn.execute("""
            SELECT operation, 'llm' AS span_type,
                   COUNT(*) AS calls,
                   ROUND(AVG(latency_ms), 0) AS avg_latency_ms,
                   CAST(SUM(input_tokens) AS INTEGER) AS input_tokens,
                   CAST(SUM(output_tokens) AS INTEGER) AS output_tokens,
                   SUM(cost_cny) AS cost_cny,
                   SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors
            FROM llm_calls WHERE ts >= ?
            GROUP BY operation
        """, (since,)).fetchall()
        _span_ops = conn.execute("""
            SELECT operation, 'span' AS span_type,
                   COUNT(*) AS calls,
                   ROUND(AVG(latency_ms), 0) AS avg_latency_ms,
                   NULL AS input_tokens, NULL AS output_tokens, NULL AS cost_cny,
                   SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors
            FROM spans WHERE start_ts >= ?
            GROUP BY operation
        """, (since,)).fetchall()
        by_operation = sorted(
            rows_to_list(_llm_ops) + rows_to_list(_span_ops),
            key=lambda x: -(x["calls"] or 0),
        )
    except Exception:
        by_operation = []

    return JSONResponse({
        "summary":             summary,
        "latency_percentiles": latency_percentiles,
        "by_day":              rows_to_list(by_day),
        "by_model":            rows_to_list(by_model),
        "by_project":          rows_to_list(by_project),
        "recent_errors":       rows_to_list(recent_errors),
        "recent_calls":        rows_to_list(recent_calls),
        "asr_stats":           asr_list,
        "error_breakdown":     error_breakdown,
        "by_operation":        by_operation,
    })


@router.get("/traces")
def get_traces(limit: int = Query(20, ge=1, le=100), days: int = Query(7, ge=1, le=90), _: None = Depends(_check_obs_auth)):
    since = _days_ago(days)
    conn = _conn()

    # 取最近的 trace_id（按 spans 表，兼顾 llm_calls 里的 trace_id）
    trace_ids = conn.execute("""
        SELECT DISTINCT trace_id FROM (
            SELECT trace_id, start_ts as ts FROM spans WHERE start_ts >= ? AND trace_id IS NOT NULL
            UNION ALL
            SELECT trace_id, ts FROM llm_calls WHERE ts >= ? AND trace_id IS NOT NULL
        ) ORDER BY ts DESC LIMIT ?
    """, (since, since, limit)).fetchall()

    result = []
    for row in trace_ids:
        tid = row[0]

        spans_rows = conn.execute("""
            SELECT operation, provider, start_ts, end_ts, latency_ms, status, error_msg, metadata
            FROM spans WHERE trace_id = ? ORDER BY start_ts
        """, (tid,)).fetchall()

        llm_rows = conn.execute("""
            SELECT operation, provider, model, ts as start_ts,
                   (ts + latency_ms/1000.0) as end_ts,
                   latency_ms, status, error_msg, cost_cny, input_tokens, output_tokens
            FROM llm_calls WHERE trace_id = ? ORDER BY ts
        """, (tid,)).fetchall()

        all_spans = [
            {
                "type": "span",
                "operation": r["operation"],
                "provider": r["provider"],
                "start_ts": r["start_ts"],
                "end_ts": r["end_ts"],
                "latency_ms": r["latency_ms"],
                "status": r["status"],
                "error_msg": r["error_msg"],
                "metadata": json.loads(r["metadata"]) if r["metadata"] else None,
            }
            for r in spans_rows
        ] + [
            {
                "type": "llm",
                "operation": r["operation"],
                "provider": r["provider"],
                "model": r["model"],
                "start_ts": r["start_ts"],
                "end_ts": r["end_ts"],
                "latency_ms": r["latency_ms"],
                "status": r["status"],
                "error_msg": r["error_msg"],
                "cost_cny": r["cost_cny"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
            }
            for r in llm_rows
        ]

        if not all_spans:
            continue

        all_spans.sort(key=lambda x: x["start_ts"])
        trace_start = all_spans[0]["start_ts"]
        trace_end = max(s["end_ts"] or s["start_ts"] for s in all_spans)

        result.append({
            "trace_id": tid,
            "start_ts": trace_start,
            "total_latency_ms": int((trace_end - trace_start) * 1000),
            "status": "error" if any(s["status"] == "error" for s in all_spans) else "ok",
            "spans": all_spans,
        })

    return JSONResponse(result)


@router.get("/health")
def obs_health(_: None = Depends(_check_obs_auth)):
    try:
        conn = _conn()
        total = conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0]
        return {"status": "ok", "total_records": total}
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)
