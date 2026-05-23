#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定时任务调度器
- 定期清理过期录音文件
- 记录清理日志
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from models import SessionLocal, AudioFile, SystemSetting
from utils.file_utils import cleanup_old_files
from config import settings

logger = logging.getLogger(__name__)

# 全局调度器实例
scheduler = AsyncIOScheduler()


def init_scheduler():
    """
    初始化定时任务调度器
    """
    # 从数据库读取清理配置
    cleanup_enabled = SystemSetting.get_setting(SessionLocal(), "cleanup_enabled", "true")
    
    if cleanup_enabled.lower() != "true":
        logger.info("自动清理任务已禁用")
        return
    
    # 默认每天凌晨 3 点执行
    cleanup_cron = SystemSetting.get_setting(SessionLocal(), "cleanup_cron", "0 3 * * *")
    
    # 解析 cron 表达式（简化版：只支持 "minute hour day month weekday"）
    try:
        parts = cleanup_cron.split()
        if len(parts) == 5:
            trigger = CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2] if parts[2] != '*' else None,
                month=parts[3] if parts[3] != '*' else None,
                day_of_week=parts[4] if parts[4] != '*' else None
            )
        else:
            # 默认每天凌晨3点
            trigger = CronTrigger(hour=3, minute=0)
        
        scheduler.add_job(
            scheduled_cleanup,
            trigger=trigger,
            id="cleanup_expired_files",
            name="清理过期录音文件",
            replace_existing=True
        )
        
        logger.info(f"✅ 定时清理任务已注册，执行周期: {cleanup_cron}")
    except Exception as e:
        logger.error(f"❌ 定时任务配置解析失败: {e}，使用默认周期（每天凌晨3点）")
        trigger = CronTrigger(hour=3, minute=0)
        scheduler.add_job(
            scheduled_cleanup,
            trigger=trigger,
            id="cleanup_expired_files",
            name="清理过期录音文件",
            replace_existing=True
        )


async def scheduled_cleanup():
    """
    定时清理任务：清理数据库和物理文件中的过期记录
    """
    logger.info(f"🕐 定时清理任务开始执行 | 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    db = SessionLocal()
    cleaned_physical = 0
    cleaned_db_records = 0
    errors = []
    
    try:
        # 1. 清理物理文件（已实现）
        await cleanup_old_files()
        
        # 2. 清理数据库中的孤立/过期记录
        from datetime import timedelta
        from models import AudioFile, UploadStatus
        
        expire_hours = int(SystemSetting.get_setting(db, "file_expire_hours", "168"))
        expire_time = datetime.now() - timedelta(hours=expire_hours)
        
        # 查找超过7天的已完成文件（即使分析完成了也清理）
        old_files = db.query(AudioFile).filter(
            AudioFile.created_at <= expire_time
        ).all()
        
        for audio_file in old_files:
            try:
                # 删除物理文件
                file_path = Path(settings.UPLOAD_DIR) / audio_file.stored_filename
                if file_path.exists():
                    file_path.unlink()
                    cleaned_physical += 1
                
                # 删除数据库记录（级联删除报告）
                db.delete(audio_file)
                cleaned_db_records += 1
                
            except Exception as e:
                errors.append(f"删除文件 {audio_file.file_id} 失败: {e}")
        
        db.commit()
        
        # 记录清理日志
        log_msg = (
            f"✅ 清理完成 | 物理文件: {cleaned_physical} 个"
            f" | DB记录: {cleaned_db_records} 条"
            f" | 错误: {len(errors)}"
        )
        logger.info(log_msg)
        
        if errors:
            for err in errors[:5]:  # 只记录前5条错误
                logger.error(f"清理异常: {err}")
        
    except Exception as e:
        logger.error(f"❌ 定时清理任务异常: {e}")
        db.rollback()
    finally:
        db.close()


def start_scheduler():
    """启动调度器"""
    if not scheduler.running:
        init_scheduler()
        scheduler.start()
        logger.info("🕐 定时任务调度器已启动")


def stop_scheduler():
    """停止调度器"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("🕐 定时任务调度器已停止")
