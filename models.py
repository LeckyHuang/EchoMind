#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库模型 - SQLAlchemy ORM
使用 SQLite（后续可迁移到 PostgreSQL/MySQL）
"""

import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    create_engine, Column, String, Integer, Float, Boolean,
    DateTime, Text, ForeignKey, JSON, Enum, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.sql import func
from passlib.context import CryptContext
import enum

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent

# 数据库路径
DATABASE_URL = f"sqlite:///{BASE_DIR}/data/echodmind.db"

# 创建引擎
engine = create_engine(
    DATABASE_URL,
    echo=False,  # 改为 True 可打印 SQL 日志
    connect_args={"check_same_thread": False}
)

# Session 工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 密码加密
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==================== 枚举类型 ====================

class UserRole(str, enum.Enum):
    """用户角色"""
    ADMIN = "admin"       # 管理员
    USER = "user"        # 普通用户


class UploadStatus(str, enum.Enum):
    """上传状态"""
    PENDING = "pending"      # 等待处理
    PROCESSING = "processing"  # 处理中
    COMPLETED = "completed"    # 完成
    FAILED = "failed"          # 失败


class AnalysisStatus(str, enum.Enum):
    """分析状态"""
    PENDING = "pending"        # 等待分析
    PROCESSING = "processing"  # 分析中
    COMPLETED = "completed"    # 完成
    FAILED = "failed"          # 失败


# ==================== 数据模型 ====================

Base = declarative_base()


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default=UserRole.USER.value)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # 关系
    audio_files = relationship("AudioFile", back_populates="user", cascade="all, delete-orphan")
    analysis_reports = relationship("AnalysisReport", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"

    def verify_password(self, password: str) -> bool:
        """验证密码"""
        return pwd_context.verify(password, self.password_hash)

    @staticmethod
    def hash_password(password: str) -> str:
        """哈希密码"""
        return pwd_context.hash(password)

    def to_dict(self, safe: bool = True):
        """转为字典"""
        data = {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        return data


class AudioFile(Base):
    """录音文件表"""
    __tablename__ = "audio_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # 文件信息
    original_filename = Column(String(255), nullable=True)  # 原始文件名
    stored_filename = Column(String(255), nullable=False)   # 存储文件名（UUID）
    file_path = Column(String(500), nullable=False)        # 完整存储路径
    file_size = Column(Integer, nullable=True)             # 文件大小（字节）
    duration = Column(Float, nullable=True)                # 录音时长（秒，ffprobe准确获取）
    file_format = Column(String(20), nullable=True)        # 文件格式 mp3/m4a/wav
    
    # 状态
    upload_status = Column(String(20), default=UploadStatus.PENDING.value)
    asr_text = Column(Text, nullable=True)                 # ASR转写文本
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # 关系
    user = relationship("User", back_populates="audio_files")
    analysis_reports = relationship("AnalysisReport", back_populates="audio_file", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<AudioFile(id={self.id}, file_id={self.file_id}, filename={self.original_filename})>"

    def to_dict(self):
        """转为字典"""
        return {
            "id": self.id,
            "file_id": self.file_id,
            "user_id": self.user_id,
            "original_filename": self.original_filename,
            "file_size": self.file_size,
            "duration": self.duration,
            "file_format": self.file_format,
            "upload_status": self.upload_status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AnalysisReport(Base):
    """分析报告表"""
    __tablename__ = "analysis_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    file_id = Column(Integer, ForeignKey("audio_files.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # 报告类型: customer_brief(接待简报) | business_opportunity(商机线索) | reception_review(接待复盘)
    report_type = Column(String(50), nullable=False, default="meeting_analysis", index=True)

    # 分析结果（JSON 格式存储完整的 LLM 输出）
    report_data = Column(JSON, nullable=True)

    # 用户编辑数据
    user_edited_data = Column(JSON, nullable=True)   # 用户对结构化字段的覆盖
    supplementary_text = Column(Text, nullable=True)  # 用户自由文字补充
    expert_notes = Column(Text, nullable=True)        # 专家讲解（接待复盘专用）
    photos = Column(JSON, nullable=True)              # 照片列表 [{"id","type","url","caption"}]
    share_id = Column(String(36), nullable=True)      # 已生成的分享页 UUID（不为空则说明已生成）

    # 状态
    status = Column(String(20), default=AnalysisStatus.PENDING.value)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # 关系
    audio_file = relationship("AudioFile", back_populates="analysis_reports")
    user = relationship("User", back_populates="analysis_reports")

    def __repr__(self):
        return f"<AnalysisReport(id={self.id}, report_id={self.report_id}, status={self.status})>"

    def to_dict(self):
        """转为字典"""
        return {
            "id": self.id,
            "report_id": self.report_id,
            "file_id": self.file_id,
            "user_id": self.user_id,
            "report_type": self.report_type,
            "status": self.status,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PromptTemplate(Base):
    """Prompt 模板表"""
    __tablename__ = "prompt_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    content = Column(Text, nullable=False)  # Prompt 模板内容
    is_active = Column(Boolean, default=False)  # 是否为当前激活的模板
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = ()

    def __repr__(self):
        return f"<PromptTemplate(id={self.id}, name={self.name}, active={self.is_active})>"

    def to_dict(self):
        """转为字典"""
        return {
            "id": self.id,
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "content": self.content,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SystemSetting(Base):
    """系统设置表"""
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<SystemSetting(key={self.key}, value={self.value})>"

    @staticmethod
    def get_setting(db, key: str, default=None):
        """获取设置值"""
        setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        return setting.value if setting else default

    @staticmethod
    def set_setting(db, key: str, value: str, description: str = None):
        """设置值"""
        setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if setting:
            setting.value = value
            if description:
                setting.description = description
        else:
            setting = SystemSetting(key=key, value=value, description=description)
            db.add(setting)
        db.commit()
        return setting


class AnalysisTaskType(Base):
    """分析任务类型表 — 动态定义可生成的报告/分析类型"""
    __tablename__ = "analysis_task_types"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type_id = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    name = Column(String(100), unique=True, nullable=False)          # slug，如 "customer_brief"
    display_name = Column(String(100), nullable=False)               # 显示名，如 "参观简报"
    description = Column(Text, nullable=True)
    prompt_key = Column(String(100), nullable=True)                  # prompt_templates.name，分析用
    share_prompt_key = Column(String(100), nullable=True)            # 分享页叙事化 prompt（可空）
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)                      # 兼容旧字段，由 default_rank 派生
    default_rank = Column(Integer, default=0)                        # 0=不默认，1/2/3=第1/2/3默认（最多3个）
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<AnalysisTaskType(name={self.name}, rank={self.default_rank})>"

    def to_dict(self):
        return {
            "id": self.id,
            "type_id": self.type_id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "prompt_key": self.prompt_key,
            "share_prompt_key": self.share_prompt_key,
            "is_active": self.is_active,
            "is_default": self.default_rank > 0,   # 向后兼容
            "default_rank": self.default_rank,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ==================== 初始化数据库 ====================

def init_db():
    """初始化数据库，创建所有表"""
    # 确保 data 目录存在
    data_dir = BASE_DIR / "data"
    data_dir.mkdir(exist_ok=True)
    
    # 创建所有表
    Base.metadata.create_all(bind=engine)
    print(f"✅ 数据库初始化完成: {BASE_DIR}/data/echodmind.db")


def drop_db():
    """删除所有表（慎用）"""
    Base.metadata.drop_all(bind=engine)
    print("✅ 数据库表已删除")


if __name__ == "__main__":
    init_db()
