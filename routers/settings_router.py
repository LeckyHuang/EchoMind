#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统设置 API
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models import get_db, User, SystemSetting, PromptTemplate
from auth import get_current_user, get_current_admin
from config import settings, asr_settings, llm_settings


router = APIRouter(prefix="/api/v1/admin", tags=["系统设置"])


# ==================== 请求模型 ====================

class SettingsUpdate(BaseModel):
    cleanup_expire_hours: int | None = None
    cleanup_cron: str | None = None
    active_prompt_id: int | None = None


# ==================== 获取设置 ====================

@router.get("/settings")
async def get_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    获取系统设置
    """
    # 默认值与清理任务（scheduler.get_cleanup_expire_hours / init_scheduler）保持一致
    cleanup_expire_hours = SystemSetting.get_setting(db, "cleanup_expire_hours", str(settings.FILE_EXPIRE_HOURS))
    cleanup_cron = SystemSetting.get_setting(db, "cleanup_cron", "0 3 * * *")
    active_prompt_id = SystemSetting.get_setting(db, "active_prompt_id", None)

    # 获取当前激活的 prompt 模板
    active_template = db.query(PromptTemplate).filter(
        PromptTemplate.is_active == True
    ).first()

    return {
        "cleanup_expire_hours": int(cleanup_expire_hours),
        "cleanup_cron": cleanup_cron,
        "active_prompt_id": int(active_prompt_id) if active_prompt_id else None,
        "active_prompt_name": active_template.name if active_template else None
    }


# ==================== 更新设置 ====================

@router.put("/settings")
async def update_settings(
    request: SettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    更新系统设置（仅管理员）
    """
    if request.cleanup_expire_hours is not None:
        if request.cleanup_expire_hours < 1:
            raise HTTPException(status_code=400, detail="过期时间必须大于0")
        SystemSetting.set_setting(
            db, "cleanup_expire_hours", str(request.cleanup_expire_hours),
            "录音物理文件过期时间（小时），报告与记录永久保留"
        )

    if request.cleanup_cron is not None:
        SystemSetting.set_setting(
            db, "cleanup_cron", request.cleanup_cron,
            "清理任务 Cron 表达式"
        )

    if request.active_prompt_id is not None:
        # 更新 prompt 激活状态
        db.query(PromptTemplate).filter(
            PromptTemplate.is_active == True
        ).update({"is_active": False})

        template = db.query(PromptTemplate).filter(
            PromptTemplate.id == request.active_prompt_id
        ).first()
        if not template:
            raise HTTPException(status_code=404, detail="Prompt 模板不存在")
        template.is_active = True
        SystemSetting.set_setting(
            db, "active_prompt_id", str(request.active_prompt_id),
            "当前激活的 Prompt 模板 ID"
        )
        db.commit()
    elif request.active_prompt_id is None and "active_prompt_id" in request.model_fields_set():
        # 显式传 null 表示取消激活
        db.query(PromptTemplate).filter(
            PromptTemplate.is_active == True
        ).update({"is_active": False})
        SystemSetting.set_setting(db, "active_prompt_id", "", "")
        db.commit()

    return {"success": True, "message": "设置已保存"}


# ==================== 服务商信息 ====================

@router.get("/settings/providers")
async def get_service_providers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    获取当前配置的服务商信息（只读）
    """
    asr_provider = getattr(asr_settings, "PROVIDER", "qwen").upper()
    llm_provider = getattr(llm_settings, "PROVIDER", "minimax").upper()

    # ASR 模型映射
    asr_models = {
        "qwen": "Paraformer语音模型",
        "doubao": "字节豆包 ASR",
        "tencent": "腾讯云 ASR",
        "baidu": "百度 ASR"
    }

    # LLM 模型映射
    llm_models = {
        "minimax": "MiniMax GLM-4",
        "kimi": "Kimi Moonshot V1",
        "qwen": "通义千问 V2",
        "doubao": "字节豆包 Pro",
        "zhipu": "智谱 GLM-4"
    }

    return {
        "asr_provider": asr_provider,
        "asr_model": asr_models.get(asr_provider.lower(), "未知"),
        "llm_provider": llm_provider,
        "llm_model": llm_models.get(llm_provider.lower(), "未知"),
        "debug_mode": getattr(settings, "DEBUG", True),
        "upload_dir": str(getattr(settings, "UPLOAD_DIR", "./uploads"))
    }
