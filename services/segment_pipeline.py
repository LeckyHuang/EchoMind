#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分段流水线（异步分析 + 录音分段串联，2026-07-28）。

职责：
- `submit_segment_asr`   段 ASR 执行（全局并发上限 3，失败重试 2 次）
- `finalize_session`     客户端声明总段数与分析类型，把会话推进到 `analyzing`
- `check_and_finalize`   **唯一的分析触发点**，幂等
- `recover_pending_on_startup`  重启续跑扫描

设计要点见 `docs/specs/2026-07-28-async-segmented-analysis-design.md` 4.3 / 4.4。

## 幂等锁

两个互相独立的事件都会调用到齐检查：`finalize` 与「最后一段 ASR 完成」。
无论谁先谁后、哪怕同一轮事件循环里同时发生，LLM 分析必须且只能跑一轮
（多跑一轮 = 多扣一次费）。

锁由 `recording_sessions.status` 的**条件原子推进**实现：

    UPDATE recording_sessions SET status='generating'
     WHERE session_id=? AND status='analyzing'

只有 rowcount==1 的那一次调用拿到锁，其余全部 return False。这一步在**任何
`await` 之前**完成并 commit，因此在单事件循环内不存在检查与占位之间的让出点；
条件 UPDATE 又让它在跨进程/跨线程下同样成立（虽然本方案已强制 workers=1）。

`generating` 是 `analyzing` 与 `completed` 之间的中间态：`analyzing` 表示「等段
到齐」，`generating` 表示「已进入 LLM 分析」。重启续跑必须把 `generating` 退回
`analyzing` 后再跑到齐检查，否则该会话永远卡死。

## 为什么不复用 routers/file_router 的工具函数

`routers/file_router` 在 import 时会连带 import `auth`，而 `auth` 强制要求
`JWT_SECRET_KEY` 环境变量。本模块要能被后台任务与单测独立导入，故自带一份等价
的服务单例访问器与任务类型查询。合并分析的建表/写报告写法与
`routers/file_router.py:487-560` 的 `merge_analyze` 保持一致。
"""

import asyncio
import logging
import uuid
from datetime import datetime

from models import (
    SessionLocal,
    AudioFile,
    AnalysisReport,
    AnalysisTaskType,
    RecordingSession,
    UploadStatus,
    AnalysisStatus,
)
from services.asr_service import ASRService
from services.llm_service import LLMService

logger = logging.getLogger(__name__)


# ==================== 常量与全局资源 ====================

#: 段 ASR 全局并发上限，防打爆 ASR 厂商配额与限流（spec 4.3）
ASR_CONCURRENCY = 3
_asr_semaphore = asyncio.Semaphore(ASR_CONCURRENCY)

#: ASR 失败重试的退避秒数；元素个数 = 重试次数（首次调用不含在内）。测试里打桩成 (0, 0)
RETRY_BACKOFF_SECONDS = (5, 15)

#: 会话状态
STATUS_RECORDING = "recording"
STATUS_ANALYZING = "analyzing"
STATUS_GENERATING = "generating"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

#: 后台任务引用，防被 GC；同时供启动续跑后等待（测试与优雅关闭用）
_background_tasks: set = set()


_asr_service = None
_llm_service = None


def get_asr_service() -> ASRService:
    global _asr_service
    if _asr_service is None:
        _asr_service = ASRService()
    return _asr_service


def get_llm_service() -> LLMService:
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


def _resolve_task_types(db, selected: list[str] | None) -> list[str]:
    """与 routers/file_router._get_task_types 等价（见模块 docstring 的解释）。"""
    q = db.query(AnalysisTaskType).filter(AnalysisTaskType.is_active == True)  # noqa: E712
    if selected:
        q = q.filter(AnalysisTaskType.name.in_(selected))
    else:
        q = q.filter(AnalysisTaskType.default_rank > 0)
    types = q.order_by(AnalysisTaskType.default_rank, AnalysisTaskType.sort_order).all()
    return [t.name for t in types]


def _generate_share(report: AnalysisReport, db, file_name: str) -> str:
    """生成分享页。懒 import（report_router 依赖 auth 的环境变量），失败只降级不抛。"""
    try:
        from routers.report_router import auto_generate_share
        return auto_generate_share(report, db, file_name)
    except Exception as e:  # pragma: no cover - 依赖运行时环境
        logger.warning(f"分享页生成失败（降级忽略）: {e}")
        return ""


def _spawn(coro) -> asyncio.Task:
    """起一个后台任务并持有引用，防止被 GC 掉。"""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def wait_for_background_tasks(timeout: float = 30.0) -> None:
    """等待当前所有后台任务结束（启动续跑后的收尾、优雅关闭、测试同步用）。"""
    deadline = asyncio.get_event_loop().time() + timeout
    while _background_tasks:
        pending = list(_background_tasks)
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            logger.warning(f"等待后台任务超时，仍有 {len(pending)} 个未完成")
            return
        await asyncio.wait(pending, timeout=remaining)


# ==================== 段 ASR ====================

async def submit_segment_asr(audio_file_id: int) -> None:
    """跑某段的 ASR（受全局信号量限流），完成后自动调到齐检查。

    段状态：pending → processing（进信号量前置位）→ completed | failed。
    失败重试 2 次，退避 5s / 15s；仍失败则标 failed，**不阻塞到齐检查**。
    """
    db = SessionLocal()
    try:
        af = db.query(AudioFile).filter(AudioFile.id == audio_file_id).first()
        if af is None:
            logger.warning(f"段 ASR 提交失败：audio_file id={audio_file_id} 不存在")
            return
        if af.upload_status == UploadStatus.COMPLETED.value:
            logger.info(f"段已完成，跳过 ASR: id={audio_file_id}")
            session_id = af.session_id
            db.close()
            db = None
            if session_id:
                await check_and_finalize(session_id)
            return

        session_id = af.session_id
        file_path = af.file_path
        duration = af.duration or 0.0
        af.upload_status = UploadStatus.PROCESSING.value
        db.commit()
    finally:
        if db is not None:
            db.close()

    text, error = await _transcribe_with_retry(file_path, duration)

    db = SessionLocal()
    try:
        af = db.query(AudioFile).filter(AudioFile.id == audio_file_id).first()
        if af is None:
            return
        if error is None:
            af.asr_text = text
            af.upload_status = UploadStatus.COMPLETED.value
        else:
            af.upload_status = UploadStatus.FAILED.value
            logger.error(f"段 ASR 最终失败 id={audio_file_id}: {error}")
        db.commit()
    finally:
        db.close()

    if session_id:
        await check_and_finalize(session_id)


async def _transcribe_with_retry(file_path: str, duration: float) -> tuple[str, str | None]:
    """返回 (text, error)；error 为 None 表示成功。首次 + len(RETRY_BACKOFF_SECONDS) 次重试。"""
    attempts = len(RETRY_BACKOFF_SECONDS) + 1
    last_error = "未知错误"
    for attempt in range(attempts):
        if attempt > 0:
            backoff = RETRY_BACKOFF_SECONDS[attempt - 1]
            if backoff:
                await asyncio.sleep(backoff)
            logger.info(f"段 ASR 第 {attempt} 次重试: {file_path}")
        try:
            async with _asr_semaphore:
                result = await get_asr_service().transcribe(
                    file_path, audio_duration_s=duration
                )
            if result.get("success"):
                return result.get("text") or "", None
            last_error = result.get("error") or "ASR 返回失败"
        except Exception as e:
            last_error = str(e)
        logger.warning(f"段 ASR 失败（第 {attempt + 1}/{attempts} 次）: {last_error}")
    return "", last_error


# ==================== finalize ====================

async def finalize_session(
    session_id: str,
    total_segments: int,
    task_types: list[str] | None = None,
    supplementary_text: str | None = None,
) -> bool:
    """客户端声明总段数与分析类型，把会话从 recording 推进到 analyzing，随后跑一次到齐检查。

    幂等：重复调用只更新字段；已经在 generating/completed/failed 的会话**不会**被拉回
    analyzing 重跑分析。返回值同 `check_and_finalize`（本次调用是否触发了分析）。
    """
    db = SessionLocal()
    try:
        sess = db.query(RecordingSession).filter(
            RecordingSession.session_id == session_id
        ).first()
        if sess is None:
            logger.warning(f"finalize 失败：会话 {session_id} 不存在")
            return False

        if sess.status in (STATUS_COMPLETED, STATUS_FAILED, STATUS_GENERATING):
            # 已跑过或正在跑：只做无害的字段补写，绝不回退状态
            logger.info(f"会话 {session_id} 已处于 {sess.status}，finalize 不重复触发分析")
            return False

        sess.total_segments = total_segments
        if task_types:
            sess.task_types = list(task_types)
        if supplementary_text is not None:
            sess.supplementary_text = supplementary_text
        sess.status = STATUS_ANALYZING
        db.commit()
    finally:
        db.close()

    return await check_and_finalize(session_id)


# ==================== 到齐检查（唯一分析触发点） ====================

async def check_and_finalize(session_id: str) -> bool:
    """到齐检查。**幂等**：触发了分析返回 True，否则 False。

    见模块 docstring 的「幂等锁」一节：抢锁之前不得有任何 await。
    """
    db = SessionLocal()
    claimed = False
    try:
        sess = db.query(RecordingSession).filter(
            RecordingSession.session_id == session_id
        ).first()
        if sess is None:
            return False
        # recording：还没 finalize；generating/completed/failed：已经跑过或正在跑
        if sess.status != STATUS_ANALYZING:
            return False
        if sess.total_segments is None:
            return False

        # 只捞真正的「段」：`_run_analysis` 建的虚拟 merged AudioFile 也挂同一个
        # session_id，但 segment_index 为空。不排除它，续跑/重跑路径下它会被当成
        # 一个段参与计数与拼接，且它初始 PROCESSING 会替幂等锁挡住并发重入
        # （spec 4.1 已把这条记为显式不变量）。
        segments = db.query(AudioFile).filter(
            AudioFile.session_id == session_id,
            AudioFile.segment_index.isnot(None),
        ).order_by(AudioFile.segment_index).all()

        if len(segments) < sess.total_segments:
            return False
        if any(
            s.upload_status in (UploadStatus.PENDING.value, UploadStatus.PROCESSING.value)
            for s in segments
        ):
            return False

        if all(s.upload_status == UploadStatus.FAILED.value for s in segments):
            sess.status = STATUS_FAILED
            sess.error_message = f"全部 {len(segments)} 段转写均失败，无可分析内容"
            db.commit()
            logger.error(f"会话 {session_id} 全段 ASR 失败，转 failed")
            return False

        # —— 幂等锁：条件原子推进到 generating，只有 rowcount==1 的调用继续 ——
        rowcount = db.query(RecordingSession).filter(
            RecordingSession.session_id == session_id,
            RecordingSession.status == STATUS_ANALYZING,
        ).update({"status": STATUS_GENERATING}, synchronize_session=False)
        db.commit()
        if rowcount != 1:
            logger.info(f"会话 {session_id} 已被另一路抢先进入 generating，本次跳过")
            return False
        claimed = True

        await _run_analysis(db, session_id, segments)
        return True

    except Exception as e:
        logger.error(f"会话 {session_id} 分析失败: {e}", exc_info=True)
        if claimed:
            try:
                db.rollback()
                sess = db.query(RecordingSession).filter(
                    RecordingSession.session_id == session_id
                ).first()
                if sess is not None:
                    sess.status = STATUS_FAILED
                    sess.error_message = str(e)
                    db.commit()
            except Exception as ex:
                logger.error(f"回写会话失败状态出错: {ex}")
        return False
    finally:
        db.close()


async def _run_analysis(db, session_id: str, segments: list) -> None:
    """拼接文本 → 建虚拟 merged AudioFile → LLM 并发分析 → 写报告 + 分享页 → 会话 completed。

    建表与写报告的写法照抄 routers/file_router.py 的 `merge_analyze`（现网跑通过的路径）。
    """
    sess = db.query(RecordingSession).filter(
        RecordingSession.session_id == session_id
    ).first()

    # 1. 按 segment_index 排序拼接，失败段插占位（spec 4.4 缺段降级）。
    #    编号用 seg.segment_index+1 而非位置序号：段号有洞时（例如某段上传
    #    从未落库）两者会错位，用户看到的「片段N」必须对应真实段号。
    parts = []
    for seg in segments:
        label = seg.segment_index + 1
        if seg.upload_status == UploadStatus.FAILED.value:
            parts.append(f"[片段{label}：转写失败，内容缺失]")
        elif not seg.asr_text:
            # ASR 调用成功但返回空文本（纯静音段等）：与真正的转写失败区分开，
            # 避免误导用户以为出了故障。
            parts.append(f"[片段{label}：无有效语音内容]")
        else:
            parts.append(f"[片段{label}]\n{seg.asr_text}")
    merged_text = "\n\n".join(parts)

    # 2. 创建合并记录（虚拟 AudioFile，无实际音频文件）
    total_duration = sum((s.duration or 0) for s in segments)
    merged_filename = sess.title or f"合并分析_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    merged_file = AudioFile(
        file_id=str(uuid.uuid4()),
        user_id=sess.user_id,
        original_filename=merged_filename,
        stored_filename=merged_filename,
        file_path="",
        file_size=0,
        duration=total_duration,
        file_format="merged",
        upload_status=UploadStatus.PROCESSING.value,
        asr_text=merged_text,
        session_id=session_id,
    )
    db.add(merged_file)
    db.commit()
    db.refresh(merged_file)

    # 3. 并发生成报告（动态类型）
    selected = list(sess.task_types) if sess.task_types else None
    active_types = _resolve_task_types(db, selected) or _resolve_task_types(db, None)
    supplementary_text = sess.supplementary_text

    tasks = [
        get_llm_service().analyze(
            text=merged_text, report_type=rt, db=db, obs_operation=f"session:{rt}"
        )
        for rt in active_types
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 4. 写入报告 + 自动生成分享页（单个类型失败隔离，不拖垮整体）
    for rt, result in zip(active_types, results):
        if isinstance(result, Exception):
            logger.error(f"会话 {session_id} 报告生成异常({rt}): {result}")
            report = AnalysisReport(
                file_id=merged_file.id,
                user_id=sess.user_id,
                report_type=rt,
                status=AnalysisStatus.FAILED.value,
                error_message=str(result),
            )
        else:
            success = result.get("success", False)
            report = AnalysisReport(
                file_id=merged_file.id,
                user_id=sess.user_id,
                report_type=rt,
                status=AnalysisStatus.COMPLETED.value if success else AnalysisStatus.FAILED.value,
                report_data=result.get("data"),
                supplementary_text=supplementary_text or None,
                error_message=result.get("error") if not success else None,
            )
        db.add(report)
        db.flush()

        if report.status == AnalysisStatus.COMPLETED.value:
            _generate_share(report, db, merged_filename)

    merged_file.upload_status = UploadStatus.COMPLETED.value
    sess.merged_file_id = merged_file.id
    sess.status = STATUS_COMPLETED
    db.commit()
    logger.info(f"会话 {session_id} 分析完成，共 {len(active_types)} 份报告")


# ==================== 启动续跑 ====================

async def recover_pending_on_startup() -> dict:
    """应用启动时的续跑扫描。返回 {"segments_resubmitted": int, "sessions_rechecked": int}。

    - 重新提交 `upload_status IN (pending, processing)` 且属于某会话的段
    - 对所有 `status IN (analyzing, generating)` 的会话跑一次到齐检查；
      **`generating` 必须先退回 `analyzing`**，否则到齐检查会因状态不符直接返回，
      该会话永远卡死。
    """
    db = SessionLocal()
    try:
        stuck_segments = db.query(AudioFile).filter(
            AudioFile.session_id.isnot(None),
            AudioFile.upload_status.in_(
                [UploadStatus.PENDING.value, UploadStatus.PROCESSING.value]
            ),
        ).all()
        segment_ids = [s.id for s in stuck_segments]

        # generating 是「进了 LLM 但没跑完就重启」，必须退回 analyzing 才能重跑
        reset = db.query(RecordingSession).filter(
            RecordingSession.status == STATUS_GENERATING
        ).update({"status": STATUS_ANALYZING}, synchronize_session=False)
        if reset:
            logger.info(f"启动续跑：{reset} 个 generating 会话退回 analyzing")
        db.commit()

        session_ids = [
            s.session_id
            for s in db.query(RecordingSession).filter(
                RecordingSession.status == STATUS_ANALYZING
            ).all()
        ]
    finally:
        db.close()

    for af_id in segment_ids:
        _spawn(submit_segment_asr(af_id))
    for sid in session_ids:
        _spawn(check_and_finalize(sid))

    stats = {
        "segments_resubmitted": len(segment_ids),
        "sessions_rechecked": len(session_ids),
    }
    logger.info(f"启动续跑扫描: {stats}")
    return stats
