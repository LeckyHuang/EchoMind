#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件处理工具
"""

import os
import uuid
import asyncio
import aiofiles
import logging
from pathlib import Path
from datetime import datetime
from typing import Tuple, Optional

from config import settings

logger = logging.getLogger(__name__)


async def save_audio_file(file, custom_filename: str = None) -> Tuple[str, str, float]:
    """
    保存上传的音频文件
    :param file: FastAPI UploadFile 对象
    :param custom_filename: 自定义文件名
    :return: (file_id, file_path, duration)
    """
    # 生成文件ID
    file_id = custom_filename or str(uuid.uuid4())
    
    # 获取文件扩展名
    original_filename = file.filename or "audio"
    ext = Path(original_filename).suffix.lower()
    
    # 标准扩展名映射
    ext_map = {
        ".mp3": ".mp3",
        ".m4a": ".m4a",
        ".amr": ".amr",
        ".wav": ".wav",
        ".3gp": ".3gp",
        ".aac": ".aac",
        ".ogg": ".ogg"
    }
    
    if ext not in ext_map:
        ext = ".mp3"
    
    filename = f"{file_id}{ext}"
    file_path = Path(settings.UPLOAD_DIR) / filename
    
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    
    # 写入文件
    content = await file.read()
    file_size = len(content)
    
    max_size = settings.MAX_FILE_SIZE * 1024 * 1024
    if file_size > max_size:
        raise ValueError(f"文件大小超过限制 ({settings.MAX_FILE_SIZE}MB)")
    
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)
    
    # 用 ffprobe 获取准确时长
    from services.media_service import get_audio_duration
    duration = get_audio_duration(str(file_path))
    
    # ffprobe 失败时用估算值兜底
    if duration <= 0:
        duration = file_size / (16 * 1024)  # 128kbps 估算
    
    logger.info(f"文件保存成功: {file_id}, 大小: {file_size/1024:.1f}KB, 时长: {duration:.1f}s")
    
    return file_id, str(file_path), duration


async def cleanup_old_files(max_age_hours: int = None):
    """
    清理过期文件
    :param max_age_hours: 最大保留时间（小时），None 则使用配置值
    """
    if max_age_hours is None:
        max_age_hours = settings.FILE_EXPIRE_HOURS
    
    upload_dir = Path(settings.UPLOAD_DIR)
    if not upload_dir.exists():
        return
    
    now = datetime.now()
    max_age_seconds = max_age_hours * 3600
    cleaned_count = 0
    
    try:
        for file_path in upload_dir.iterdir():
            if not file_path.is_file():
                continue
            file_age = (now - datetime.fromtimestamp(file_path.stat().st_mtime)).total_seconds()
            if file_age > max_age_seconds:
                file_path.unlink()
                cleaned_count += 1
                logger.info(f"清理过期文件: {file_path.name}")
    except Exception as e:
        logger.error(f"清理文件异常: {e}")
    
    if cleaned_count > 0:
        logger.info(f"共清理 {cleaned_count} 个过期文件")


def get_file_info(file_id: str) -> Optional[dict]:
    """
    获取文件信息
    :param file_id: 文件ID
    :return: 文件信息字典，不存在则返回None
    """
    upload_dir = Path(settings.UPLOAD_DIR)
    
    for ext in [".mp3", ".m4a", ".amr", ".wav", ".3gp", ".aac"]:
        file_path = upload_dir / f"{file_id}{ext}"
        if file_path.exists():
            stat = file_path.stat()
            return {
                "file_id": file_id,
                "filename": file_path.name,
                "size": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
            }
    
    return None
