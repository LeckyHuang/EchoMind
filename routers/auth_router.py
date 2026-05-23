#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户认证 API 路由
仅保留登录和当前用户信息，其余用户管理归 user_router
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models import User, get_db
from auth import create_access_token, get_current_user

router = APIRouter(prefix="/api/v1/auth", tags=["认证管理"])


# ==================== 请求/响应模型 ====================

class UserLoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class UserResponse(BaseModel):
    id: int
    user_id: str
    username: str
    email: str | None
    role: str
    is_active: bool
    created_at: str | None


# ==================== 认证接口 ====================

@router.post("/login", response_model=LoginResponse)
async def login(request: UserLoginRequest, db: Session = Depends(get_db)):
    """
    用户登录
    """
    user = db.query(User).filter(
        User.username == request.username,
        User.is_active == True
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )

    if not user.verify_password(request.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )

    from auth import JWT_EXPIRE_HOURS
    token = create_access_token(user)

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=JWT_EXPIRE_HOURS * 3600,
        user=user.to_dict(safe=True)
    )


@router.get("/users/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """
    获取当前登录用户信息
    """
    return UserResponse(**current_user.to_dict())
