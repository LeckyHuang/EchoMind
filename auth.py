#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
认证模块 - JWT Token 鉴权
"""

import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models import User, get_db

# JWT 配置
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY 环境变量未设置。请在启动服务前设置一个强随机密钥，"
        "例如：export JWT_SECRET_KEY=$(python3 -c \"import secrets; print(secrets.token_hex(32))\")"
    )
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "72"))  # 默认72小时

# HTTP Bearer Token
bearer_scheme = HTTPBearer(auto_error=False)


class TokenData(BaseModel):
    """Token 数据"""
    user_id: str
    username: str
    role: str


class TokenResponse(BaseModel):
    """登录响应"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 秒
    user: dict


def create_access_token(user: User) -> str:
    """生成 JWT Token"""
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "sub": user.user_id,
        "username": user.username,
        "role": user.role,
        "exp": expire.timestamp()
    }
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token


def decode_token(token: str) -> Optional[TokenData]:
    """解析 JWT Token"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return TokenData(
            user_id=payload.get("sub"),
            username=payload.get("username"),
            role=payload.get("role", "user")
        )
    except JWTError:
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    获取当前登录用户（需带有效 Token）
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token 已过期或无效，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not credentials:
        raise credentials_exception

    token_data = decode_token(credentials.credentials)
    if not token_data:
        raise credentials_exception

    user = db.query(User).filter(User.user_id == token_data.user_id, User.is_active == True).first()
    if not user:
        raise credentials_exception

    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    获取当前用户（Token 可选，不强制）
    """
    if not credentials:
        return None

    token_data = decode_token(credentials.credentials)
    if not token_data:
        return None

    return db.query(User).filter(User.user_id == token_data.user_id, User.is_active == True).first()


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """
    获取当前用户（仅限管理员）
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限"
        )
    return user
