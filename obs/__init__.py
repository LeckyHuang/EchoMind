"""
obs — 可观测性模块

用法（各子项目 main.py / app.py 启动时）：

    import obs
    obs.init("my-service")

    # 手动埋点一个阶段（如 ASR、文档解析等）
    with obs.span("asr", provider="aliyun") as s:
        result = call_asr(...)

    # 标记当前请求的 trace_id（让同一请求的 LLM 调用自动归入同一链路）
    obs.set_trace_id("abc123")
"""

import contextlib
import time
import uuid

from obs.db import setup_db, write_span
from obs.patch import apply_patches, set_project, set_operation, set_session, set_trace_id, get_trace_id

_service: str = "unknown"


def init(project: str) -> None:
    global _service
    _service = project
    set_project(project)
    setup_db()
    apply_patches()


class SpanContext:
    def __init__(self, span_id: str, trace_id: str):
        self.span_id = span_id
        self.trace_id = trace_id


@contextlib.contextmanager
def span(operation: str, provider: str = None, **metadata):
    span_id = uuid.uuid4().hex[:12]
    trace_id = get_trace_id() or uuid.uuid4().hex[:12]
    set_trace_id(trace_id)
    start = time.time()
    ctx = SpanContext(span_id, trace_id)
    try:
        yield ctx
        write_span(
            span_id=span_id, trace_id=trace_id, service=_service,
            operation=operation, start_ts=start, end_ts=time.time(),
            status="ok", provider=provider,
            metadata=metadata if metadata else None,
        )
    except Exception as e:
        write_span(
            span_id=span_id, trace_id=trace_id, service=_service,
            operation=operation, start_ts=start, end_ts=time.time(),
            status="error", provider=provider,
            error_msg=str(e),
            metadata=metadata if metadata else None,
        )
        raise


__all__ = ["init", "span", "set_trace_id", "get_trace_id", "set_operation", "set_session"]
