"""
在 chat.completions.create（sync + async）层打补丁
覆盖所有调用路径，包括 ingest_engine 等直接构造 client 的场景
"""

import re as _re
import time
import contextvars
from typing import Any, Optional

from obs.db import write_call
from obs.pricing import calc_cost

# 由各子项目在 init() 时设置
_project: str = "unknown"

# 业务层可选设置当前 operation 名（如 "ingest" / "query"）
_op_var: contextvars.ContextVar[str] = contextvars.ContextVar("obs_op", default="")
_session_var: contextvars.ContextVar[str] = contextvars.ContextVar("obs_session", default="")
_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("obs_trace_id", default="")

_patched = False


def set_project(name: str) -> None:
    global _project
    _project = name


def set_operation(name: str) -> None:
    _op_var.set(name)


def set_session(session_id: str) -> None:
    _session_var.set(session_id)


def set_trace_id(trace_id: str) -> None:
    _trace_id_var.set(trace_id)


def get_trace_id() -> str:
    return _trace_id_var.get()


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


def _provider_from_base_url(base_url: str) -> str:
    url = (base_url or "").lower()
    if "moonshot" in url:
        return "moonshot"
    if "aliyun" in url or "qwen" in url or "dashscope" in url:
        return "qwen"
    if "openai" in url:
        return "openai"
    return url.split("/")[2] if "//" in url else "unknown"


def _record(model: str, base_url: str, input_tok, output_tok, latency_ms: int,
             status: str, error_msg=None) -> None:
    provider = _provider_from_base_url(base_url)
    cost = None
    if input_tok is not None and output_tok is not None:
        cost = calc_cost(model or "", input_tok, output_tok)
    error_type = _classify_error(error_msg) if error_msg else None
    sanitized_error = _sanitize_error(error_msg) if error_msg else None
    write_call(
        project=_project,
        operation=_op_var.get() or "unknown",
        provider=provider,
        model=model or "unknown",
        input_tokens=input_tok,
        output_tokens=output_tok,
        latency_ms=latency_ms,
        cost_cny=cost,
        status=status,
        error_msg=sanitized_error,
        error_type=error_type,
        trace_id=_trace_id_var.get() or None,
        session_id=_session_var.get() or None,
    )


def _get_base_url(self_obj) -> str:
    try:
        return str(self_obj._client.base_url)
    except Exception:
        try:
            return str(self_obj.base_url)
        except Exception:
            return ""


# ── Sync stream wrapper ────────────────────────────────────────

class _SyncStreamWrapper:
    def __init__(self, stream, model: str, base_url: str, start: float):
        self._stream = stream
        self._model = model
        self._base_url = base_url
        self._start = start
        self._input_tok = None
        self._output_tok = None

    def __iter__(self):
        try:
            for chunk in self._stream:
                if chunk.usage:
                    self._input_tok = chunk.usage.prompt_tokens
                    self._output_tok = chunk.usage.completion_tokens
                yield chunk
        except Exception as e:
            latency = int((time.monotonic() - self._start) * 1000)
            _record(self._model, self._base_url, None, None, latency, "error", str(e))
            raise
        latency = int((time.monotonic() - self._start) * 1000)
        _record(self._model, self._base_url, self._input_tok, self._output_tok, latency, "ok")

    def __enter__(self):
        self._stream.__enter__()
        return self

    def __exit__(self, *args):
        return self._stream.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self._stream, name)


# ── Async stream wrapper ───────────────────────────────────────

class _AsyncStreamWrapper:
    def __init__(self, stream, model: str, base_url: str, start: float):
        self._stream = stream
        self._model = model
        self._base_url = base_url
        self._start = start
        self._input_tok = None
        self._output_tok = None

    def __aiter__(self):
        return self._aiter_impl()

    async def _aiter_impl(self):
        try:
            async for chunk in self._stream:
                if chunk.usage:
                    self._input_tok = chunk.usage.prompt_tokens
                    self._output_tok = chunk.usage.completion_tokens
                yield chunk
        except Exception as e:
            latency = int((time.monotonic() - self._start) * 1000)
            _record(self._model, self._base_url, None, None, latency, "error", str(e))
            raise
        latency = int((time.monotonic() - self._start) * 1000)
        _record(self._model, self._base_url, self._input_tok, self._output_tok, latency, "ok")

    async def __aenter__(self):
        await self._stream.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self._stream.__aexit__(*args)

    def __getattr__(self, name):
        return getattr(self._stream, name)


# ── Apply patches ──────────────────────────────────────────────

def apply_patches() -> None:
    global _patched
    if _patched:
        return
    _patched = True

    try:
        from openai.resources.chat.completions import Completions
        _orig_sync = Completions.create

        def _patched_sync(self, *args, **kwargs):
            is_stream = kwargs.get("stream", False)
            if is_stream and "stream_options" not in kwargs:
                kwargs["stream_options"] = {"include_usage": True}
            model = kwargs.get("model", "")
            base_url = _get_base_url(self)
            start = time.monotonic()
            try:
                result = _orig_sync(self, *args, **kwargs)
            except Exception as e:
                latency = int((time.monotonic() - start) * 1000)
                _record(model, base_url, None, None, latency, "error", str(e))
                raise
            if is_stream:
                return _SyncStreamWrapper(result, model, base_url, start)
            latency = int((time.monotonic() - start) * 1000)
            usage = getattr(result, "usage", None)
            _record(
                model, base_url,
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
                latency, "ok",
            )
            return result

        Completions.create = _patched_sync
    except Exception:
        pass

    try:
        from openai.resources.chat.async_completions import AsyncCompletions
        _orig_async = AsyncCompletions.create

        async def _patched_async(self, *args, **kwargs):
            is_stream = kwargs.get("stream", False)
            if is_stream and "stream_options" not in kwargs:
                kwargs["stream_options"] = {"include_usage": True}
            model = kwargs.get("model", "")
            base_url = _get_base_url(self)
            start = time.monotonic()
            try:
                result = await _orig_async(self, *args, **kwargs)
            except Exception as e:
                latency = int((time.monotonic() - start) * 1000)
                _record(model, base_url, None, None, latency, "error", str(e))
                raise
            if is_stream:
                return _AsyncStreamWrapper(result, model, base_url, start)
            latency = int((time.monotonic() - start) * 1000)
            usage = getattr(result, "usage", None)
            _record(
                model, base_url,
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
                latency, "ok",
            )
            return result

        AsyncCompletions.create = _patched_async
    except Exception:
        pass
