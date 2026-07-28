#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
会话接口（异步分析 + 录音分段串联，2026-07-28）。

- `POST /api/v1/segments` —— 上传一段
- `POST /api/v1/sessions/{session_id}/finalize` —— 声明录完
- `GET /api/v1/sessions/{session_id}` —— 状态轮询
- `GET /api/v1/sessions` —— 会话列表

接口签名与返回体字段见 `docs/specs/2026-07-28-async-segmented-analysis-design.md` 4.2。
真正的状态机与幂等锁在 `services/segment_pipeline.py`（本路由只是它的调用方，
finalize 必须走 `segment_pipeline.finalize_session()`，不得自己改 session.status）。
"""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from models import get_db, User, AudioFile, AnalysisReport, RecordingSession, UploadStatus
from auth import get_current_user
from utils.file_utils import save_audio_file
from services.segment_pipeline import submit_segment_asr, finalize_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["会话"])

#: 后台 ASR 任务引用，防被 GC（与 segment_pipeline._spawn 同一目的，路由层独立持有一份）
_background_tasks: set = set()


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def _check_session_access(sess: RecordingSession, current_user: User) -> None:
    """越权防护：查/改别人的 session 一律 403。session 不存在由调用方查完后单独 404。"""
    if current_user.role != "admin" and sess.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此会话")


# ==================== POST /api/v1/segments ====================

@router.post("/segments", status_code=202)
async def upload_segment(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    segment_index: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传一段。session 不存在则隐式创建（status=recording）。
    同 (session_id, segment_index) 重复上传覆盖原段并重跑 ASR（幂等）。
    """
    sess = db.query(RecordingSession).filter(
        RecordingSession.session_id == session_id
    ).first()

    if sess is None:
        sess = RecordingSession(
            session_id=session_id,
            user_id=current_user.id,
            title=file.filename or session_id,
            status="recording",
        )
        db.add(sess)
        db.commit()
        db.refresh(sess)
    else:
        _check_session_access(sess, current_user)

    file_id, file_path, duration = await save_audio_file(file)
    ext = Path(file_path).suffix.replace(".", "")

    existing = db.query(AudioFile).filter(
        AudioFile.session_id == session_id,
        AudioFile.segment_index == segment_index,
    ).first()

    if existing is not None:
        # 覆盖旧的物理文件（不同 file_path 时才删，避免误删刚写入的新文件）
        old_path = Path(existing.file_path) if existing.file_path else None
        if old_path and old_path.exists() and str(old_path) != file_path:
            try:
                old_path.unlink()
            except OSError as e:
                logger.warning(f"覆盖段时删除旧文件失败（忽略）: {e}")

        existing.original_filename = file.filename
        existing.stored_filename = Path(file_path).name
        existing.file_path = file_path
        existing.file_size = Path(file_path).stat().st_size
        existing.duration = duration
        existing.file_format = ext
        existing.upload_status = UploadStatus.PENDING.value
        existing.asr_text = None
        db.commit()
        db.refresh(existing)
        audio_file = existing
    else:
        audio_file = AudioFile(
            file_id=file_id,
            user_id=current_user.id,
            original_filename=file.filename,
            stored_filename=Path(file_path).name,
            file_path=file_path,
            file_size=Path(file_path).stat().st_size,
            duration=duration,
            file_format=ext,
            upload_status=UploadStatus.PENDING.value,
            session_id=session_id,
            segment_index=segment_index,
        )
        db.add(audio_file)
        db.commit()
        db.refresh(audio_file)

    _spawn(submit_segment_asr(audio_file.id))

    return {
        "session_id": session_id,
        "segment_index": segment_index,
        "file_id": audio_file.file_id,
        "status": audio_file.upload_status,
    }


# ==================== POST /api/v1/sessions/{session_id}/finalize ====================

class FinalizeRequest(BaseModel):
    total_segments: int
    task_types: list[str] | None = None
    supplementary_text: str | None = None


@router.post("/sessions/{session_id}/finalize")
async def finalize_session_endpoint(
    session_id: str,
    request: FinalizeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """声明录完。幂等：重复调用只更新字段，不重复触发分析（由 segment_pipeline.finalize_session 保证）。"""
    sess = db.query(RecordingSession).filter(
        RecordingSession.session_id == session_id
    ).first()
    if sess is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    _check_session_access(sess, current_user)

    await finalize_session(
        session_id,
        request.total_segments,
        request.task_types,
        request.supplementary_text,
    )

    db.expire(sess)
    sess = db.query(RecordingSession).filter(
        RecordingSession.session_id == session_id
    ).first()
    return {"session_id": session_id, "status": sess.status}


# ==================== GET /api/v1/sessions/{session_id} ====================

def _session_progress(db: Session, sess: RecordingSession) -> dict:
    # 合并分析产生的虚拟 merged AudioFile 也挂着同一个 session_id，但 segment_index 为空，
    # 不是真正的「段」，必须排除，否则轮询时段数会多算一条。
    segments = db.query(AudioFile).filter(
        AudioFile.session_id == sess.session_id,
        AudioFile.segment_index.isnot(None),
    ).order_by(AudioFile.segment_index).all()

    asr_done = sum(1 for s in segments if s.upload_status == UploadStatus.COMPLETED.value)
    asr_total = sess.total_segments if sess.total_segments is not None else len(segments)

    report_ids = []
    if sess.merged_file_id is not None:
        reports = db.query(AnalysisReport).filter(
            AnalysisReport.file_id == sess.merged_file_id
        ).all()
        report_ids = [r.report_id for r in reports]

    return {
        "segments": segments,
        "progress": {"asr_done": asr_done, "asr_total": asr_total},
        "report_ids": report_ids,
    }


@router.get("/sessions/{session_id}")
async def get_session_status(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """状态轮询。字段一字不差按 spec 4.2：
    session_id / status / total_segments / segments[]{segment_index,status,duration} /
    progress{asr_done,asr_total} / report_ids[] / error_message
    """
    sess = db.query(RecordingSession).filter(
        RecordingSession.session_id == session_id
    ).first()
    if sess is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    _check_session_access(sess, current_user)

    info = _session_progress(db, sess)

    return {
        "session_id": sess.session_id,
        "status": sess.status,
        "total_segments": sess.total_segments,
        "segments": [
            {
                "segment_index": s.segment_index,
                "status": s.upload_status,
                "duration": s.duration,
            }
            for s in info["segments"]
        ],
        "progress": info["progress"],
        "report_ids": info["report_ids"],
        "error_message": sess.error_message,
    }


# ==================== GET /api/v1/sessions ====================

@router.get("/sessions")
async def list_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """App 历史列表用，当前用户的会话摘要（管理员看全部）。

    返回体 spec 未逐字给出，字段名按 App 端已实现的容错解析约定：
    数组包在 `sessions` 键下，每项含
    session_id/title/status/total_segments/progress{asr_done,asr_total}/report_ids/error_message/created_at。
    """
    query = db.query(RecordingSession)
    if current_user.role != "admin":
        query = query.filter(RecordingSession.user_id == current_user.id)
    sessions = query.order_by(desc(RecordingSession.created_at)).all()

    result = []
    for sess in sessions:
        info = _session_progress(db, sess)
        result.append({
            "session_id": sess.session_id,
            "title": sess.title,
            "status": sess.status,
            "total_segments": sess.total_segments,
            "progress": info["progress"],
            "report_ids": info["report_ids"],
            "error_message": sess.error_message,
            "created_at": sess.created_at.isoformat() if sess.created_at else None,
        })

    return {"sessions": result}
