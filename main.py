#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EchoMind 智能录音分析平台
录音上传(APP) → ASR转文字 → LLM分析 → 管理后台
"""

import os
import time
import uuid
import asyncio
import logging
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from models import init_db, get_db, User, AudioFile, AnalysisReport, PromptTemplate
from auth import get_current_user
from services.asr_service import ASRService
from services.llm_service import LLMService
from utils.file_utils import save_audio_file, cleanup_old_files, verify_asr_temp_token
from routers.auth_router import router as auth_router
from routers.file_router import router as file_router
from routers.prompt_router import router as prompt_router
from routers.user_router import router as user_router
from routers.settings_router import router as settings_router
from routers.report_router import router as report_router
from routers.tasktype_router import router as tasktype_router

# 简单内存速率限制（per-IP，单进程有效）
_upload_counters: dict = defaultdict(list)
_RATE_LIMIT = 20
_RATE_WINDOW = 3600

def _check_rate_limit(client_ip: str) -> bool:
    now = time.time()
    ts_list = _upload_counters[client_ip]
    _upload_counters[client_ip] = [t for t in ts_list if t > now - _RATE_WINDOW]
    if len(_upload_counters[client_ip]) >= _RATE_LIMIT:
        return False
    _upload_counters[client_ip].append(now)
    return True

# obs 可观测性（可选，obs/ 目录不存在时静默跳过）
try:
    import obs as _obs
    from obs.router import router as obs_router
    _obs.init("echomind")
    _OBS_ROUTER = obs_router
except Exception:
    _OBS_ROUTER = None

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建 FastAPI 应用
app = FastAPI(
    title="EchoMind - 智能录音分析平台",
    description="录音上传 → ASR转文字 → 自定义LLM分析 → 多维度报告",
    version="1.0.0"
)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth_router)
app.include_router(file_router)
app.include_router(prompt_router)
app.include_router(user_router)
app.include_router(settings_router)
app.include_router(report_router)
app.include_router(tasktype_router)
if _OBS_ROUTER:
    app.include_router(_OBS_ROUTER)

# 管理后台入口：访问 /app/echodmind 自动跳转到登录页
@app.get("/app/echodmind")
async def admin_redirect():
    return RedirectResponse(url="/app/echodmind/login.html")

# 分享页服务：/share/{share_id}
@app.get("/share/{share_id}")
async def serve_share_page(share_id: str):
    from fastapi.responses import FileResponse as FR
    share_path = Path(__file__).parent / "shares" / f"{share_id}.html"
    if not share_path.exists():
        raise HTTPException(status_code=404, detail="分享页不存在或已过期")
    return FR(path=share_path, media_type="text/html")


@app.post("/share/{share_id}/edit")
async def edit_share_page(share_id: str, request: dict, current_user: User = Depends(get_current_user)):
    """公开端点：编辑分享页内容（文字修改+图片删除）"""
    import re
    share_path = Path(__file__).parent / "shares" / f"{share_id}.html"
    if not share_path.exists():
        raise HTTPException(status_code=404, detail="分享页不存在或已过期")

    body_html = request.get("body_html", "")
    if not body_html:
        raise HTTPException(status_code=400, detail="body_html 不能为空")

    # 从旧HTML提取 title 和 label
    old_html = share_path.read_text(encoding="utf-8")
    title_match = re.search(r"<title>(.*?)</title>", old_html)
    title = title_match.group(1) if title_match else "报告"
    label_match = re.search(r'<div class="header-label">(.*?)</div>', old_html)
    label = label_match.group(1) if label_match else "报告"

    # 重新生成完整HTML（保留编辑JS能力）
    from routers.report_router import _html_wrapper
    new_html = _html_wrapper(label, title, body_html, share_id=share_id)
    share_path.write_text(new_html, encoding="utf-8")

    return {"success": True, "share_url": f"/share/{share_id}"}


# 挂载前端静态文件，通过 /app/echodmind/ 访问
app.mount("/app/echodmind", StaticFiles(directory=str(Path(__file__).parent / "frontend")), name="frontend")

# 挂载照片静态文件
_photos_dir = Path(__file__).parent / "uploads" / "photos"
_photos_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads/photos", StaticFiles(directory=str(_photos_dir)), name="photos")


# 供百炼 Fun-ASR 临时下载音频（签名 URL，短期有效）
@app.get("/asr-temp/{token}/{filename}")
async def serve_asr_temp_file(token: str, filename: str):
    """
    百炼 Fun-ASR 识别前需要拉取音频文件，
    本端点生成短期签名 URL，token 过期后自动失效。
    """
    if not verify_asr_temp_token(token, filename):
        raise HTTPException(status_code=403, detail="临时链接已失效或无效")

    file_path = Path(settings.UPLOAD_DIR) / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="音频文件不存在")

    return FileResponse(path=str(file_path), media_type="audio/mpeg", filename=filename)


# ==================== 请求/响应模型 ====================

class AnalyzeRequest(BaseModel):
    text: str = None
    file_id: str = None
    mode: str = "meeting"
    task_types: list[str] | None = None  # 指定分析类型；为空则用所有默认类型


class ReportResult(BaseModel):
    report_id: str | None = None
    data: dict | None = None
    error: str | None = None


class AnalyzeResponse(BaseModel):
    success: bool
    file_id: str
    asr_text: str | None = None
    reports: dict | None = None
    share_urls: dict | None = None   # {report_type: "/share/{id}"}
    # 兼容旧版单报告字段
    report_id: str | None = None
    analysis: dict | None = None
    error: str | None = None


class StatusResponse(BaseModel):
    status: str
    message: str


# ==================== 初始化服务 ====================

asr_service = ASRService()
llm_service = LLMService()


# ==================== API 路由 ====================

def _get_task_types(db, selected: list[str] | None = None) -> list[str]:
    """返回要分析的任务类型列表。selected 不为空时只取交集；否则取 default_rank 1/2/3 的类型（按 rank 排序）。"""
    from models import AnalysisTaskType
    q = db.query(AnalysisTaskType).filter(AnalysisTaskType.is_active == True)
    if selected:
        q = q.filter(AnalysisTaskType.name.in_(selected))
    else:
        q = q.filter(AnalysisTaskType.default_rank > 0)
    types = q.order_by(AnalysisTaskType.default_rank, AnalysisTaskType.sort_order).all()
    return [t.name for t in types]


@app.get("/api/v1/task-types")
async def list_task_types(db: Session = Depends(get_db)):
    """返回所有激活的分析任务类型（供前端构建勾选列表）"""
    from models import AnalysisTaskType
    types = db.query(AnalysisTaskType).filter(
        AnalysisTaskType.is_active == True
    ).order_by(AnalysisTaskType.sort_order).all()
    return {"task_types": [t.to_dict() for t in types]}


@app.get("/", response_model=StatusResponse)
async def root():
    return StatusResponse(status="ok", message="EchoMind 智能录音分析平台 v1.0")


@app.get("/health", response_model=StatusResponse)
async def health_check():
    return StatusResponse(status="healthy", message="服务正常")


# ==================== APP 端接口 ====================


@app.post("/api/v1/analyze", response_model=AnalyzeResponse)
async def analyze_audio(
    request: Request,
    file: UploadFile = File(...),
    task_types: str = Form(None),           # 逗号分隔的类型名，为空则用默认类型
    supplementary_text: str = Form(None),   # 可选补充说明，写入所有报告
    current_user: User = Depends(get_current_user),
):
    """
    【APP调用】完整流程：上传 → ASR → LLM并发分析 → 自动生成分享页 → 返回 share_urls
    需要登录（Bearer Token），上传文件归属到当前用户。
    """
    from models import SessionLocal, UploadStatus, AnalysisStatus
    from routers.report_router import auto_generate_share

    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        try:
            from obs.db import write_span as _sec_write_span
            import uuid as _sec_uuid
            _sec_now = time.time()
            _sec_write_span(
                span_id=_sec_uuid.uuid4().hex,
                trace_id=_sec_uuid.uuid4().hex[:12],
                service="echomind",
                operation="security:rate_limit_hit",
                start_ts=_sec_now, end_ts=_sec_now,
                status="blocked",
                metadata={"client_ip": client_ip},
            )
        except Exception:
            pass
        raise HTTPException(status_code=429, detail="上传过于频繁，请稍后再试")

    file_id = None
    db = SessionLocal()
    duration = None
    _e2e_start = time.time()
    _e2e_status = "ok"

    # 生成本次请求的 trace_id，让 ASR span 和 LLM 调用归入同一链路；同时写入 user_id
    _obs_mod = None
    if _OBS_ROUTER is not None:
        import obs as _obs_mod
        import uuid as _uuid
        _obs_mod.set_trace_id(_uuid.uuid4().hex[:12])
        _obs_mod.set_session(str(current_user.id))

    try:
        # 1. 保存文件
        file_id, file_path, duration = await save_audio_file(file)
        ext = Path(file_path).suffix.replace(".", "")

        audio_file = AudioFile(
            file_id=file_id,
            user_id=current_user.id,
            original_filename=file.filename,
            stored_filename=Path(file_path).name,
            file_path=file_path,
            file_size=Path(file_path).stat().st_size,
            duration=duration,
            file_format=ext,
            upload_status=UploadStatus.PROCESSING.value
        )
        db.add(audio_file)
        db.commit()
        db.refresh(audio_file)

        # 2. ASR 转文字
        asr_result = await asr_service.transcribe(file_path, audio_duration_s=duration)
        asr_text = asr_result["text"] if asr_result["success"] else ""
        audio_file.asr_text = asr_text
        db.commit()

        if not asr_result["success"]:
            audio_file.upload_status = UploadStatus.FAILED.value
            db.commit()
            return AnalyzeResponse(
                success=False,
                file_id=file_id,
                error=f"ASR转写失败: {asr_result.get('error')}"
            )

        # 3. 动态获取任务类型并并发调用 LLM
        selected = [t.strip() for t in task_types.split(",")] if task_types else None
        active_types = _get_task_types(db, selected) or _get_task_types(db, None)
        tasks = [
            llm_service.analyze(text=asr_text, report_type=rt, db=db, obs_operation=f"app:{rt}")
            for rt in active_types
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 4. 写入报告 + 自动生成分享页
        reports_output = {}
        share_urls = {}
        file_name = file.filename or "录音分析"

        for rt, result in zip(active_types, results):
            if isinstance(result, Exception):
                logger.error(f"报告生成异常({rt}): {result}")
                report = AnalysisReport(
                    file_id=audio_file.id,
                    user_id=current_user.id,
                    report_type=rt,
                    status=AnalysisStatus.FAILED.value,
                    error_message=str(result)
                )
            else:
                success = result.get("success", False)
                report = AnalysisReport(
                    file_id=audio_file.id,
                    user_id=current_user.id,
                    report_type=rt,
                    status=AnalysisStatus.COMPLETED.value if success else AnalysisStatus.FAILED.value,
                    report_data=result.get("data"),
                    supplementary_text=supplementary_text or None,
                    error_message=result.get("error") if not success else None
                )
            db.add(report)
            db.flush()

            reports_output[rt] = {
                "report_id": report.report_id,
                "status": report.status,
                "error": report.error_message
            }

            # 自动生成分享页（成功的报告才生成）
            if report.status == AnalysisStatus.COMPLETED.value:
                share_url = auto_generate_share(report, db, file_name)
                if share_url:
                    share_urls[rt] = share_url

        audio_file.upload_status = UploadStatus.COMPLETED.value
        db.commit()

        return AnalyzeResponse(
            success=True,
            file_id=file_id,
            asr_text=asr_text,
            reports=reports_output,
            share_urls=share_urls if share_urls else None
        )

    except Exception as e:
        _e2e_status = "error"
        logger.error(f"分析流程异常: {str(e)}")
        if file_id:
            try:
                af = db.query(AudioFile).filter(AudioFile.file_id == file_id).first()
                if af:
                    af.upload_status = UploadStatus.FAILED.value
                    db.commit()
            except Exception as ex:
                logger.error(f"更新文件状态失败: {ex}")
        return AnalyzeResponse(success=False, file_id=file_id or "", error=str(e))
    finally:
        if _obs_mod is not None:
            try:
                from obs.db import write_span as _obs_write_span
                _obs_write_span(
                    span_id=uuid.uuid4().hex,
                    trace_id=_obs_mod.get_trace_id(),
                    service="echomind",
                    operation="request",
                    start_ts=_e2e_start,
                    end_ts=time.time(),
                    status=_e2e_status,
                    metadata={"audio_duration_s": duration},
                )
            except Exception:
                pass
        db.close()


@app.post("/api/v1/analyze/text", response_model=AnalyzeResponse)
async def analyze_text(request: AnalyzeRequest, current_user: User = Depends(get_current_user)):
    """
    【APP调用】直接分析文字（已有转写结果）
    """
    from models import SessionLocal, AnalysisStatus
    
    file_id = request.file_id or str(uuid.uuid4())
    db = SessionLocal()
    
    try:
        if not request.text:
            raise HTTPException(status_code=400, detail="缺少text参数")
        
        analysis_result = await llm_service.analyze(text=request.text, mode=request.mode)
        
        return AnalyzeResponse(
            success=analysis_result["success"],
            file_id=file_id,
            analysis=analysis_result.get("data"),
            error=analysis_result.get("error")
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文字分析异常: {str(e)}")
        return AnalyzeResponse(success=False, file_id=file_id, error=str(e))
    finally:
        db.close()


# ==================== 启动事件 ====================

@app.on_event("startup")
async def startup_event():
    """服务启动时的初始化"""
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.UPLOAD_DIR, "photos").mkdir(parents=True, exist_ok=True)
    Path(Path(__file__).parent / "shares").mkdir(parents=True, exist_ok=True)
    init_db()
    _run_db_migrations()
    _seed_prompt_templates()
    _seed_task_types()
    # 启动时只清理过期录音物理文件，阈值与管理后台"清理设置"一致
    from models import SessionLocal
    from scheduler import start_scheduler, get_cleanup_expire_hours
    _db = SessionLocal()
    try:
        await cleanup_old_files(get_cleanup_expire_hours(_db))
    finally:
        _db.close()
    start_scheduler()
    logger.info("EchoMind 智能录音分析平台 v1.0 启动完成")


def _run_db_migrations():
    """安全地为已存在的表添加新列（SQLite 兼容写法）"""
    from models import engine
    from sqlalchemy import text, inspect
    with engine.connect() as conn:
        inspector = inspect(engine)

        # analysis_reports 表新列
        ar_cols = {c['name'] for c in inspector.get_columns('analysis_reports')}
        for col_name, col_type in [
            ("user_edited_data", "TEXT"),
            ("supplementary_text", "TEXT"),
            ("expert_notes", "TEXT"),
            ("photos", "TEXT"),
            ("share_id", "TEXT"),
        ]:
            if col_name not in ar_cols:
                conn.execute(text(f"ALTER TABLE analysis_reports ADD COLUMN {col_name} {col_type}"))
                conn.commit()
                logger.info(f"DB migration: added column analysis_reports.{col_name}")

        # analysis_task_types 表新列
        if 'analysis_task_types' in inspector.get_table_names():
            att_cols = {c['name'] for c in inspector.get_columns('analysis_task_types')}
            if 'default_rank' not in att_cols:
                conn.execute(text("ALTER TABLE analysis_task_types ADD COLUMN default_rank INTEGER DEFAULT 0"))
                # 从 is_default + sort_order 迁移：is_default=True 的记录 default_rank = sort_order（1/2/3）
                conn.execute(text(
                    "UPDATE analysis_task_types SET default_rank = sort_order "
                    "WHERE is_default = 1 AND sort_order BETWEEN 1 AND 3"
                ))
                conn.commit()
                logger.info("DB migration: added column analysis_task_types.default_rank")


def _seed_prompt_templates():
    """
    启动时将 prompts/ 目录下的 prompt 文件 seed 进数据库。
    - 若该 name 下已有任何记录（无论是否激活），跳过不重复写入
    - 若该 name 下没有任何记录，读取文件内容创建一条激活记录
    """
    from models import SessionLocal, PromptTemplate
    from pathlib import Path as _Path

    PROMPT_SEEDS = [
        ("customer_brief",            "参观简报",              "接待录音 → 参观简报（官方报道风格）",       "customer_brief.md"),
        ("business_opportunity",      "商机简报",              "接待录音 → 商机简报（发给客户经理）",       "business_opportunity.md"),
        ("reception_review",          "接待复盘",              "接待录音 → 接待复盘（运营团队参考）",       "reception_review.md"),
        ("customer_brief_share",      "参观简报·分享报告叙事化", "结构化参观简报 → 新闻稿风格叙事文本",      "customer_brief_share.md"),
        ("business_opportunity_share","商机简报·分享报告叙事化", "结构化商机简报 → 内部简报叙事文本",        "business_opportunity_share.md"),
        ("reception_review_share",    "接待复盘·分享报告叙事化", "结构化接待复盘 → 运营简报叙事文本",        "reception_review_share.md"),
    ]

    prompts_dir = _Path(__file__).parent / "prompts"
    db = SessionLocal()
    try:
        for name, display_name, description, filename in PROMPT_SEEDS:
            exists = db.query(PromptTemplate).filter(PromptTemplate.name == name).first()
            if exists:
                continue  # 已有记录，不覆盖
            filepath = prompts_dir / filename
            if not filepath.exists():
                logger.warning(f"Prompt 文件不存在，跳过 seed: {filename}")
                continue
            content = filepath.read_text(encoding="utf-8")
            tpl = PromptTemplate(
                name=name,
                description=f"[{display_name}] {description}",
                content=content,
                is_active=True,
            )
            db.add(tpl)
            logger.info(f"Prompt seed 写入: {name}")
        db.commit()
    except Exception as e:
        logger.error(f"Prompt seed 失败: {e}")
        db.rollback()
    finally:
        db.close()


def _seed_task_types():
    """
    首次启动时写入两个普适默认类型：会议摘要（rank 1）+ 意图分析（rank 2）。
    prompt 内容从预设库读取，同步写入 prompt_templates 表。
    已有记录不覆盖；展厅系列和其他类型由用户在管理后台「类型库」按需安装。
    """
    from models import SessionLocal, AnalysisTaskType, PromptTemplate
    from presets_library import get_preset, get_preset_prompt

    BUILTIN_TYPES = [
        {"name": "meeting_summary",  "display_name": "会议摘要", "default_rank": 1, "sort_order": 1},
        {"name": "intent_analysis",  "display_name": "意图分析", "default_rank": 2, "sort_order": 2},
    ]

    db = SessionLocal()
    try:
        for td in BUILTIN_TYPES:
            name = td["name"]
            # 1. 写入 PromptTemplate（若已存在则跳过）
            if not db.query(PromptTemplate).filter(PromptTemplate.name == name).first():
                preset = get_preset(name)
                prompt_content = get_preset_prompt(name)
                if preset and prompt_content:
                    db.add(PromptTemplate(
                        name=name,
                        description=f"[{td['display_name']}] {preset.get('description', '')}",
                        content=prompt_content,
                        is_active=True,
                    ))
                    logger.info(f"Prompt seed 写入: {name}")

            # 2. 写入 AnalysisTaskType（若已存在则跳过）
            if not db.query(AnalysisTaskType).filter(AnalysisTaskType.name == name).first():
                preset = get_preset(name)
                db.add(AnalysisTaskType(
                    name=name,
                    display_name=td["display_name"],
                    description=preset.get("description", "") if preset else "",
                    prompt_key=name,
                    share_prompt_key=None,
                    is_default=True,
                    default_rank=td["default_rank"],
                    sort_order=td["sort_order"],
                ))
                logger.info(f"TaskType seed 写入: {name}")

        db.commit()
    except Exception as e:
        logger.error(f"TaskType seed 失败: {e}")
        db.rollback()
    finally:
        db.close()


@app.on_event("shutdown")
async def shutdown_event():
    from scheduler import stop_scheduler
    stop_scheduler()
    logger.info("EchoMind 服务关闭")


if __name__ == "__main__":
    import uvicorn
    ssl_kwargs = {}
    if settings.SSL_CERTFILE and settings.SSL_KEYFILE:
        ssl_kwargs["ssl_certfile"] = settings.SSL_CERTFILE
        ssl_kwargs["ssl_keyfile"]  = settings.SSL_KEYFILE
        logger.info(f"HTTPS 模式，证书: {settings.SSL_CERTFILE}")
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        **ssl_kwargs
    )
