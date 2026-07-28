#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告编辑与分享 API
- 编辑报告结构化字段 & 补充文字
- 照片上传/删除/说明更新
- 生成手机端分享 HTML 页面（参观简报：LLM 叙事化 → HTML）
"""

import uuid
import json
import html
import base64
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models import get_db, User, AnalysisReport, AudioFile
from auth import get_current_user
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["报告编辑与分享"])

# ==================== 非 admin 语义别名路由（异步分段串联，2026-07-28） ====================
# `GET /api/v1/admin/reports/{id}`（routers/prompt_router.py 的 get_report）路径带 admin，
# 但鉴权只按当前用户，语义有误导。这里加一条非 admin 前缀的别名路由，直接复用同一个
# handler 函数（不复制逻辑），供 App 原生渲染取 report_data。旧路由原样保留。
alias_router = APIRouter(prefix="/api/v1", tags=["报告编辑与分享"])


@alias_router.get("/reports/{report_id}")
async def get_report_alias(
    report_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """`GET /api/v1/admin/reports/{report_id}` 的非 admin 别名，见 spec 4.2。"""
    from routers.prompt_router import get_report as _admin_get_report
    return await _admin_get_report(report_id, db, current_user)

BASE_DIR = Path(__file__).resolve().parent.parent
PHOTOS_DIR = BASE_DIR / "uploads" / "photos"
SHARES_DIR = BASE_DIR / "shares"


# ==================== 辅助函数 ====================

def get_report_or_404(report_id: str, db: Session, current_user: User) -> AnalysisReport:
    report = db.query(AnalysisReport).filter(AnalysisReport.report_id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    if current_user.role != "admin" and report.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作此报告")
    return report


# ==================== 编辑报告 ====================

class EditReportRequest(BaseModel):
    user_edited_data: Optional[dict] = None
    supplementary_text: Optional[str] = None
    expert_notes: Optional[str] = None


class ExpertNotesRequest(BaseModel):
    expert_notes: Optional[str] = None


class AiExtractRequest(BaseModel):
    supplement_text: str


@router.patch("/reports/{report_id}/edit")
async def edit_report(
    report_id: str,
    request: EditReportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """保存用户对报告的编辑（结构化字段覆盖 + 补充文字）"""
    report = get_report_or_404(report_id, db, current_user)

    if request.user_edited_data is not None:
        report.user_edited_data = request.user_edited_data
    if request.supplementary_text is not None:
        report.supplementary_text = request.supplementary_text
    if request.expert_notes is not None:
        report.expert_notes = request.expert_notes

    # 内容有更新时清除已缓存的分享页，强制下次重新生成
    if report.share_id:
        old_share = SHARES_DIR / f"{report.share_id}.html"
        if old_share.exists():
            old_share.unlink()
        report.share_id = None

    db.commit()
    db.refresh(report)

    return {
        "success": True,
        "report_id": report.report_id,
        "user_edited_data": report.user_edited_data,
        "supplementary_text": report.supplementary_text
    }


# ==================== 专家讲解 ====================

@router.patch("/reports/{report_id}/expert-notes")
async def save_expert_notes(
    report_id: str,
    request: ExpertNotesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """保存专家讲解内容（接待复盘专用），不触发分享页缓存失效"""
    report = get_report_or_404(report_id, db, current_user)

    if request.expert_notes is not None:
        report.expert_notes = request.expert_notes

    db.commit()
    db.refresh(report)

    return {
        "success": True,
        "report_id": report.report_id,
        "expert_notes": report.expert_notes
    }


@router.post("/reports/{report_id}/expert-notes/organize")
async def organize_expert_notes(
    report_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """调用 LLM 对专家讲解内容进行梳理和分段，99%保留原文"""
    report = get_report_or_404(report_id, db, current_user)

    if not report.expert_notes or not report.expert_notes.strip():
        raise HTTPException(status_code=400, detail="专家讲解内容为空，请先填写内容")

    try:
        from services.llm_service import LLMService
        svc = LLMService()
        result = await svc.analyze(
            text=report.expert_notes,
            report_type="expert_notes_organizer",
            db=db
        )
        if result.get("success") and result.get("data"):
            data = result["data"]
            organized_text = data.get("organized_text") if isinstance(data, dict) else None
            if not organized_text:
                # 降级：返回原始文本（LLM未按格式输出时保留原文）
                organized_text = report.expert_notes
            return {
                "success": True,
                "organized_text": organized_text
            }
        else:
            raise HTTPException(
                status_code=502,
                detail=f"AI整理失败: {result.get('error', '未知错误')}"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"专家讲解整理异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== AI 辅助补录 ====================

@router.post("/reports/{report_id}/ai-extract")
async def ai_extract_fields(
    report_id: str,
    request: AiExtractRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """从用户补充文字中 AI 提取结构化字段，用于自动回填报告缺失内容"""
    if not request.supplement_text or not request.supplement_text.strip():
        raise HTTPException(status_code=400, detail="补充文字不能为空")

    report = get_report_or_404(report_id, db, current_user)

    if report.status != "completed" or not report.report_data:
        raise HTTPException(status_code=400, detail="报告尚未生成完成")

    # 合并当前数据，以便 LLM 知道哪些字段待补充
    current_data = _deep_merge(report.report_data, report.user_edited_data)

    try:
        from services.llm_service import LLMService
        svc = LLMService()
        result = await svc.extract_supplement_fields(
            supplement_text=request.supplement_text.strip(),
            report_type=report.report_type,
            current_data=current_data
        )
        if not result.get("success"):
            raise HTTPException(status_code=502, detail=f"AI提取失败: {result.get('error', '未知错误')}")

        return {
            "success": True,
            "report_type": report.report_type,
            "extracted_data": result.get("data") or {},
            "extracted_fields": result.get("extracted_fields") or [],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI字段提取异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 照片管理 ====================

class AddPhotoByUrlRequest(BaseModel):
    url: str
    caption: Optional[str] = ""


@router.post("/reports/{report_id}/photos")
async def add_photo(
    report_id: str,
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """上传本地照片到报告（multipart/form-data）"""
    report = get_report_or_404(report_id, db, current_user)

    if not file:
        raise HTTPException(status_code=400, detail="请上传照片文件")

    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/jpg"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="仅支持 JPG/PNG/WebP 格式图片")

    ext = Path(file.filename or "photo.jpg").suffix.lower() or ".jpg"
    photo_id = str(uuid.uuid4())
    filename = f"{photo_id}{ext}"
    save_path = PHOTOS_DIR / filename

    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    save_path.write_bytes(content)

    photo_url = f"/uploads/photos/{filename}"
    photo_obj = {"id": photo_id, "type": "local", "url": photo_url, "caption": ""}

    current_photos = list(report.photos or [])
    current_photos.append(photo_obj)
    report.photos = current_photos
    # 照片有变化时清除分享页缓存
    _invalidate_share(report)
    db.commit()

    return {"success": True, "photo": photo_obj}


@router.post("/reports/{report_id}/photos/url")
async def add_photo_by_url(
    report_id: str,
    request: AddPhotoByUrlRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """以 URL 方式添加照片到报告"""
    report = get_report_or_404(report_id, db, current_user)

    if not request.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="请输入有效的图片 URL")

    photo_id = str(uuid.uuid4())
    photo_obj = {"id": photo_id, "type": "url", "url": request.url, "caption": request.caption or ""}

    current_photos = list(report.photos or [])
    current_photos.append(photo_obj)
    report.photos = current_photos
    _invalidate_share(report)
    db.commit()

    return {"success": True, "photo": photo_obj}


@router.delete("/reports/{report_id}/photos/{photo_id}")
async def delete_photo(
    report_id: str,
    photo_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """删除报告中的某张照片"""
    report = get_report_or_404(report_id, db, current_user)

    current_photos = list(report.photos or [])
    target = next((p for p in current_photos if p["id"] == photo_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="照片不存在")

    if target.get("type") == "local":
        local_path = BASE_DIR / target["url"].lstrip("/")
        if local_path.exists():
            local_path.unlink()

    report.photos = [p for p in current_photos if p["id"] != photo_id]
    _invalidate_share(report)
    db.commit()

    return {"success": True}


class UpdateCaptionRequest(BaseModel):
    caption: str


@router.patch("/reports/{report_id}/photos/{photo_id}/caption")
async def update_photo_caption(
    report_id: str,
    photo_id: str,
    request: UpdateCaptionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新照片说明文字"""
    report = get_report_or_404(report_id, db, current_user)

    current_photos = list(report.photos or [])
    for p in current_photos:
        if p["id"] == photo_id:
            p["caption"] = request.caption
            break

    report.photos = current_photos
    db.commit()

    return {"success": True}


class ReorderPhotosRequest(BaseModel):
    photo_ids: list[str]


@router.post("/reports/{report_id}/reorder-photos")
async def reorder_photos(
    report_id: str,
    request: ReorderPhotosRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """调整报告照片的顺序"""
    report = get_report_or_404(report_id, db, current_user)

    current_photos = list(report.photos or [])
    photo_map = {p["id"]: p for p in current_photos}

    new_photos = []
    for pid in request.photo_ids:
        if pid in photo_map:
            new_photos.append(photo_map[pid])
    # 把不在请求列表中的照片append到末尾（兜底）
    for p in current_photos:
        if p["id"] not in request.photo_ids:
            new_photos.append(p)

    # 去重保护
    seen = set()
    deduped = []
    for p in new_photos:
        pid = p["id"]
        if pid not in seen:
            seen.add(pid)
            deduped.append(p)
    report.photos = deduped
    _invalidate_share(report)
    db.commit()

    return {"success": True, "photos": deduped}


def _invalidate_share(report: AnalysisReport):
    """内容变更时清除分享页缓存"""
    if report.share_id:
        old_share = SHARES_DIR / f"{report.share_id}.html"
        if old_share.exists():
            old_share.unlink()
        report.share_id = None


def auto_generate_share(report: AnalysisReport, db: Session, file_name: str = "") -> str:
    """
    分析完成后自动生成分享页（同步，无 LLM 叙事化）。
    供 /api/v1/analyze 流程内部调用，返回 share_url（如 /share/{id}）。
    三种旧类型跳过叙事层直接渲染，新类型走 sections 通用渲染。
    """
    if report.status != "completed" or not report.report_data:
        return ""
    if report.share_id:
        share_file = SHARES_DIR / f"{report.share_id}.html"
        if share_file.exists():
            return f"/share/{report.share_id}"
    merged_data = _deep_merge(report.report_data, report.user_edited_data or {})
    supp_text = report.supplementary_text or ""
    SHARES_DIR.mkdir(parents=True, exist_ok=True)
    share_id = str(uuid.uuid4())
    html_content = _generate_share_html(
        report_type=report.report_type,
        data=merged_data,
        photos=list(report.photos or []),
        supplementary_text=supp_text,
        file_name=file_name or "录音分析",
        narrative=None,
    )
    (SHARES_DIR / f"{share_id}.html").write_text(html_content, encoding="utf-8")
    report.share_id = share_id
    db.commit()
    return f"/share/{share_id}"


# ==================== 生成分享页 ====================

@router.post("/reports/{report_id}/generate-share")
async def generate_share_page(
    report_id: str,
    force: bool = Query(False, description="强制重新生成，忽略缓存"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    生成（或返回已缓存的）手机端分享 HTML 页面。
    - 参观简报：先调用 LLM 将结构化数据叙事化，再生成 HTML
    - 其他报告：直接从结构化数据生成 HTML
    """
    report = get_report_or_404(report_id, db, current_user)

    if report.status != "completed" or not report.report_data:
        raise HTTPException(status_code=400, detail="报告尚未生成完成，无法生成分享页")

    # ——缓存命中：直接返回已有分享页——
    if not force and report.share_id:
        share_file = SHARES_DIR / f"{report.share_id}.html"
        if share_file.exists():
            return {
                "success": True,
                "share_id": report.share_id,
                "share_url": f"/share/{report.share_id}",
                "cached": True,
            }

    # ——合并数据——
    merged_data = _deep_merge(report.report_data, report.user_edited_data)
    photos = list(report.photos or [])
    supp_text = report.supplementary_text or ""

    audio_file = db.query(AudioFile).filter(AudioFile.id == report.file_id).first()
    file_name = audio_file.original_filename if audio_file else "接待活动"

    # ——LLM 叙事化（三种报告均支持）——
    narrative_key_map = {
        "customer_brief": "customer_brief_share",
        "business_opportunity": "business_opportunity_share",
        "reception_review": "reception_review_share",
    }
    narrative = None
    prompt_key = narrative_key_map.get(report.report_type)
    if prompt_key:
        narrative = await _generate_narrative(merged_data, db, prompt_key)

    # ——生成 HTML——
    SHARES_DIR.mkdir(parents=True, exist_ok=True)
    share_id = str(uuid.uuid4())
    html_content = _generate_share_html(
        report_type=report.report_type,
        data=merged_data,
        photos=photos,
        supplementary_text=supp_text,
        file_name=file_name,
        narrative=narrative,
        share_id=share_id,
    )
    (SHARES_DIR / f"{share_id}.html").write_text(html_content, encoding="utf-8")

    report.share_id = share_id
    db.commit()

    return {
        "success": True,
        "share_id": share_id,
        "share_url": f"/share/{share_id}",
        "cached": False,
    }


async def _generate_narrative(data: dict, db, prompt_key: str) -> Optional[dict]:
    """调用 LLM 将结构化报告数据转成叙事化内容"""
    try:
        from services.llm_service import LLMService
        svc = LLMService()
        result = await svc.generate_text(prompt_key, data, db)
        if result.get("success") and result.get("data"):
            return result["data"]
    except Exception as e:
        logger.warning(f"叙事化生成失败({prompt_key})，降级为结构化展示: {e}")
    return None


# ==================== HTML 生成 ====================

def _deep_merge(target: dict, source: dict) -> dict:
    if not source or not isinstance(source, dict):
        return target or {}
    if not target:
        return source
    result = dict(target)
    for key, val in source.items():
        if val is None or val == "" or (isinstance(val, list) and len(val) == 0):
            continue
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _photo_to_img_tag(photo: dict, style: str = "width:100%;border-radius:8px;display:block;") -> str:
    url = photo.get("url", "")
    caption = html.escape(photo.get("caption", ""))
    alt = caption or "照片"

    if photo.get("type") == "local":
        local_path = BASE_DIR / url.lstrip("/")
        if local_path.exists():
            try:
                raw = local_path.read_bytes()
                ext = local_path.suffix.lower().lstrip(".")
                mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
                b64 = base64.b64encode(raw).decode()
                url = f"data:{mime};base64,{b64}"
            except Exception:
                pass

    caption_html = f'<p style="font-size:12px;color:#999;text-align:center;margin:6px 0 0;">{caption}</p>' if caption else ""
    return f'<div style="margin-bottom:12px;"><img src="{url}" alt="{alt}" style="{style}" loading="lazy">{caption_html}</div>'


REPORT_TYPE_LABELS = {
    "customer_brief": "参观简报",
    "business_opportunity": "商机简报",
    "reception_review": "接待复盘",
}


def _get_report_label(report_type: str, db=None) -> str:
    """从 DB 获取展示名，fallback 到内置字典，最终 fallback 到 report_type 本身。"""
    if db is not None:
        try:
            from models import AnalysisTaskType
            t = db.query(AnalysisTaskType).filter(AnalysisTaskType.name == report_type).first()
            if t:
                return t.display_name
        except Exception:
            pass
    return REPORT_TYPE_LABELS.get(report_type, report_type)

ACCENT = "#00CDB8"


def _html_wrapper(label: str, title: str, body: str, share_id: str = None) -> str:
    edit_js = ""
    if share_id:
        edit_js = f"""<script>
(function(){{
  var shareId = '{share_id}';
  var selectors = '.para, .lead-item, .highlight-item, .improve-item, .outlook, .supp, .item, li';
  var editableEls = document.querySelectorAll(selectors);
  var isEditing = false;

  // 默认不可编辑
  editableEls.forEach(function(el){{
    el.contentEditable = false;
    el.style.outline = 'none';
    el.dataset.editable = 'true';
  }});

  // 图片删除按钮（仅在编辑模式显示）
  document.querySelectorAll('img').forEach(function(img){{
    var wrapper = img.parentElement;
    if(!wrapper || wrapper.querySelector('.img-delete-btn')) return;
    var btn = document.createElement('button');
    btn.innerHTML = '✕';
    btn.className = 'img-delete-btn';
    btn.style.cssText = 'position:absolute;top:4px;right:4px;background:rgba(0,0,0,0.5);color:#fff;border:none;border-radius:50%;width:28px;height:28px;font-size:14px;cursor:pointer;display:none;z-index:10;';
    wrapper.style.position = 'relative';
    wrapper.appendChild(btn);
    wrapper.addEventListener('mouseenter', function(){{ if(isEditing) btn.style.display='block'; }});
    wrapper.addEventListener('mouseleave', function(){{ btn.style.display='none'; }});
    btn.addEventListener('click', function(e){{
      e.preventDefault();
      if(!isEditing) return;
      if(confirm('删除这张图片？')) wrapper.remove();
    }});
  }});

  // 底部按钮：默认"修改"→点击后进入编辑→显示"保存"
  var footer = document.querySelector('.footer');
  var actionBtn = document.createElement('button');
  actionBtn.id = 'share-action-btn';
  actionBtn.textContent = '修改';
  actionBtn.style.cssText = 'background:#00CDB8;color:#0D1B2E;border:none;padding:8px 20px;border-radius:16px;font-size:13px;font-weight:600;cursor:pointer;margin-top:12px;';

  actionBtn.addEventListener('click', function(){{
    if(!isEditing){{
      isEditing = true;
      editableEls.forEach(function(el){{
        el.contentEditable = true;
        el.style.boxShadow = 'inset 0 0 0 1px #00CDB8';
        el.style.borderRadius = '4px';
        el.style.padding = '2px 4px';
      }});
      actionBtn.textContent = '保存';
      actionBtn.style.background = '#4a7c59';
    }} else {{
      actionBtn.textContent = '保存中...';
      actionBtn.disabled = true;
      var bodyEl = document.querySelector('.body');
      var bodyHtml = bodyEl ? bodyEl.innerHTML : '';
      fetch('/share/' + shareId + '/edit', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{body_html: bodyHtml}})
      }}).then(function(r){{ return r.json(); }})
        .then(function(data){{
          if(data.success){{
            isEditing = false;
            editableEls.forEach(function(el){{
              el.contentEditable = false;
              el.style.boxShadow = 'none';
              el.style.padding = '';
            }});
            actionBtn.textContent = '修改';
            actionBtn.style.background = '#00CDB8';
            actionBtn.disabled = false;
          }} else {{
            alert('保存失败：' + (data.detail || '未知错误'));
            actionBtn.textContent = '保存';
            actionBtn.disabled = false;
          }}
        }})
        .catch(function(err){{
          alert('保存失败：' + err.message);
          actionBtn.textContent = '保存';
          actionBtn.disabled = false;
        }});
    }}
  }});

  if(footer){{
    footer.appendChild(document.createElement('br'));
    footer.appendChild(actionBtn);
  }} else {{
    var bar = document.createElement('div');
    bar.style.cssText = 'text-align:center;padding:16px;';
    bar.appendChild(actionBtn);
    document.body.appendChild(bar);
  }}
}})();
</script>"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>{title}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;background:#0D1B2E;color:#D0E8FF;font-size:15px;line-height:1.7;-webkit-font-smoothing:antialiased}}
.header{{background:linear-gradient(135deg,#0D2744 0%,#0D1B2E 100%);padding:28px 20px 22px;border-bottom:2px solid {ACCENT}}}
.header-label{{font-size:11px;color:{ACCENT};letter-spacing:2.5px;margin-bottom:10px;text-transform:uppercase;opacity:.9}}
.header-title{{font-size:22px;font-weight:700;line-height:1.35;color:#E8F4FF}}
.body{{padding:0 0 48px}}
.cover-photo{{width:100%;display:block;max-height:260px;object-fit:cover;border-radius:8px}}
.section{{background:#132236;margin:10px 0;padding:18px 20px;border-left:3px solid transparent}}
.section-title{{font-size:11px;font-weight:700;color:{ACCENT};letter-spacing:2px;margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid #1E3550;text-transform:uppercase}}
.para{{font-size:15px;line-height:1.9;color:#C8DFF5;margin-bottom:10px}}
.para:last-child{{margin-bottom:0}}
.item{{padding:8px 0;border-bottom:1px solid #1A3050;font-size:14px;line-height:1.7;color:#B8D4EE}}
.item:last-child{{border-bottom:none}}
.item-label{{font-size:11px;color:#5A7A9A;margin-bottom:3px;letter-spacing:.5px}}
.tag{{display:inline-block;background:#0D2744;color:{ACCENT};font-size:12px;padding:4px 12px;border-radius:20px;margin:3px 4px 3px 0;border:1px solid #1A3A5C}}
.tag-green{{background:#0D2A1E;color:#3DD68C;border-color:#1A4A32}}
.badge-pri{{display:inline-block;font-size:11px;padding:2px 8px;border-radius:4px;margin-right:6px;font-weight:600}}
.pri-high{{background:#2D1620;color:#FF6B6B}}
.pri-mid{{background:#2D2410;color:#FFD166}}
.pri-low{{background:#1A2A3A;color:#7A93B0}}
.supp{{background:#0D2236;border-left:3px solid {ACCENT};padding:14px 16px;font-size:14px;line-height:1.85;white-space:pre-wrap;color:#A0C0E0}}
.photos-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:4px;align-items:start}}
.footer{{text-align:center;font-size:12px;color:#3A5A7A;padding:24px 20px;background:#0D1B2E}}
ul{{padding-left:18px}}
li{{margin-bottom:6px;font-size:14px;line-height:1.7;color:#B8D4EE}}
.outlook{{background:#0D2236;border-radius:8px;padding:16px 18px;margin:10px 20px;font-size:14px;line-height:1.85;color:#90B8D8;font-style:italic;border-left:3px solid {ACCENT}}}
.leads-section{{background:#12213A}}
.lead-item{{padding:9px 0;border-bottom:1px solid #1A3050;font-size:14px;font-weight:500;color:#C0D8F0;line-height:1.6}}
.lead-item:last-child{{border-bottom:none}}
.highlight-section{{background:#0D2A1E}}
.highlight-item{{color:#3DD68C}}
.improve-section{{background:#2A1A10}}
.improve-item{{color:#FFB347}}
</style>
</head>
<body>
<div class="header">
  <div class="header-label">{label}</div>
  <div class="header-title">{title}</div>
</div>
<div class="body">
{body}
</div>
<div class="footer">由智慧展厅管理系统生成</div>
{edit_js}
</body>
</html>"""


def _generate_share_html(report_type: str, data: dict, photos: list,
                         supplementary_text: str, file_name: str,
                         narrative: Optional[dict] = None,
                         share_id: str = None) -> str:
    # 照片去重保护（按 photo_id）
    seen_ids = set()
    unique_photos = []
    for p in (photos or []):
        pid = p.get("id") if isinstance(p, dict) else None
        if pid and pid in seen_ids:
            continue
        if pid:
            seen_ids.add(pid)
        unique_photos.append(p)
    photos = unique_photos

    label = REPORT_TYPE_LABELS.get(report_type, "分析报告")

    if report_type == "customer_brief":
        title = (data.get("reception_theme") or
                 (narrative or {}).get("title") or
                 _clean_filename(file_name))
        body = _body_customer_brief(data, photos, supplementary_text, narrative)
    elif report_type == "business_opportunity":
        title = (narrative or {}).get("title") or "商机简报"
        body = _body_business_opportunity(data, photos, supplementary_text, narrative)
    elif report_type == "reception_review":
        title = (narrative or {}).get("title") or "接待复盘"
        body = _body_reception_review(data, photos, supplementary_text, narrative)
    else:
        # 通用渲染：适配任意新类型，要求 LLM 输出 sections 格式
        title = (data.get("title") or
                 (narrative or {}).get("title") or
                 _clean_filename(file_name))
        body = _body_generic(data, photos, supplementary_text, narrative)

    return _html_wrapper(label, title, body, share_id=share_id)


def _clean_filename(name: str) -> str:
    import re
    name = re.sub(r'\.[^.]+$', '', name or "接待活动")
    return name[:40]


# ==================== 参观简报 HTML（新闻稿风格）====================

def _body_customer_brief(d: dict, photos: list, supp: str, narrative: Optional[dict]) -> str:
    parts = []
    supp = html.escape(supp or "")

    # 1. 封面照片（仅第一张，横向大图）
    if photos:
        cover = photos[0]
        url = _resolve_photo_url(cover)
        caption = html.escape(cover.get("caption", ""))
        cap_html = f'<p style="font-size:12px;color:#aaa;text-align:center;padding:6px 20px 0;">{caption}</p>' if caption else ""
        parts.append(f'<img src="{url}" alt="封面" class="cover-photo">{cap_html}')

    # 2. 导语段落（LLM 生成 or 结构化降级）
    lead_text = ""
    body_paras = []
    outlook_text = ""

    if narrative and narrative.get("lead"):
        lead_text = narrative["lead"]
        body_paras = [p for p in (narrative.get("body") or []) if p and p.strip()]
        outlook_text = narrative.get("outlook", "")
    else:
        # 降级：用结构化数据拼接
        gi = d.get("guest_info") or {}
        parts_lead = []
        if d.get("reception_time"):
            parts_lead.append(d["reception_time"])
        if gi.get("organization") and gi.get("key_guests"):
            guests = "、".join(gi["key_guests"])
            parts_lead.append(f'{gi["organization"]}{guests}等一行')
        elif gi.get("organization"):
            parts_lead.append(gi["organization"])
        if d.get("reception_theme"):
            parts_lead.append(f'莅临参观，就{d["reception_theme"]}进行了深度交流')
        outcomes = d.get("cooperation_outcomes") or []
        if outcomes:
            parts_lead.append(f'，双方达成{outcomes[0]}')
        lead_text = "，".join(parts_lead) + "。" if parts_lead else ""
        outlook_text = (d.get("next_steps") or ["双方表达了进一步深化合作的共同意愿。"])[0]

    if lead_text:
        parts.append(f'<div class="section"><p class="para">{lead_text}</p>'
                     + "".join(f'<p class="para">{p}</p>' for p in body_paras)
                     + '</div>')

    # 3. 重点演示（保留，用 tag 样式简洁呈现）
    demos = d.get("key_demonstrations") or []
    if demos:
        tags = "".join(f'<span class="tag">{i.get("item","")}</span>' for i in demos[:6])
        parts.append(f'<div class="section"><div class="section-title">参观亮点</div>{tags}</div>')

    # 4. 后续机会（替代原来的"后续跟进"和"结语"）
    if outlook_text:
        parts.append(f'<div class="outlook">{outlook_text}</div>')

    # 5. 补充说明
    if supp and supp.strip():
        parts.append(f'<div class="section"><div class="section-title">补充说明</div><div class="supp">{supp}</div></div>')

    # 6. 其余照片（网格，放在结尾）
    if len(photos) > 1:
        remaining = photos[1:]
        grid_items = "".join(
            f'<div>{_photo_to_img_tag(p, "width:100%;border-radius:6px;display:block;height:auto;")}</div>'
            for p in remaining
        )
        parts.append(f'<div class="section"><div class="section-title">现场照片</div><div class="photos-grid">{grid_items}</div></div>')

    return "\n".join(parts)


def _resolve_photo_url(photo: dict) -> str:
    url = photo.get("url", "")
    if photo.get("type") == "local":
        local_path = BASE_DIR / url.lstrip("/")
        if local_path.exists():
            try:
                raw = local_path.read_bytes()
                ext = local_path.suffix.lower().lstrip(".")
                mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
                return f"data:{mime};base64,{base64.b64encode(raw).decode()}"
            except Exception:
                pass
    return url


# ==================== 商机简报 HTML ====================

def _body_business_opportunity(d: dict, photos: list, supp: str, narrative: Optional[dict] = None) -> str:
    parts = []
    n = narrative or {}
    supp = html.escape(supp or "")

    # 1. 封面照片（仅第一张）
    if photos:
        cover = photos[0]
        url = _resolve_photo_url(cover)
        caption = html.escape(cover.get("caption", ""))
        cap_html = f'<p style="font-size:12px;color:#aaa;text-align:center;padding:6px 20px 0;">{caption}</p>' if caption else ""
        parts.append(f'<img src="{url}" alt="封面" class="cover-photo">{cap_html}')

    # 2. 整体概述（LLM or 结构化降级）
    summary_text = n.get("summary") or d.get("summary") or d.get("discussion_overview") or ""
    if summary_text:
        parts.append(f'<div class="section"><div class="section-title">商机概述</div><p class="para">{summary_text}</p></div>')

    # 3. 核心商机线索（置顶突出）
    key_leads = n.get("key_leads") or d.get("key_leads") or []
    if key_leads:
        items = "".join(f'<div class="lead-item">⚡ {lead}</div>' for lead in key_leads[:5])
        parts.append(f'<div class="section leads-section"><div class="section-title">核心商机线索</div>{items}</div>')

    # 4. 建议跟进动作（LLM）
    next_actions_narrative = n.get("next_actions") or []
    if next_actions_narrative:
        items = "".join(f'<div class="item">→ {a}</div>' for a in next_actions_narrative[:3])
        parts.append(f'<div class="section"><div class="section-title">优先跟进</div>{items}</div>')
    else:
        # 降级：使用结构化数据
        actions = d.get("next_actions") or []
        if actions:
            pri_map = {"高": "pri-high", "中": "pri-mid", "低": "pri-low"}
            def _action_row(i):
                pri = i.get("priority", "中")
                notes_html = f'<div style="font-size:12px;color:#999;margin-top:2px;">{i["notes"]}</div>' if i.get("notes") else ""
                return f'<div class="item"><span class="badge-pri {pri_map.get(pri,"pri-mid")}">{pri}</span><b>{i.get("action","")}</b>{notes_html}</div>'
            rows = "".join(_action_row(i) for i in actions[:6])
            parts.append(f'<div class="section"><div class="section-title">下一步行动</div>{rows}</div>')

    # 5. 客户感兴趣点（标签云）
    interests = d.get("interest_points") or []
    if interests:
        tags = "".join(f'<span class="tag">{i}</span>' for i in interests[:8])
        parts.append(f'<div class="section"><div class="section-title">客户感兴趣点</div>{tags}</div>')

    # 6. 客户提问 & 质疑
    questions = d.get("questions_asked") or []
    doubts = d.get("doubts_objections") or []
    if questions or doubts:
        rows = "".join(f'<div class="item">❓ {q}</div>' for q in questions[:6])
        rows += "".join(f'<div class="item"><b>{i.get("topic","")}</b>：{i.get("content","")}</div>' for i in doubts[:4])
        parts.append(f'<div class="section"><div class="section-title">客户关注与质疑</div>{rows}</div>')

    # 7. 结语（LLM）
    closing = n.get("closing") or ""
    if closing:
        parts.append(f'<div class="outlook">{closing}</div>')

    # 8. 补充说明
    if supp and supp.strip():
        parts.append(f'<div class="section"><div class="section-title">补充说明</div><div class="supp">{supp}</div></div>')

    # 9. 其余照片网格
    if len(photos) > 1:
        remaining = photos[1:]
        grid_items = "".join(
            f'<div>{_photo_to_img_tag(p, "width:100%;border-radius:6px;display:block;height:auto;")}</div>'
            for p in remaining
        )
        parts.append(f'<div class="section"><div class="section-title">现场照片</div><div class="photos-grid">{grid_items}</div></div>')

    return "\n".join(parts)


# ==================== 接待复盘 HTML ====================

def _body_reception_review(d: dict, photos: list, supp: str, narrative: Optional[dict] = None) -> str:
    parts = []
    n = narrative or {}
    ov = d.get("reception_overview") or {}
    gp = d.get("guide_performance") or {}
    supp = html.escape(supp or "")

    # 1. 封面照片（仅第一张）
    if photos:
        cover = photos[0]
        url = _resolve_photo_url(cover)
        caption = html.escape(cover.get("caption", ""))
        cap_html = f'<p style="font-size:12px;color:#aaa;text-align:center;padding:6px 20px 0;">{caption}</p>' if caption else ""
        parts.append(f'<img src="{url}" alt="封面" class="cover-photo">{cap_html}')

    # 2. 整体概述（LLM or 结构化降级）
    summary_text = n.get("summary") or d.get("summary") or ""
    if not summary_text and ov.get("atmosphere"):
        summary_text = f'本次接待整体氛围{ov["atmosphere"]}，客户参与度{ov.get("engagement","中")}。'
    if summary_text:
        parts.append(f'<div class="section"><div class="section-title">复盘概述</div><p class="para">{summary_text}</p></div>')

    # 3. 接待亮点（置顶展示）
    highlights_list = n.get("highlights") or d.get("top_highlights") or []
    if highlights_list:
        items = "".join(f'<div class="lead-item highlight-item">✓ {h}</div>' for h in highlights_list[:3])
        parts.append(f'<div class="section leads-section highlight-section"><div class="section-title">接待亮点</div>{items}</div>')

    # 4. 待改进事项（置顶展示）
    improvements_top = n.get("improvements") or d.get("top_improvements") or []
    if improvements_top:
        items = "".join(f'<div class="lead-item improve-item">→ {i}</div>' for i in improvements_top[:3])
        parts.append(f'<div class="section leads-section improve-section"><div class="section-title">待改进</div>{items}</div>')

    # 5. 接待概况
    info_rows = ""
    if ov.get("duration"):
        info_rows += f'<div class="item"><div class="item-label">接待时长</div>{ov["duration"]}</div>'
    if ov.get("client_type"):
        info_rows += f'<div class="item"><div class="item-label">客户类型</div>{ov["client_type"]}</div>'
    if ov.get("atmosphere"):
        info_rows += f'<div class="item"><div class="item-label">整体氛围</div>{ov["atmosphere"]}</div>'
    if ov.get("engagement"):
        color = "#4a7c59" if ov["engagement"] == "高" else "#c9a227" if ov["engagement"] == "中" else "#999"
        info_rows += f'<div class="item"><div class="item-label">参与度</div><span style="color:{color};font-weight:700;">{ov["engagement"]}</span></div>'
    if info_rows:
        parts.append(f'<div class="section"><div class="section-title">接待概况</div>{info_rows}</div>')

    # 6. 有效环节（详细）
    effective = d.get("effective_aspects") or []
    if effective:
        rows = "".join(f'<div class="item"><b>{i.get("aspect","")}</b>：{i.get("description","")}</div>' for i in effective[:6])
        parts.append(f'<div class="section"><div class="section-title">有效环节</div>{rows}</div>')

    # 7. 需调优环节（详细）
    needs_imp = d.get("needs_improvement") or []
    if needs_imp:
        sev_map = {"高": "#d64545", "中": "#c9a227", "低": "#999"}
        rows = "".join(f'<div class="item"><span style="color:{sev_map.get(i.get("severity","中"),"#999")};font-weight:700;margin-right:6px;">[{i.get("severity","中")}]</span><b>{i.get("aspect","")}</b>：{i.get("issue","")}</div>' for i in needs_imp[:6])
        parts.append(f'<div class="section"><div class="section-title">需调优环节</div>{rows}</div>')

    # 8. 讲解员表现
    if gp.get("overall") or gp.get("highlights") or gp.get("improvements"):
        gp_html = ""
        if gp.get("overall"):
            gp_html += f'<p class="para">{gp["overall"]}</p>'
        if gp.get("highlights"):
            gp_html += f'<div style="margin-top:8px;"><div class="item-label" style="color:#4a7c59;margin-bottom:4px;">亮点</div><ul>{"".join(f"<li>{h}</li>" for h in gp["highlights"][:4])}</ul></div>'
        if gp.get("improvements"):
            gp_html += f'<div style="margin-top:8px;"><div class="item-label" style="margin-bottom:4px;">改进方向</div><ul>{"".join(f"<li>{h}</li>" for h in gp["improvements"][:4])}</ul></div>'
        parts.append(f'<div class="section"><div class="section-title">讲解员表现</div>{gp_html}</div>')

    # 9. 优化建议（LLM or 结构化）
    top_suggestions = n.get("top_suggestions") or []
    if top_suggestions:
        items = "".join(f'<div class="item">💡 {s}</div>' for s in top_suggestions[:3])
        parts.append(f'<div class="section"><div class="section-title">优化建议</div>{items}</div>')
    else:
        suggestions = d.get("optimization_suggestions") or []
        if suggestions:
            pri_map = {"高": "pri-high", "中": "pri-mid", "低": "pri-low"}
            rows = "".join(f'<div class="item"><span class="badge-pri {pri_map.get(i.get("priority","中"),"pri-mid")}">{i.get("priority","中")}</span><b>{i.get("area","")}</b>：{i.get("suggestion","")}</div>' for i in suggestions[:6])
            parts.append(f'<div class="section"><div class="section-title">优化建议</div>{rows}</div>')

    # 10. 结语（LLM）
    closing = n.get("closing") or ""
    if closing:
        parts.append(f'<div class="outlook">{closing}</div>')

    # 11. 补充说明
    if supp and supp.strip():
        parts.append(f'<div class="section"><div class="section-title">补充说明</div><div class="supp">{supp}</div></div>')

    # 12. 其余照片网格
    if len(photos) > 1:
        remaining = photos[1:]
        grid_items = "".join(
            f'<div>{_photo_to_img_tag(p, "width:100%;border-radius:6px;display:block;height:auto;")}</div>'
            for p in remaining
        )
        parts.append(f'<div class="section"><div class="section-title">现场照片</div><div class="photos-grid">{grid_items}</div></div>')

    return "\n".join(parts)


# ==================== 通用渲染器（P2 — 适配任意新分析类型）====================

def _body_generic(data: dict, photos: list, supp: str, narrative: Optional[dict] = None) -> str:
    """
    通用段落渲染器。LLM 输出应包含标准化 sections 数组：
      {"title": "...", "sections": [
        {"type": "text",    "title": "...", "content": "..."},
        {"type": "list",    "title": "...", "items": ["..."]},
        {"type": "kv",      "title": "...", "items": [{"label":"...","value":"..."}]},
        {"type": "tags",    "title": "...", "items": ["..."]},
        {"type": "actions", "title": "...", "items": [{"action":"...","priority":"高","notes":"..."}]}
      ]}
    兜底：直接渲染 raw_content 或 JSON dump。
    """
    parts = []
    n = narrative or {}
    supp = html.escape(supp or "")

    # 封面照片
    if photos:
        cover = photos[0]
        url = _resolve_photo_url(cover)
        caption = html.escape(cover.get("caption", ""))
        cap_html = f'<p style="font-size:12px;color:#aaa;text-align:center;padding:6px 20px 0;">{caption}</p>' if caption else ""
        parts.append(f'<img src="{url}" alt="封面" class="cover-photo">{cap_html}')

    # summary（顶部一句话摘要）
    summary = data.get("summary") or n.get("summary") or ""
    if summary:
        parts.append(f'<div class="section"><p class="para">{summary}</p></div>')

    # sections 通用渲染
    sections = data.get("sections") or []
    pri_map = {"高": "pri-high", "中": "pri-mid", "低": "pri-low"}
    for sec in sections:
        sec_type = sec.get("type", "text")
        sec_title = sec.get("title", "")
        title_html = f'<div class="section-title">{sec_title}</div>' if sec_title else ""

        if sec_type == "text":
            content = sec.get("content", "")
            if content:
                parts.append(f'<div class="section">{title_html}<p class="para">{content}</p></div>')

        elif sec_type == "list":
            items = sec.get("items") or []
            if items:
                rows = "".join(f'<div class="item para">• {i}</div>' for i in items)
                parts.append(f'<div class="section">{title_html}{rows}</div>')

        elif sec_type == "kv":
            items = sec.get("items") or []
            if items:
                rows = "".join(
                    f'<div class="item"><div class="item-label">{i.get("label","")}</div>{i.get("value","")}</div>'
                    for i in items
                )
                parts.append(f'<div class="section">{title_html}{rows}</div>')

        elif sec_type == "tags":
            items = sec.get("items") or []
            if items:
                tags = "".join(f'<span class="tag">{i}</span>' for i in items)
                parts.append(f'<div class="section">{title_html}{tags}</div>')

        elif sec_type == "actions":
            items = sec.get("items") or []
            if items:
                rows = "".join(
                    f'<div class="item">'
                    f'<span class="badge-pri {pri_map.get(i.get("priority","中"),"pri-mid")}">{i.get("priority","中")}</span>'
                    f'<b>{i.get("action","")}</b>'
                    + (f'<div style="font-size:12px;color:#999;margin-top:2px;">{i["notes"]}</div>' if i.get("notes") else "")
                    + '</div>'
                    for i in items
                )
                parts.append(f'<div class="section">{title_html}{rows}</div>')

    # 兜底：sections 为空时渲染 raw_content 或 JSON
    if not sections:
        raw = data.get("raw_content") or ""
        if raw:
            parts.append(f'<div class="section"><p class="para" style="white-space:pre-wrap;">{raw}</p></div>')
        elif data:
            parts.append(f'<div class="section"><pre style="font-size:12px;overflow-x:auto;">{json.dumps(data, ensure_ascii=False, indent=2)}</pre></div>')

    # 补充说明
    if supp and supp.strip():
        parts.append(f'<div class="section"><div class="section-title">补充说明</div><div class="supp">{supp}</div></div>')

    # 其余照片网格
    if len(photos) > 1:
        remaining = photos[1:]
        grid_items = "".join(
            f'<div>{_photo_to_img_tag(p, "width:100%;border-radius:6px;display:block;height:auto;")}</div>'
            for p in remaining
        )
        parts.append(f'<div class="section"><div class="section-title">照片</div><div class="photos-grid">{grid_items}</div></div>')

    return "\n".join(parts)
