#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prompt 模板管理 API + 报告管理 API
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime

from models import get_db, User, PromptTemplate, AnalysisReport, AudioFile
from auth import get_current_user, get_current_admin

router = APIRouter(prefix="/api/v1/admin", tags=["Prompt管理与报告"])


# ==================== Prompt 模板管理 ====================

class PromptTemplateResponse(BaseModel):
    id: int
    template_id: str
    name: str
    description: str | None
    content: str
    is_active: bool
    created_at: str | None
    updated_at: str | None

    class Config:
        from_attributes = True


class PromptTemplateCreate(BaseModel):
    name: str
    description: str | None = None
    content: str
    is_active: bool = False


class PromptTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    is_active: bool | None = None


class PromptPreviewRequest(BaseModel):
    content: str
    sample_text: str = "这是一段示例会议录音的文字内容..."


class PromptListResponse(BaseModel):
    prompts: list


@router.get("/prompts")
async def list_prompts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    获取所有 Prompt 模板列表
    """
    templates = db.query(PromptTemplate).order_by(desc(PromptTemplate.is_active), PromptTemplate.name).all()
    return PromptListResponse(
        prompts=[
            PromptTemplateResponse(
                id=t.id,
                template_id=t.template_id,
                name=t.name,
                description=t.description,
                content=t.content,
                is_active=t.is_active,
                created_at=t.created_at.isoformat() if t.created_at else None,
                updated_at=t.updated_at.isoformat() if t.updated_at else None
            ) for t in templates
        ]
    )


@router.get("/prompts/{template_id}", response_model=PromptTemplateResponse)
async def get_prompt(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    获取单个 Prompt 模板详情
    """
    template = db.query(PromptTemplate).filter(PromptTemplate.template_id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    return PromptTemplateResponse(
        id=template.id,
        template_id=template.template_id,
        name=template.name,
        description=template.description,
        content=template.content,
        is_active=template.is_active,
        created_at=template.created_at.isoformat() if template.created_at else None,
        updated_at=template.updated_at.isoformat() if template.updated_at else None
    )


@router.post("/prompts", response_model=PromptTemplateResponse)
async def create_prompt(
    request: PromptTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    创建 Prompt 模板（仅管理员）
    """
    # 若新建即激活，先把同名（同报告类型）其他激活模板关闭
    if request.is_active:
        db.query(PromptTemplate).filter(
            PromptTemplate.is_active == True,
            PromptTemplate.name == request.name
        ).update({"is_active": False})

    template = PromptTemplate(
        name=request.name,
        description=request.description,
        content=request.content,
        is_active=request.is_active
    )
    db.add(template)
    db.commit()
    db.refresh(template)

    return PromptTemplateResponse(
        id=template.id,
        template_id=template.template_id,
        name=template.name,
        description=template.description,
        content=template.content,
        is_active=template.is_active,
        created_at=template.created_at.isoformat() if template.created_at else None,
        updated_at=template.updated_at.isoformat() if template.updated_at else None
    )


@router.put("/prompts/{template_id}", response_model=PromptTemplateResponse)
async def update_prompt(
    template_id: str,
    request: PromptTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    更新 Prompt 模板（仅管理员）
    """
    template = db.query(PromptTemplate).filter(PromptTemplate.template_id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    if request.name is not None:
        template.name = request.name

    if request.description is not None:
        template.description = request.description
    if request.content is not None:
        template.content = request.content
    if request.is_active is not None:
        # 如果激活此模板，先取消同名（同报告类型）的其他激活状态
        if request.is_active:
            db.query(PromptTemplate).filter(
                PromptTemplate.is_active == True,
                PromptTemplate.name == template.name,
                PromptTemplate.template_id != template_id
            ).update({"is_active": False})
        template.is_active = request.is_active

    db.commit()
    db.refresh(template)

    return PromptTemplateResponse(
        id=template.id,
        template_id=template.template_id,
        name=template.name,
        description=template.description,
        content=template.content,
        is_active=template.is_active,
        created_at=template.created_at.isoformat() if template.created_at else None,
        updated_at=template.updated_at.isoformat() if template.updated_at else None
    )


@router.delete("/prompts/{template_id}")
async def delete_prompt(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    删除 Prompt 模板（仅管理员）
    """
    template = db.query(PromptTemplate).filter(PromptTemplate.template_id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    db.delete(template)
    db.commit()
    return {"success": True, "message": "模板已删除"}


@router.post("/prompts/preview")
async def preview_prompt(
    request: PromptPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    预览 Prompt 效果（用示例文本测试 Prompt）
    """
    # 把 {text} 替换成示例文本
    preview_prompt = request.content.replace("{text}", request.sample_text)
    return {
        "preview_prompt": preview_prompt,
        "note": "这是将 {text} 替换为示例文本后的完整 Prompt，可复制到 LLM 中测试效果"
    }


class ToggleActiveRequest(BaseModel):
    is_active: bool


@router.post("/prompts/{template_id}/toggle")
async def toggle_prompt_active(
    template_id: str,
    request: ToggleActiveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    切换 Prompt 模板激活状态（仅管理员）
    """
    template = db.query(PromptTemplate).filter(PromptTemplate.template_id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    if request.is_active:
        # 仅取消同名（同报告类型）的其他激活模板，不影响其他类型
        db.query(PromptTemplate).filter(
            PromptTemplate.is_active == True,
            PromptTemplate.name == template.name,
            PromptTemplate.template_id != template_id
        ).update({"is_active": False})
    template.is_active = request.is_active
    db.commit()
    return {"success": True, "is_active": template.is_active}


class PromptVariablesRequest(BaseModel):
    variables: dict = {}


@router.post("/prompts/{template_id}/preview")
async def preview_prompt_by_id(
    template_id: str,
    request: PromptVariablesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    预览指定模板的效果（将变量占位符替换为传入值）
    """
    template = db.query(PromptTemplate).filter(PromptTemplate.template_id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    preview_prompt = template.content
    for key, value in request.variables.items():
        preview_prompt = preview_prompt.replace(f"{{{key}}}", str(value))

    return {
        "preview_prompt": preview_prompt,
        "note": "已将模板中的变量占位符替换为传入值，可复制到 LLM 中测试效果"
    }


# ==================== 报告管理 ====================

class ReportResponse(BaseModel):
    id: int
    report_id: str
    file_id: str
    status: str
    created_at: str | None
    audio_filename: str | None

    class Config:
        from_attributes = True


class ReportListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int
    reports: list


@router.get("/reports", response_model=ReportListResponse)
async def list_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取分析报告列表（分页）
    """
    if current_user.role == "admin":
        query = db.query(AnalysisReport)
    else:
        query = db.query(AnalysisReport).filter(AnalysisReport.user_id == current_user.id)

    if status:
        query = query.filter(AnalysisReport.status == status)

    if date_from:
        try:
            from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(AnalysisReport.created_at >= from_dt)
        except ValueError:
            pass

    if date_to:
        try:
            to_dt = datetime.strptime(date_to, "%Y-%m-%d")
            to_dt = to_dt.replace(hour=23, minute=59, second=59)
            query = query.filter(AnalysisReport.created_at <= to_dt)
        except ValueError:
            pass

    total = query.count()
    pages = (total + page_size - 1) // page_size
    offset = (page - 1) * page_size

    reports = query.order_by(desc(AnalysisReport.created_at)).offset(offset).limit(page_size).all()

    result = []
    for r in reports:
        audio_file = db.query(AudioFile).filter(AudioFile.id == r.file_id).first()
        result.append({
            "id": r.id,
            "report_id": r.report_id,
            "file_id": r.file_id,
            "status": r.status,
            "error_message": r.error_message,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "audio_filename": audio_file.original_filename if audio_file else None
        })

    return ReportListResponse(
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
        reports=result
    )


@router.get("/reports/{report_id}")
async def get_report(
    report_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取报告详情
    """
    report = db.query(AnalysisReport).filter(AnalysisReport.report_id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")

    if current_user.role != "admin" and report.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权查看此报告")

    audio_file = db.query(AudioFile).filter(AudioFile.id == report.file_id).first()

    from services.media_service import format_duration

    return {
        "report_id": report.report_id,
        "status": report.status,
        "report_data": report.report_data,
        "error_message": report.error_message,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "audio": {
            "file_id": audio_file.file_id if audio_file else None,
            "original_filename": audio_file.original_filename if audio_file else None,
            "duration": round(audio_file.duration, 1) if audio_file and audio_file.duration else None,
            "duration_formatted": format_duration(audio_file.duration) if audio_file and audio_file.duration else None,
            "asr_text": audio_file.asr_text if audio_file else None
        } if audio_file else None
    }


@router.get("/reports/recent")
async def get_recent_reports(
    limit: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取最近的分析报告（供仪表盘使用）
    """
    base_filter = [] if current_user.role == "admin" else [AnalysisReport.user_id == current_user.id]

    reports = db.query(AnalysisReport).filter(*base_filter).order_by(
        desc(AnalysisReport.created_at)
    ).limit(limit).all()

    result = []
    for r in reports:
        audio_file = db.query(AudioFile).filter(AudioFile.id == r.file_id).first()
        result.append({
            "report_id": r.report_id,
            "file_id": audio_file.file_id if audio_file else None,
            "filename": audio_file.original_filename if audio_file else None,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {"reports": result}


# ==================== 仪表盘统计 ====================

@router.get("/stats")
async def get_admin_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    通用管理统计（供 settings / 其他页面使用）
    """
    from sqlalchemy import func

    base_filter = [] if current_user.role == "admin" else [AudioFile.user_id == current_user.id]

    total_files = db.query(func.count(AudioFile.id)).filter(*base_filter).scalar()
    total_reports = db.query(func.count(AnalysisReport.id)).filter(*base_filter).scalar()

    return {
        "total_files": total_files,
        "total_reports": total_reports,
    }


@router.get("/dashboard/stats")
async def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    仪表盘统计数据
    """
    from sqlalchemy import func

    # 全部/只看自己
    base_filter = [] if current_user.role == "admin" else [AudioFile.user_id == current_user.id]
    report_filter = [] if current_user.role == "admin" else [AnalysisReport.user_id == current_user.id]

    total_files = db.query(func.count(AudioFile.id)).filter(*base_filter).scalar()
    total_reports = db.query(func.count(AnalysisReport.id)).filter(*report_filter).scalar()

    completed_files = db.query(func.count(AudioFile.id)).filter(
        *base_filter, AudioFile.upload_status == "completed"
    ).scalar()

    failed_files = db.query(func.count(AudioFile.id)).filter(
        *base_filter, AudioFile.upload_status == "failed"
    ).scalar()

    total_duration = db.query(func.sum(AudioFile.duration)).filter(*base_filter).scalar() or 0

    # 本月新增
    now = datetime.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0)
    monthly_files = db.query(func.count(AudioFile.id)).filter(
        *base_filter, AudioFile.created_at >= month_start
    ).scalar()

    return {
        "total_files": total_files,
        "total_reports": total_reports,
        "completed_files": completed_files,
        "failed_files": failed_files,
        "pending_files": total_files - completed_files - failed_files,
        "total_duration_seconds": round(total_duration, 1),
        "total_duration_formatted": format_duration(total_duration),
        "monthly_new_files": monthly_files
    }


def format_duration(seconds: float) -> str:
    if seconds <= 0:
        return "00:00"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
