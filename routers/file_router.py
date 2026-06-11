#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件管理 API - 管理后台调用
"""

import uuid
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc

from models import get_db, User, AudioFile, AnalysisReport, UploadStatus, AnalysisStatus
from auth import get_current_user, get_current_admin
from config import settings
from services.asr_service import ASRService
from services.llm_service import LLMService
from utils.file_utils import save_audio_file

logger = logging.getLogger(__name__)

_asr_service = None
_llm_service = None

def get_asr_service() -> ASRService:
    global _asr_service
    if _asr_service is None:
        _asr_service = ASRService()
    return _asr_service

def get_llm_service() -> LLMService:
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service

router = APIRouter(prefix="/api/v1/admin", tags=["文件管理"])


def _get_task_types(db, selected: list[str] | None = None) -> list[str]:
    """返回要分析的任务类型列表。selected 不为空时只取交集；否则取 default_rank 1/2/3 的类型（按 rank 排序）。"""
    from models import AnalysisTaskType
    q = db.query(AnalysisTaskType).filter(AnalysisTaskType.is_active == True)
    if selected:
        q = q.filter(AnalysisTaskType.name.in_(selected))
    else:
        q = q.filter(AnalysisTaskType.default_rank > 0)
    types = q.order_by(AnalysisTaskType.default_rank, AnalysisTaskType.sort_order).all()
    return [t.name for t in types]


# ==================== 文件列表 ====================

class AudioFileResponse(BaseModel):
    id: int
    file_id: str
    original_filename: str | None
    file_size: int | None
    duration: float | None
    file_format: str | None
    upload_status: str
    has_report: bool
    created_at: str | None

    class Config:
        from_attributes = True


class FileListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int
    files: list[AudioFileResponse]


@router.get("/files", response_model=FileListResponse)
async def list_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query(None, description="搜索文件名"),
    status: str = Query(None, description="筛选状态: pending/processing/completed/failed"),
    date_from: str = Query(None, description="开始日期 YYYY-MM-DD"),
    date_to: str = Query(None, description="结束日期 YYYY-MM-DD"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取录音文件列表（分页 + 搜索 + 日期筛选）
    """
    # 普通用户只能看自己的文件，管理员看全部
    if current_user.role == "admin":
        query = db.query(AudioFile)
    else:
        query = db.query(AudioFile).filter(AudioFile.user_id == current_user.id)
    
    # 搜索文件名
    if keyword:
        query = query.filter(AudioFile.original_filename.ilike(f"%{keyword}%"))
    
    # 状态筛选
    if status:
        query = query.filter(AudioFile.upload_status == status)
    
    # 日期筛选
    if date_from:
        try:
            from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(AudioFile.created_at >= from_dt)
        except ValueError:
            pass
    
    if date_to:
        try:
            to_dt = datetime.strptime(date_to, "%Y-%m-%d")
            # 包含当天结束
            to_dt = to_dt.replace(hour=23, minute=59, second=59)
            query = query.filter(AudioFile.created_at <= to_dt)
        except ValueError:
            pass
    
    # 总数
    total = query.count()
    
    # 分页
    pages = (total + page_size - 1) // page_size
    offset = (page - 1) * page_size
    files = query.order_by(desc(AudioFile.created_at)).offset(offset).limit(page_size).all()
    
    return FileListResponse(
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
        files=[
            AudioFileResponse(
                id=f.id,
                file_id=f.file_id,
                original_filename=f.original_filename,
                file_size=f.file_size,
                duration=round(f.duration, 1) if f.duration else None,
                file_format=f.file_format,
                upload_status=f.upload_status,
                has_report=bool(f.analysis_reports),
                created_at=f.created_at.isoformat() if f.created_at else None
            )
            for f in files
        ]
    )


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    删除录音文件（同时删除物理文件和数据库记录）
    """
    audio_file = db.query(AudioFile).filter(AudioFile.file_id == file_id).first()
    if not audio_file:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    # 普通用户只能删除自己的文件
    if current_user.role != "admin" and audio_file.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权删除此文件")
    
    # 删除物理文件
    file_path = Path(settings.UPLOAD_DIR) / audio_file.stored_filename
    if file_path.exists():
        file_path.unlink()
    
    # 删除数据库记录（级联删除 analysis_report）
    db.delete(audio_file)
    db.commit()
    
    return {"success": True, "message": "文件已删除"}


@router.post("/files/batch-delete")
async def batch_delete_files(
    ids: list[str],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    批量删除录音文件
    """
    deleted = 0
    for file_id in ids:
        audio_file = db.query(AudioFile).filter(AudioFile.file_id == file_id).first()
        if audio_file:
            if current_user.role != "admin" and audio_file.user_id != current_user.id:
                continue
            file_path = Path(settings.UPLOAD_DIR) / audio_file.stored_filename
            if file_path.exists():
                file_path.unlink()
            db.delete(audio_file)
            deleted += 1

    db.commit()
    return {"success": True, "deleted": deleted}


@router.post("/files/{file_id}/delete-batch")
async def delete_files_batch(
    file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    兼容旧端点：单个文件路径，但 body 传 list[str]
    """
    audio_file = db.query(AudioFile).filter(AudioFile.file_id == file_id).first()
    if not audio_file:
        raise HTTPException(status_code=404, detail="文件不存在")
    if current_user.role != "admin" and audio_file.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权删除此文件")
    file_path = Path(settings.UPLOAD_DIR) / audio_file.stored_filename
    if file_path.exists():
        file_path.unlink()
    db.delete(audio_file)
    db.commit()
    return {"success": True, "deleted": 1}


@router.get("/files/{file_id}/download")
async def download_file(
    file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    下载录音文件
    """
    # 兼容 UUID file_id 和整数 id
    audio_file = db.query(AudioFile).filter(AudioFile.file_id == file_id).first()
    if not audio_file:
        try:
            audio_file = db.query(AudioFile).filter(AudioFile.id == int(file_id)).first()
        except (ValueError, TypeError):
            pass
    if not audio_file:
        raise HTTPException(status_code=404, detail="文件不存在")

    # 普通用户只能下载自己的文件
    if current_user.role != "admin" and audio_file.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权下载此文件")
    
    file_path = Path(settings.UPLOAD_DIR) / audio_file.stored_filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="录音物理文件已过期清理（分析报告仍保留）")
    
    # 原始文件名
    download_name = audio_file.original_filename or f"{file_id}.{audio_file.file_format}"
    
    media_types = {
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "wav": "audio/wav",
        "amr": "audio/amr",
        "3gp": "audio/3gpp",
    }
    media_type = media_types.get(audio_file.file_format, "audio/mpeg")
    
    return FileResponse(
        path=file_path,
        filename=download_name,
        media_type=media_type
    )


@router.get("/files/{file_id}/detail")
async def get_file_detail(
    file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取文件详细信息（含分析报告）
    """
    # 兼容 UUID file_id 和整数 id
    audio_file = db.query(AudioFile).filter(AudioFile.file_id == file_id).first()
    if not audio_file:
        try:
            audio_file = db.query(AudioFile).filter(AudioFile.id == int(file_id)).first()
        except (ValueError, TypeError):
            pass
    if not audio_file:
        raise HTTPException(status_code=404, detail="文件不存在")

    if current_user.role != "admin" and audio_file.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权查看此文件")

    # 获取关联的全部分析报告（三种类型）
    reports_list = db.query(AnalysisReport).filter(AnalysisReport.file_id == audio_file.id).all()

    from services.media_service import format_duration

    result = {
        "file_id": audio_file.file_id,
        "original_filename": audio_file.original_filename,
        "file_size": audio_file.file_size,
        "duration": round(audio_file.duration, 1) if audio_file.duration else None,
        "duration_formatted": format_duration(audio_file.duration) if audio_file.duration else None,
        "file_format": audio_file.file_format,
        "upload_status": audio_file.upload_status,
        "asr_text": audio_file.asr_text,
        "created_at": audio_file.created_at.isoformat() if audio_file.created_at else None,
        "reports": {}
    }

    for r in reports_list:
        import json as _json
        result["reports"][r.report_type] = {
            "report_id": r.report_id,
            "status": r.status,
            "data": r.report_data,
            "user_edited_data": r.user_edited_data if hasattr(r, 'user_edited_data') else None,
            "supplementary_text": r.supplementary_text if hasattr(r, 'supplementary_text') else None,
            "expert_notes": r.expert_notes if hasattr(r, 'expert_notes') else None,
            "photos": r.photos if hasattr(r, 'photos') else [],
            "share_id": r.share_id if hasattr(r, 'share_id') else None,
            "error_message": r.error_message,
            "created_at": r.created_at.isoformat() if r.created_at else None
        }

    return result


# ==================== 手动上传 & 合并分析 ====================

@router.post("/files/upload-analyze")
async def admin_upload_analyze(
    file: UploadFile = File(...),
    task_types: str = Form(None),  # 逗号分隔，为空则取默认类型；前端放 FormData 发送，必须声明为 Form
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    【后台手动上传】上传本地录音文件，走完整 ASR→LLM 分析流程。
    task_types 为空时使用所有 is_default=True 的任务类型。
    """
    allowed_exts = {".mp3", ".m4a", ".wav", ".amr", ".3gp"}
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed_exts:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型，请上传 {'/'.join(allowed_exts)}")

    file_id = None
    try:
        file_id, file_path, duration = await save_audio_file(file)
        fmt = Path(file_path).suffix.replace(".", "")

        audio_file = AudioFile(
            file_id=file_id,
            user_id=current_user.id,
            original_filename=file.filename,
            stored_filename=Path(file_path).name,
            file_path=file_path,
            file_size=Path(file_path).stat().st_size,
            duration=duration,
            file_format=fmt,
            upload_status=UploadStatus.PROCESSING.value
        )
        db.add(audio_file)
        db.commit()
        db.refresh(audio_file)

        asr_result = await get_asr_service().transcribe(file_path)
        asr_text = asr_result["text"] if asr_result["success"] else ""
        audio_file.asr_text = asr_text
        db.commit()

        if not asr_result["success"]:
            audio_file.upload_status = UploadStatus.FAILED.value
            db.commit()
            raise HTTPException(status_code=502, detail=f"ASR转写失败: {asr_result.get('error')}")

        selected = [t.strip() for t in task_types.split(",")] if task_types else None
        active_types = _get_task_types(db, selected) or _get_task_types(db, None)
        tasks = [
            get_llm_service().analyze(text=asr_text, report_type=rt, db=db)
            for rt in active_types
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        reports_output = {}
        for rt, result in zip(active_types, results):
            if isinstance(result, Exception):
                logger.error(f"报告生成异常({rt}): {result}")
                report = AnalysisReport(
                    file_id=audio_file.id,
                    user_id=current_user.id,
                    report_type=rt,
                    status=AnalysisStatus.FAILED.value,
                    error_message=str(result)
                )
            else:
                success = result.get("success", False)
                report = AnalysisReport(
                    file_id=audio_file.id,
                    user_id=current_user.id,
                    report_type=rt,
                    status=AnalysisStatus.COMPLETED.value if success else AnalysisStatus.FAILED.value,
                    report_data=result.get("data"),
                    error_message=result.get("error") if not success else None
                )
            db.add(report)
            db.flush()
            reports_output[rt] = {
                "report_id": report.report_id,
                "status": report.status,
                "data": report.report_data
            }

        audio_file.upload_status = UploadStatus.COMPLETED.value
        db.commit()

        return {
            "success": True,
            "file_id": file_id,
            "asr_text": asr_text,
            "reports": reports_output
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"后台上传分析异常: {e}")
        if file_id:
            af = db.query(AudioFile).filter(AudioFile.file_id == file_id).first()
            if af:
                af.upload_status = UploadStatus.FAILED.value
                db.commit()
        raise HTTPException(status_code=500, detail=str(e))


class MergeAnalyzeRequest(BaseModel):
    file_ids: list[str]


@router.post("/analyze/merge")
async def merge_analyze(
    request: MergeAnalyzeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    【合并分析】将多段已完成 ASR 的录音文件按顺序合并转写文本，统一生成三份报告。
    用于处理因分段录制产生的多个文件。
    file_ids 按先后顺序传入。
    """
    if len(request.file_ids) < 2:
        raise HTTPException(status_code=400, detail="至少需要选择 2 个文件进行合并分析")

    # 查询所有文件，校验权限和 ASR 状态
    audio_files = []
    for fid in request.file_ids:
        af = db.query(AudioFile).filter(AudioFile.file_id == fid).first()
        if not af:
            raise HTTPException(status_code=404, detail=f"文件 {fid} 不存在")
        if current_user.role != "admin" and af.user_id != current_user.id:
            raise HTTPException(status_code=403, detail=f"无权访问文件 {fid}")
        if not af.asr_text:
            raise HTTPException(status_code=400, detail=f"文件 {af.original_filename} 尚未完成 ASR 转写")
        audio_files.append(af)

    # 按传入顺序拼接转写文本
    merged_text = "\n\n".join(
        f"[片段{i+1}]\n{af.asr_text}" for i, af in enumerate(audio_files)
    )

    # 创建合并记录（虚拟 AudioFile，无实际音频文件）
    total_duration = sum((af.duration or 0) for af in audio_files)
    source_names = "、".join(af.original_filename or af.file_id for af in audio_files)
    merged_filename = f"合并分析_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    merged_file = AudioFile(
        file_id=str(uuid.uuid4()),
        user_id=current_user.id,
        original_filename=merged_filename,
        stored_filename=merged_filename,
        file_path="",
        file_size=0,
        duration=total_duration,
        file_format="merged",
        upload_status=UploadStatus.PROCESSING.value,
        asr_text=merged_text
    )
    db.add(merged_file)
    db.commit()
    db.refresh(merged_file)

    # 并发生成报告（动态类型）
    active_types = _get_task_types(db, None)
    tasks = [
        get_llm_service().analyze(text=merged_text, report_type=rt, db=db)
        for rt in active_types
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    reports_output = {}
    for rt, result in zip(active_types, results):
        if isinstance(result, Exception):
            logger.error(f"合并报告生成异常({rt}): {result}")
            report = AnalysisReport(
                file_id=merged_file.id,
                user_id=current_user.id,
                report_type=rt,
                status=AnalysisStatus.FAILED.value,
                error_message=str(result)
            )
        else:
            success = result.get("success", False)
            report = AnalysisReport(
                file_id=merged_file.id,
                user_id=current_user.id,
                report_type=rt,
                status=AnalysisStatus.COMPLETED.value if success else AnalysisStatus.FAILED.value,
                report_data=result.get("data"),
                error_message=result.get("error") if not success else None
            )
        db.add(report)
        db.flush()
        reports_output[rt] = {
            "report_id": report.report_id,
            "status": report.status,
            "data": report.report_data
        }

    merged_file.upload_status = UploadStatus.COMPLETED.value
    db.commit()

    return {
        "success": True,
        "file_id": merged_file.file_id,
        "source_files": source_names,
        "merged_text_length": len(merged_text),
        "reports": reports_output
    }
