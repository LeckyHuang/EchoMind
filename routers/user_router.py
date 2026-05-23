#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户管理 API - 管理后台调用
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc

from models import get_db, User
from auth import get_current_user, get_current_admin


router = APIRouter(prefix="/api/v1/admin", tags=["用户管理"])


# ==================== 请求/响应模型 ====================

class UserResponse(BaseModel):
    id: int
    user_id: str
    username: str
    email: str | None
    role: str
    is_active: bool
    created_at: str | None

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    total: int
    users: list[UserResponse]


class UserCreate(BaseModel):
    username: str
    email: str | None = None
    password: str | None = None
    role: str = "user"


class UserUpdate(BaseModel):
    email: str | None = None
    password: str | None = None
    role: str | None = None


class ToggleStatusRequest(BaseModel):
    is_active: bool


# ==================== 用户列表 ====================

@router.get("/users", response_model=UserListResponse)
async def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    获取所有用户列表（仅管理员）
    """
    users = db.query(User).order_by(desc(User.created_at)).all()
    return UserListResponse(
        total=len(users),
        users=[
            UserResponse(
                id=u.id,
                user_id=u.user_id,
                username=u.username,
                email=u.email,
                role=u.role,
                is_active=u.is_active,
                created_at=u.created_at.isoformat() if u.created_at else None
            )
            for u in users
        ]
    )


# ==================== 单个用户 ====================

@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    获取指定用户信息（仅管理员）
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return UserResponse(
        id=user.id,
        user_id=user.user_id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else None
    )


# ==================== 创建用户 ====================

@router.post("/users", response_model=UserResponse)
async def create_user(
    request: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    创建新用户（仅管理员）
    """
    # 检查用户名唯一
    existing = db.query(User).filter(User.username == request.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")

    if request.email:
        existing_email = db.query(User).filter(User.email == request.email).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="邮箱已被使用")

    if not request.password:
        raise HTTPException(status_code=400, detail="密码不能为空")

    # 角色白名单校验
    valid_roles = {"admin", "user"}
    if request.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"无效的角色，只允许: {', '.join(valid_roles)}")

    user = User(
        username=request.username,
        email=request.email,
        password_hash=User.hash_password(request.password),
        role=request.role
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return UserResponse(
        id=user.id,
        user_id=user.user_id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else None
    )


# ==================== 更新用户 ====================

@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    request: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    更新用户信息（仅管理员）
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if request.email is not None and request.email != user.email:
        existing_email = db.query(User).filter(User.email == request.email, User.id != user_id).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="邮箱已被使用")
        user.email = request.email

    if request.password:
        user.password_hash = User.hash_password(request.password)

    if request.role is not None:
        user.role = request.role

    db.commit()
    db.refresh(user)

    return UserResponse(
        id=user.id,
        user_id=user.user_id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else None
    )


# ==================== 删除用户 ====================

@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    删除用户（仅管理员，不允许删除自己）
    """
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    db.delete(user)
    db.commit()
    return {"success": True, "message": "用户已删除"}


# ==================== 重置密码 ====================

@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    重置用户密码为默认值（仅管理员）
    默认密码：User123456
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    default_password = "User123456"
    user.password_hash = User.hash_password(default_password)
    db.commit()

    return {
        "success": True,
        "message": "密码已重置为默认值",
        "password": default_password
    }


# ==================== 切换用户状态 ====================

@router.post("/users/{user_id}/toggle-status")
async def toggle_user_status(
    user_id: int,
    request: ToggleStatusRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    启用/禁用用户（仅管理员，不允许禁用自己）
    """
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能禁用自己")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.is_active = request.is_active
    db.commit()

    return {
        "success": True,
        "is_active": user.is_active
    }
