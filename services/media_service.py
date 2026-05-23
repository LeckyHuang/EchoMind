#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音视频处理服务 - ffprobe 获取准确的录音时长
"""

import subprocess
import json
import re
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def get_audio_duration(file_path: str) -> float:
    """
    使用 ffprobe 获取音频文件的准确时长（秒）
    如果 ffprobe 不可用或失败，返回 0
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            file_path
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            duration = float(data.get("format", {}).get("duration", 0))
            logger.info(f"ffprobe 获取时长: {file_path} → {duration}s")
            return duration
        else:
            logger.warning(f"ffprobe 获取时长失败: {result.stderr}")
            return 0
            
    except FileNotFoundError:
        logger.warning("ffprobe 未安装，无法获取准确时长")
        return 0
    except Exception as e:
        logger.warning(f"ffprobe 异常: {e}")
        return 0


def format_duration(seconds: float) -> str:
    """
    将秒数格式化为 mm:ss 或 hh:mm:ss
    """
    if seconds <= 0:
        return "00:00"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"
