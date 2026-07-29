#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定时任务调度器
- 定期清理过期录音文件
- 记录清理日志
"""

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from models import SessionLocal, AudioFile, RecordingSession, UploadStatus, SystemSetting
from utils.file_utils import cleanup_old_files
from config import settings

logger = logging.getLogger(__name__)

# 全局调度器实例
scheduler = AsyncIOScheduler()


def get_cleanup_expire_hours(db: Session) -> int:
    """过期时长统一读管理后台设置的 cleanup_expire_hours，未配置时回退 .env 的 FILE_EXPIRE_HOURS"""
    return int(SystemSetting.get_setting(db, "cleanup_expire_hours", str(settings.FILE_EXPIRE_HOURS)))


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
    定时清理任务：只删除过期录音的物理文件。
    DB 记录与分析报告永久保留（报告级联挂在 audio_files 上，禁止删除记录）。
    """
    logger.info(f"🕐 定时清理任务开始执行 | 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    db = SessionLocal()
    cleaned_physical = 0
    errors = []

    try:
        expire_hours = get_cleanup_expire_hours(db)
        # created_at 由 func.now() 写入（SQLite 下为 UTC），比较时同样用 UTC
        expire_time = datetime.utcnow() - timedelta(hours=expire_hours)

        old_files = db.query(AudioFile).filter(
            AudioFile.created_at <= expire_time
        ).all()

        for audio_file in old_files:
            try:
                if not audio_file.stored_filename:
                    continue
                file_path = Path(settings.UPLOAD_DIR) / audio_file.stored_filename
                if file_path.is_file():
                    file_path.unlink()
                    cleaned_physical += 1
            except Exception as e:
                errors.append(f"删除文件 {audio_file.file_id} 失败: {e}")

        # 兜底：按 mtime 清理 uploads 目录中无 DB 记录的孤立文件
        await cleanup_old_files(expire_hours)

        # 孤儿 session 清理（异步分段串联，2026-07-28，spec 4.4）
        orphan_count = await cleanup_orphan_sessions()
        if orphan_count:
            logger.info(f"🕐 孤儿会话清理: {orphan_count} 个")

        # 记录清理日志
        log_msg = (
            f"✅ 清理完成 | 物理文件: {cleaned_physical} 个"
            f" | 过期阈值: {expire_hours} 小时"
            f" | 错误: {len(errors)}"
        )
        logger.info(log_msg)

        if errors:
            for err in errors[:5]:  # 只记录前5条错误
                logger.error(f"清理异常: {err}")

    except Exception as e:
        logger.error(f"❌ 定时清理任务异常: {e}")
    finally:
        db.close()


#: 孤儿 session 判定阈值：finalize 从未被调用（App 崩溃/卸载）超过这个时长即标 failed（spec 4.4）
ORPHAN_SESSION_EXPIRE_HOURS = 24


async def cleanup_orphan_sessions(session_factory=SessionLocal) -> int:
    """`recording` 状态且 `created_at` 早于 24 小时前的会话标记 `failed`，并清理其段音频物理文件。

    `session_factory` 可注入（测试用临时库工厂），默认用生产 `SessionLocal`。
    返回被清理的会话数。
    """
    db = session_factory()
    cleaned = 0
    try:
        expire_time = datetime.utcnow() - timedelta(hours=ORPHAN_SESSION_EXPIRE_HOURS)
        orphans = db.query(RecordingSession).filter(
            RecordingSession.status == "recording",
            RecordingSession.created_at <= expire_time,
        ).all()

        for sess in orphans:
            # spec 4.1 不变量：merged 虚拟 AudioFile 也带 session_id 但
            # segment_index 为空，按 session 捞段必须过滤掉它。这里删的是
            # 真实段的物理文件，混进 merged 记录会把它当成一个段处理。
            segments = db.query(AudioFile).filter(
                AudioFile.session_id == sess.session_id,
                AudioFile.segment_index.isnot(None),
            ).all()
            for seg in segments:
                try:
                    if seg.stored_filename:
                        file_path = Path(settings.UPLOAD_DIR) / seg.stored_filename
                        if file_path.is_file():
                            file_path.unlink()
                except Exception as e:
                    logger.warning(f"孤儿会话清理：删除段音频失败 file_id={seg.file_id}: {e}")

            sess.status = "failed"
            sess.error_message = "录音未正常结束"
            cleaned += 1

        if cleaned:
            db.commit()
            logger.info(f"孤儿会话清理：{cleaned} 个 recording 会话标记 failed")
    finally:
        db.close()

    return cleaned


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
