#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 服务 - 大模型分析
支持: MiniMax, Kimi, 通义千问, 豆包, 智谱GLM
"""

import json
import asyncio
import httpx
import time
from typing import Optional
from pathlib import Path
import logging

from config import llm_settings

# ── obs 可观测性（本地 obs/ 模块）─────────────────────────────────
try:
    from obs.db import write_call as _obs_write
    from obs.pricing import calc_cost as _obs_calc_cost
    from obs.patch import get_trace_id as _obs_get_trace_id, set_session as _obs_set_session
    try:
        from obs.patch import _session_var as _obs_session_var
        def _obs_get_session() -> str:
            return _obs_session_var.get()
    except Exception:
        def _obs_get_session() -> str:
            return ""
    _OBS_ENABLED = True
except Exception:
    _OBS_ENABLED = False
    _obs_get_trace_id = lambda: None
    _obs_get_session = lambda: ""


import re as _re


def _sanitize_error(msg: str) -> str:
    """脱敏 error_msg：屏蔽 API key 特征，截断超长内容"""
    if not msg:
        return msg
    msg = _re.sub(r'(sk-[A-Za-z0-9]{8,})', '[REDACTED_KEY]', msg)
    msg = _re.sub(r'(Bearer\s+[A-Za-z0-9\-_\.]{8,})', 'Bearer [REDACTED]', msg)
    msg = _re.sub(r'([Aa][Pp][Ii][_-]?[Kk][Ee][Yy]\s*[=:]\s*\S+)', 'api_key=[REDACTED]', msg)
    if len(msg) > 500:
        msg = msg[:500] + '...[truncated]'
    return msg


def _classify_error(error_msg: str) -> Optional[str]:
    """根据 error_msg 自动分类 error_type"""
    if not error_msg:
        return None
    msg = error_msg.lower()
    if 'timeout' in msg or 'timed out' in msg or 'read timeout' in msg:
        return 'timeout'
    if 'rate limit' in msg or '429' in msg or 'too many requests' in msg:
        return 'rate_limit'
    if '401' in msg or 'unauthorized' in msg or 'invalid api key' in msg or 'authentication' in msg:
        return 'auth'
    if 'connection' in msg or 'network' in msg or 'refused' in msg or 'unreachable' in msg:
        return 'network'
    if 'json' in msg or 'parse' in msg or 'decode' in msg or 'invalid response' in msg:
        return 'parse_error'
    return 'unknown'


def _obs_provider(url: str) -> str:
    u = url.lower()
    if "moonshot" in u: return "moonshot"
    if "dashscope" in u or "aliyun" in u: return "qwen"
    if "minimax" in u: return "minimax"
    if "volces" in u: return "doubao"
    if "bigmodel" in u or "zhipu" in u: return "zhipu"
    return "unknown"


def _obs_record(url, model, usage, latency_ms, status, operation="analyze", error_msg=None, prompt_chars=None):
    if not _OBS_ENABLED:
        return
    try:
        in_tok  = usage.get("prompt_tokens")
        out_tok = usage.get("completion_tokens")
        cost = _obs_calc_cost(model, in_tok, out_tok) if in_tok is not None and out_tok is not None else None
        error_type = _classify_error(error_msg) if error_msg else None
        sanitized_error = _sanitize_error(error_msg) if error_msg else None
        _obs_write(
            project="echomind",
            operation=operation,
            provider=_obs_provider(url),
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=latency_ms,
            cost_cny=cost,
            status=status,
            error_msg=sanitized_error,
            error_type=error_type,
            trace_id=_obs_get_trace_id() or None,
            session_id=_obs_get_session() or None,
            prompt_chars=prompt_chars,
        )
    except Exception:
        pass

logger = logging.getLogger(__name__)


class LLMService:
    """LLM 服务统一接口"""

    def __init__(self):
        self.provider = llm_settings.PROVIDER
        self._load_prompts()
        logger.info(f"LLM服务初始化，提供商: {self.provider}")

    # 内置兜底 Prompt 文件（新类型通过 DB 的 AnalysisTaskType.prompt_key 配置）
    _BUILTIN_PROMPT_FILES = {
        "customer_brief": "customer_brief.md",
        "business_opportunity": "business_opportunity.md",
        "reception_review": "reception_review.md",
        "meeting_analysis": "meeting_analyzer.md",
        "customer_brief_share": "customer_brief_share.md",
        "business_opportunity_share": "business_opportunity_share.md",
        "reception_review_share": "reception_review_share.md",
        "expert_notes_organizer": "expert_notes_organizer.md",
    }

    def _load_prompts(self):
        """从 prompts/ 目录预加载内置 prompt 到内存缓存（DB 优先，文件兜底）"""
        prompts_dir = Path(__file__).parent.parent / "prompts"
        self._prompt_cache = {}
        for key, filename in self._BUILTIN_PROMPT_FILES.items():
            path = prompts_dir / filename
            if path.exists():
                self._prompt_cache[key] = path.read_text(encoding="utf-8")
        self.meeting_prompt = self._prompt_cache.get("meeting_analysis", self._default_meeting_prompt())

    def _get_prompt(self, report_type: str, db=None) -> str:
        """
        获取 Prompt 模板。查找顺序：
        1. PromptTemplate DB（name == report_type，is_active=True）
        2. AnalysisTaskType.prompt_key → 再走 PromptTemplate DB
        3. 内存文件缓存（_BUILTIN_PROMPT_FILES）
        4. 默认 meeting_analysis
        """
        if db is not None:
            try:
                from models import PromptTemplate, AnalysisTaskType
                # 直接按 report_type 查激活 prompt
                tpl = db.query(PromptTemplate).filter(
                    PromptTemplate.name == report_type,
                    PromptTemplate.is_active == True
                ).first()
                if tpl:
                    return tpl.content

                # 如果没有，通过 AnalysisTaskType.prompt_key 间接查
                task_type = db.query(AnalysisTaskType).filter(
                    AnalysisTaskType.name == report_type
                ).first()
                if task_type and task_type.prompt_key and task_type.prompt_key != report_type:
                    tpl2 = db.query(PromptTemplate).filter(
                        PromptTemplate.name == task_type.prompt_key,
                        PromptTemplate.is_active == True
                    ).first()
                    if tpl2:
                        return tpl2.content
            except Exception as e:
                logger.warning(f"从数据库加载Prompt失败({report_type}): {e}")

        return self._prompt_cache.get(report_type, self._prompt_cache.get("meeting_analysis", self._default_meeting_prompt()))

    async def analyze(self, text: str, mode: str = "meeting", report_type: str = None, db=None, context_data: str = "", obs_operation: str = None) -> dict:
        """
        分析文字内容
        :param text: 待分析的文本
        :param report_type: 报告类型 (customer_brief|business_opportunity|reception_review|meeting_analysis)
        :param db: 数据库会话
        :param context_data: 补充上下文
        :return: {"success": bool, "data": dict, "error": str}
        """
        if report_type is None:
            report_type = "meeting_analysis"

        _op = obs_operation or report_type

        try:
            prompt_template = self._get_prompt(report_type, db)
            prompt = prompt_template.replace("{text}", text)
            if "{context_data}" in prompt:
                ctx = context_data if context_data else "（暂无补充上下文数据，仅基于录音分析）"
                prompt = prompt.replace("{context_data}", ctx)

            if self.provider == "minimax":
                return await self._call_minimax(prompt, operation=_op)
            elif self.provider == "kimi":
                return await self._call_kimi(prompt, operation=_op)
            elif self.provider == "qwen":
                return await self._call_qwen(prompt, operation=_op)
            elif self.provider == "doubao":
                return await self._call_doubao(prompt, operation=_op)
            elif self.provider == "zhipu":
                return await self._call_zhipu(prompt, operation=_op)
            elif self.provider == "mock":
                return await self._mock_analyze(prompt)
            else:
                return {"success": False, "data": None, "error": f"未知的LLM提供商: {self.provider}"}

        except Exception as e:
            logger.error(f"LLM分析异常: {str(e)}")
            return {"success": False, "data": None, "error": str(e)}

    async def generate_text(self, prompt_type: str, data: dict, db=None) -> dict:
        """
        叙事化文本生成：用于将结构化报告数据转换为流畅的段落文字。
        返回 {"success": bool, "data": dict}，data 是 LLM 输出的 JSON（不强制特定结构）。
        """
        try:
            prompt_template = self._get_prompt(prompt_type, db)
            import json as _json
            data_str = _json.dumps(data, ensure_ascii=False, indent=2)
            prompt = prompt_template.replace("{data}", data_str)

            op = f"gen:{prompt_type}"
            if self.provider == "minimax":
                return await self._call_minimax(prompt, operation=op)
            elif self.provider == "kimi":
                return await self._call_kimi(prompt, operation=op)
            elif self.provider == "qwen":
                return await self._call_qwen(prompt, operation=op)
            elif self.provider == "doubao":
                return await self._call_doubao(prompt, operation=op)
            elif self.provider == "zhipu":
                return await self._call_zhipu(prompt, operation=op)
            else:
                # mock：返回简单占位文本
                return {"success": True, "data": {
                    "title": data.get("reception_theme", "参观简报"),
                    "lead": "（模拟模式，请配置 LLM API）",
                    "body": [],
                    "outlook": ""
                }}
        except Exception as e:
            logger.error(f"叙事化生成异常({prompt_type}): {e}")
            return {"success": False, "data": None, "error": str(e)}

    async def _post_openai_compat(self, url: str, api_key: str, model: str, prompt: str, timeout: int = 120, operation: str = "analyze") -> dict:
        """通用 OpenAI 兼容接口调用"""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7
        }
        _t0 = time.monotonic()
        # trust_env=False：禁止继承系统代理，LLM 服务商均为国内直连
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            resp = await client.post(url, json=data, headers=headers)
            _latency = int((time.monotonic() - _t0) * 1000)
            if resp.status_code == 200:
                result = resp.json()
                choices = result.get("choices")
                if choices:
                    content = choices[0]["message"]["content"]
                    _obs_record(url, model, result.get("usage") or {}, _latency, "ok", operation=operation, prompt_chars=len(prompt))
                    return {"success": True, "data": self._parse_analysis(content)}
                else:
                    err = (result.get("base_resp", {}).get("status_msg")
                           or result.get("error", {}).get("message")
                           or result.get("message")
                           or "API返回空响应")
                    logger.error(f"API格式错误: {result}")
                    _obs_record(url, model, {}, _latency, "error", operation=operation, error_msg=err, prompt_chars=len(prompt))
                    return {"success": False, "data": None, "error": err}
            else:
                logger.error(f"API错误 [{resp.status_code}]: {resp.text}")
                _obs_record(url, model, {}, _latency, "error", operation=operation, error_msg=f"HTTP {resp.status_code}", prompt_chars=len(prompt))
                return {"success": False, "data": None, "error": f"API错误: {resp.status_code}"}

    # ==================== MiniMax ====================

    async def _call_minimax(self, prompt: str, operation: str = "analyze") -> dict:
        api_key = llm_settings.MINIMAX_API_KEY
        if not api_key:
            return await self._mock_analyze(prompt)
        url = f"{llm_settings.MINIMAX_BASE_URL}/text/chatcompletion_v2"
        try:
            return await self._post_openai_compat(url, api_key, llm_settings.MINIMAX_MODEL, prompt, operation=operation)
        except Exception as e:
            logger.error(f"MiniMax请求异常: {e}")
            return {"success": False, "data": None, "error": str(e)}

    # ==================== Kimi ====================

    async def _call_kimi(self, prompt: str, operation: str = "analyze") -> dict:
        api_key = llm_settings.KIMI_API_KEY
        if not api_key:
            return await self._mock_analyze(prompt)
        url = f"{llm_settings.KIMI_BASE_URL}/chat/completions"
        try:
            return await self._post_openai_compat(url, api_key, llm_settings.KIMI_MODEL, prompt, operation=operation)
        except Exception as e:
            logger.error(f"Kimi请求异常: {e}")
            return {"success": False, "data": None, "error": str(e)}

    # ==================== 通义千问 ====================

    async def _call_qwen(self, prompt: str, operation: str = "analyze") -> dict:
        api_key = llm_settings.QWEN_API_KEY
        if not api_key:
            return await self._mock_analyze(prompt)
        url = f"{llm_settings.QWEN_BASE_URL}/chat/completions"
        try:
            return await self._post_openai_compat(url, api_key, llm_settings.QWEN_MODEL, prompt, operation=operation)
        except Exception as e:
            logger.error(f"通义千问请求异常: {e}")
            return {"success": False, "data": None, "error": str(e)}

    # ==================== 豆包 ====================

    async def _call_doubao(self, prompt: str, operation: str = "analyze") -> dict:
        api_key = llm_settings.DOUBAO_API_KEY
        if not api_key:
            return await self._mock_analyze(prompt)
        url = f"{llm_settings.DOUBAO_BASE_URL}/chat/completions"
        try:
            return await self._post_openai_compat(url, api_key, llm_settings.DOUBAO_MODEL, prompt, operation=operation)
        except Exception as e:
            logger.error(f"豆包请求异常: {e}")
            return {"success": False, "data": None, "error": str(e)}

    # ==================== 智谱 GLM ====================

    async def _call_zhipu(self, prompt: str, operation: str = "analyze") -> dict:
        api_key = llm_settings.ZHIPU_API_KEY
        if not api_key:
            return await self._mock_analyze(prompt)
        url = f"{llm_settings.ZHIPU_BASE_URL}/chat/completions"
        try:
            return await self._post_openai_compat(url, api_key, llm_settings.ZHIPU_MODEL, prompt, operation=operation)
        except Exception as e:
            logger.error(f"智谱GLM请求异常: {e}")
            return {"success": False, "data": None, "error": str(e)}

    # ==================== 模拟分析 ====================

    async def _mock_analyze(self, prompt: str) -> dict:
        """模拟分析 - 用于测试或未配置API时"""
        logger.info("使用模拟分析模式")
        await asyncio.sleep(2)
        mock_result = {
            "highlights": [
                {"type": "亮点", "content": "项目经验丰富，从0到1项目经验"},
                {"type": "亮点", "content": "表达逻辑清晰，回答有条理"},
            ],
            "suggestions": [
                {"type": "建议", "content": "补充具体的数字成果"},
            ],
            "summary": ["整体表现良好"],
            "score": 78,
            "tags": ["项目经验", "数据思维"]
        }
        return {"success": True, "data": mock_result}

    def _parse_analysis(self, content: str) -> dict:
        """解析 LLM 返回的分析结果"""
        try:
            # 剥离 Qwen3 等模型的思考标签
            import re
            content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            return json.loads(content.strip())
        except json.JSONDecodeError:
            logger.warning("LLM返回内容无法解析为JSON，返回原文")
            return {
                "raw_content": content,
                "highlights": [],
                "suggestions": [],
                "concerns": [],
                "summary": [content],
                "score": 0,
                "tags": []
            }

    async def extract_supplement_fields(self, supplement_text: str, report_type: str, current_data: dict) -> dict:
        """
        从用户补充文字中提取结构化字段，用于 AI 辅助补录功能。
        返回 {"success": bool, "data": dict, "extracted_fields": list[str], "error": str}
        """
        prompt = self._build_extract_prompt(supplement_text, report_type, current_data)
        try:
            if self.provider == "minimax":
                result = await self._call_minimax(prompt, operation="extract")
            elif self.provider == "kimi":
                result = await self._call_kimi(prompt, operation="extract")
            elif self.provider == "qwen":
                result = await self._call_qwen(prompt, operation="extract")
            elif self.provider == "doubao":
                result = await self._call_doubao(prompt, operation="extract")
            elif self.provider == "zhipu":
                result = await self._call_zhipu(prompt, operation="extract")
            elif self.provider == "mock":
                result = self._mock_extract(report_type)
            else:
                return {"success": False, "data": None, "extracted_fields": [], "error": f"未知的LLM提供商: {self.provider}"}

            if not result.get("success") or not result.get("data"):
                return {"success": False, "data": None, "extracted_fields": [], "error": result.get("error", "提取失败")}

            extracted = result["data"]
            # 计算实际提取到了哪些字段（非空的叶子字段名）
            extracted_fields = self._collect_field_names(extracted)
            return {"success": True, "data": extracted, "extracted_fields": extracted_fields}

        except Exception as e:
            logger.error(f"字段提取异常: {e}")
            return {"success": False, "data": None, "extracted_fields": [], "error": str(e)}

    def _build_extract_prompt(self, supplement_text: str, report_type: str, current_data: dict) -> str:
        """根据报告类型构建字段提取 Prompt"""
        missing_hints = self._get_missing_field_hints(report_type, current_data)

        if report_type == "customer_brief":
            fields_desc = """请从文字中提取以下字段（能提取多少提取多少，无法确定的字段直接忽略，不要猜测）：
- reception_time: 接待/参观的时间（字符串，如"2025年5月8日下午"）
- reception_location: 接待地点（字符串，如"北京智慧展厅"）
- reception_theme: 接待主题（字符串，如"参观智慧展厅暨产品交流会"）
- guest_info: 来访嘉宾信息（对象），包含：
  - organization: 来访单位/机构/公司名称（字符串）
  - key_guests: 主要嘉宾姓名列表（字符串数组，如["张总","李经理"]）
  - group_size: 来访总人数（字符串，如"12人"）
  - guest_background: 来访方背景简介（字符串，一句话）
- cooperation_outcomes: 达成的合作意向或共识（字符串数组，每条一句话）
- next_steps: 后续待推进的事项（字符串数组，每条一句话）"""

        elif report_type == "business_opportunity":
            fields_desc = """请从文字中提取以下字段（能提取多少提取多少，无法确定的字段直接忽略，不要猜测）：
- discussion_overview: 本次讨论要点概述（字符串，3-5句话）
- questions_asked: 客户提出的问题列表（字符串数组）
- interest_points: 客户明显感兴趣的内容（字符串数组）
- next_actions: 建议跟进动作列表（对象数组，每个对象含 action、priority（高/中/低）、notes）"""

        elif report_type == "reception_review":
            fields_desc = """请从文字中提取以下字段（能提取多少提取多少，无法确定的字段直接忽略，不要猜测）：
- reception_overview: 接待概况（对象），包含：
  - duration: 接待时长（字符串，如"约45分钟"）
  - client_type: 客户类型（字符串，如"采购决策者"）
  - atmosphere: 整体氛围（字符串，如"积极热情"）
- guide_performance: 讲解员表现（对象），包含：
  - overall: 整体评价（字符串，1-2句话）
  - highlights: 亮点列表（字符串数组）
  - improvements: 改进方向列表（字符串数组）"""
        else:
            fields_desc = "请提取文字中所有有价值的结构化信息，以JSON格式返回。"

        missing_str = f"\n当前报告中待补充的字段：{missing_hints}\n请重点关注这些字段。" if missing_hints else ""

        return f"""你是一个信息提取助手，善于从自然语言描述中准确提取结构化字段。

{fields_desc}{missing_str}

**重要规则**：
1. 只提取能从文字中明确得出的信息，不要推断或补充
2. 提取结果必须是合法 JSON，只包含你能提取的字段
3. 字符串数组的每个元素用中文，简洁完整
4. 不要添加任何解释文字，只返回 JSON

用户补充说明文字：
{supplement_text}

请直接返回 JSON（不需要 markdown 代码块）："""

    def _get_missing_field_hints(self, report_type: str, current_data: dict) -> str:
        """找出当前数据中为空的字段，生成提示字符串"""
        if not current_data:
            return ""

        missing = []
        if report_type == "customer_brief":
            checks = [
                ("reception_time", "接待时间"),
                ("reception_location", "接待地点"),
                ("reception_theme", "接待主题"),
            ]
            for key, label in checks:
                if not current_data.get(key):
                    missing.append(label)
            gi = current_data.get("guest_info") or {}
            if not gi.get("organization"):
                missing.append("来访单位")
            if not gi.get("key_guests"):
                missing.append("主要嘉宾")
            if not gi.get("group_size"):
                missing.append("来访人数")

        elif report_type == "business_opportunity":
            if not current_data.get("discussion_overview"):
                missing.append("讨论要点")

        elif report_type == "reception_review":
            ov = current_data.get("reception_overview") or {}
            if not ov.get("duration"):
                missing.append("接待时长")
            if not ov.get("client_type"):
                missing.append("客户类型")

        return "、".join(missing) if missing else ""

    def _collect_field_names(self, data: dict, prefix: str = "") -> list:
        """递归收集提取结果中非空的叶子字段名"""
        fields = []
        for key, val in (data or {}).items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(val, dict):
                fields.extend(self._collect_field_names(val, full_key))
            elif val is not None and val != "" and val != []:
                fields.append(full_key)
        return fields

    def _mock_extract(self, report_type: str) -> dict:
        """模拟提取结果（用于测试）"""
        if report_type == "customer_brief":
            return {"success": True, "data": {
                "reception_time": "2025年5月8日下午",
                "guest_info": {
                    "organization": "某科技有限公司（模拟）",
                    "key_guests": ["张总", "李经理"],
                    "group_size": "5人"
                }
            }}
        return {"success": True, "data": {}}

    def _default_meeting_prompt(self) -> str:
        return """你是一位专业的商业会议分析师，擅长从对话文本中提炼关键信息。请分析以下内容并以JSON格式输出。

{text}"""
