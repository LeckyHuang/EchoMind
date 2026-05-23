#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析任务类型管理 API
- CRUD 已安装的任务类型
- 浏览预设库 + 一键安装（自动创建 PromptTemplate 副本）
- default_rank 校验：最多 3 个，值为 1/2/3，同一 rank 不可重复
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models import get_db, AnalysisTaskType, PromptTemplate
from auth import get_current_user, get_current_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["任务类型管理"])


# ==================== 数据模型 ====================

class TaskTypeCreate(BaseModel):
    name: str
    display_name: str
    description: Optional[str] = None
    prompt_key: Optional[str] = None
    share_prompt_key: Optional[str] = None
    default_rank: int = 0
    sort_order: int = 0


class TaskTypeUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    prompt_key: Optional[str] = None
    share_prompt_key: Optional[str] = None
    is_active: Optional[bool] = None
    default_rank: Optional[int] = None
    sort_order: Optional[int] = None


# ==================== 已安装类型管理 ====================

@router.get("/task-types")
async def list_task_types(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """获取所有任务类型（含停用），按 default_rank 排序"""
    types = db.query(AnalysisTaskType).order_by(
        AnalysisTaskType.default_rank.desc(),
        AnalysisTaskType.sort_order
    ).all()
    return {"task_types": [t.to_dict() for t in types]}


@router.post("/task-types")
async def create_task_type(
    req: TaskTypeCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin)
):
    """手动新建分析任务类型"""
    if db.query(AnalysisTaskType).filter(AnalysisTaskType.name == req.name).first():
        raise HTTPException(status_code=409, detail=f"类型名 '{req.name}' 已存在")
    if req.default_rank not in (0, 1, 2, 3):
        raise HTTPException(status_code=400, detail="default_rank 只能为 0/1/2/3")
    if req.default_rank > 0:
        _ensure_rank_free(db, req.default_rank, exclude_id=None)
    t = AnalysisTaskType(
        name=req.name,
        display_name=req.display_name,
        description=req.description,
        prompt_key=req.prompt_key or req.name,
        share_prompt_key=req.share_prompt_key,
        is_default=req.default_rank > 0,
        default_rank=req.default_rank,
        sort_order=req.sort_order,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"success": True, "task_type": t.to_dict()}


@router.patch("/task-types/{type_id}")
async def update_task_type(
    type_id: str,
    req: TaskTypeUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin)
):
    """更新任务类型（含调整 default_rank）"""
    t = db.query(AnalysisTaskType).filter(AnalysisTaskType.type_id == type_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="任务类型不存在")

    if req.default_rank is not None:
        if req.default_rank not in (0, 1, 2, 3):
            raise HTTPException(status_code=400, detail="default_rank 只能为 0/1/2/3")
        if req.default_rank > 0:
            _ensure_rank_free(db, req.default_rank, exclude_id=t.id)
        t.default_rank = req.default_rank
        t.is_default = req.default_rank > 0

    for field in ("display_name", "description", "prompt_key", "share_prompt_key", "is_active", "sort_order"):
        val = getattr(req, field, None)
        if val is not None:
            setattr(t, field, val)

    db.commit()
    db.refresh(t)
    return {"success": True, "task_type": t.to_dict()}


@router.delete("/task-types/{type_id}")
async def delete_task_type(
    type_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin)
):
    """删除任务类型（建议用停用代替删除）"""
    t = db.query(AnalysisTaskType).filter(AnalysisTaskType.type_id == type_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="任务类型不存在")
    db.delete(t)
    db.commit()
    return {"success": True}


# ==================== 预设类型库 ====================

@router.get("/type-presets")
async def list_type_presets(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    返回全部预置类型（含安装状态）。
    installed=True 表示该预设已在 analysis_task_types 表中。
    """
    from presets_library import get_all_presets
    installed_names = {
        t.name for t in db.query(AnalysisTaskType.name).all()
    }
    result = []
    for p in get_all_presets():
        result.append({
            "name": p["name"],
            "display_name": p["display_name"],
            "description": p["description"],
            "category": p.get("category", "通用"),
            "installed": p["name"] in installed_names,
        })
    return {"presets": result}


@router.post("/type-presets/{name}/install")
async def install_preset(
    name: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin)
):
    """
    安装预置类型：
    1. 在 prompt_templates 中创建该类型的可编辑 prompt 副本（若已存在则跳过）
    2. 在 analysis_task_types 中创建类型记录
    """
    from presets_library import get_preset, get_preset_prompt

    preset = get_preset(name)
    if not preset:
        raise HTTPException(status_code=404, detail=f"预设类型 '{name}' 不存在")

    exists = db.query(AnalysisTaskType).filter(AnalysisTaskType.name == name).first()
    if exists:
        raise HTTPException(status_code=409, detail=f"类型 '{name}' 已安装")

    # 1. 创建 PromptTemplate（用户可编辑的副本）
    prompt_key = name
    tpl = db.query(PromptTemplate).filter(PromptTemplate.name == prompt_key).first()
    if not tpl:
        prompt_content = get_preset_prompt(name)
        tpl = PromptTemplate(
            name=prompt_key,
            description=f"[{preset['display_name']}] {preset['description']}",
            content=prompt_content,
            is_active=True,
        )
        db.add(tpl)
        db.flush()
        logger.info(f"预设 prompt 写入: {prompt_key}")

    # 2. 创建 AnalysisTaskType
    t = AnalysisTaskType(
        name=name,
        display_name=preset["display_name"],
        description=preset["description"],
        prompt_key=prompt_key,
        share_prompt_key=None,
        is_default=False,
        default_rank=0,
        sort_order=100,  # 用户自定义类型排在内置类型后面
    )
    db.add(t)
    db.commit()
    db.refresh(t)

    return {"success": True, "task_type": t.to_dict()}


@router.post("/type-presets/{name}/reset-prompt")
async def reset_preset_prompt(
    name: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin)
):
    """将某类型的 prompt 恢复为系统预设默认值"""
    from presets_library import get_preset_prompt

    prompt_content = get_preset_prompt(name)
    if not prompt_content:
        raise HTTPException(status_code=404, detail=f"预设类型 '{name}' 不存在，无法重置")

    tpl = db.query(PromptTemplate).filter(
        PromptTemplate.name == name,
        PromptTemplate.is_active == True
    ).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="未找到对应的 Prompt 模板")

    tpl.content = prompt_content
    db.commit()
    return {"success": True, "message": "已恢复为系统默认 Prompt"}


# ==================== 辅助函数 ====================

def _ensure_rank_free(db: Session, rank: int, exclude_id: int | None):
    """确保指定 rank 没有被其他类型占用，若有则清零"""
    q = db.query(AnalysisTaskType).filter(AnalysisTaskType.default_rank == rank)
    if exclude_id is not None:
        q = q.filter(AnalysisTaskType.id != exclude_id)
    existing = q.first()
    if existing:
        existing.default_rank = 0
        existing.is_default = False
        logger.info(f"已将 {existing.name} 的 default_rank 从 {rank} 清零")
